import os
import time
import logging
import requests
from bs4 import BeautifulSoup
from dotenv import load_dotenv
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from data.utils import normalize_name

load_dotenv()

logger = logging.getLogger(__name__)

DATABASE_URL = "mysql+pymysql://root:{password}@{host}:3306/{db}".format(
    password=os.getenv("MYSQL_ROOT_PASSWORD", ""),
    host=os.getenv("MYSQL_HOST", "db"),
    db=os.getenv("MYSQL_DATABASE", "ppa_dun_api"),
)
engine = create_engine(DATABASE_URL, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/125.0.0.0 Safari/537.36"
    )
}

BASE_URL = "https://www.espn.com/mlb/team/depth/_/name/{slug}"

# (ESPN slug, league)
# League determines which table (players_al or players_nl) to update first
TEAMS = [
    # AL
    ("bal",  "AL"), ("bos",  "AL"), ("nyy",  "AL"), ("tb",   "AL"), ("tor",  "AL"),
    ("chw",  "AL"), ("cle",  "AL"), ("det",  "AL"), ("kc",   "AL"), ("min",  "AL"),
    ("hou",  "AL"), ("laa",  "AL"), ("ath",  "AL"), ("sea",  "AL"), ("tex",  "AL"),
    # NL
    ("ari",  "NL"), ("atl",  "NL"), ("chc",  "NL"), ("cin",  "NL"), ("col",  "NL"),
    ("lad",  "NL"), ("mia",  "NL"), ("mil",  "NL"), ("nym",  "NL"), ("phi",  "NL"),
    ("pit",  "NL"), ("sd",   "NL"), ("sf",   "NL"), ("stl",  "NL"), ("wsh",  "NL"),
]


# ── Scrape ────────────────────────────────────────────────────────────────────

def _scrape_team(slug: str) -> list[dict]:
    """
    Scrape depth chart for one team from ESPN.
    Returns list of dicts: {player_name, position, depth_order}

    ESPN depth chart page layout:
      Table 0: position labels column (P, RP, CL, C, 1B, ...)
      Table 1: player grid (row = position, col = depth_order 1..N)
    """
    url  = BASE_URL.format(slug=slug)
    resp = requests.get(url, headers=HEADERS, timeout=15)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")

    tables = soup.find_all("table")
    if len(tables) < 2:
        logger.warning(f"[depth] {slug}: expected 2 tables, got {len(tables)}")
        return []

    pos_table  = tables[0]   # position label column
    data_table = tables[1]   # player grid

    # Extract position labels (skip header row)
    positions = [
        row.find(["td", "th"]).get_text(strip=True)
        for row in pos_table.find_all("tr")[1:]
        if row.find(["td", "th"])
    ]

    PITCHER_POSITIONS = {"P", "RP", "CL"}

    rows = []
    for row_idx, tr in enumerate(data_table.find_all("tr")[1:]):
        if row_idx >= len(positions):
            break
        position = positions[row_idx]

        # Skip pitchers — players tables contain batters only
        if position in PITCHER_POSITIONS:
            continue

        for depth_order, td in enumerate(tr.find_all("td"), start=1):
            link = td.find("a", href=True)
            if not link:
                continue

            player_name = link.get_text(strip=True)
            if not player_name:
                continue

            rows.append({
                "player_name": player_name,
                "position":    position,
                "depth_order": depth_order,   # 1 = starter, 2 = backup, ...
            })

    return rows


# ── Update ────────────────────────────────────────────────────────────────────

def _update_players(rows: list[dict], league: str) -> tuple[int, int]:
    """
    Update depth_order in the appropriate players table.

    Strategy:
      - Primary table  : players_al if league == "AL", else players_nl
      - Fallback table : the other one (handles traded players)
    Match is done by normalize_name() applied to both sides at query time.

    Returns (matched_count, unmatched_count).
    """
    primary  = "players_al" if league == "AL" else "players_nl"
    fallback = "players_nl" if league == "AL" else "players_al"

    db      = SessionLocal()
    matched = 0

    try:
        for row in rows:
            norm        = normalize_name(row["player_name"])
            depth_order = row["depth_order"]

            updated = False
            for table in (primary, fallback):
                result = db.execute(
                    text(f"""
                        UPDATE {table}
                        SET depth_order = :depth_order
                        WHERE LOWER(REPLACE(REPLACE(name, '.', ''), '\\'', '''')) = :norm
                    """),
                    {"depth_order": depth_order, "norm": norm},
                )
                if result.rowcount > 0:
                    matched += 1
                    updated  = True
                    break

            if not updated:
                logger.debug(f"[depth] UNMATCHED: {row['player_name']}")

        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()

    unmatched = len(rows) - matched
    return matched, unmatched


# ── Public entry point ────────────────────────────────────────────────────────

def _reset_depth_order() -> None:
    """
    Clear depth_order for both players tables before applying today's data.
    Runs once per pipeline run so stale entries from yesterday do not persist,
    while allowing the 30-team loop to accumulate today's values without
    overwriting each other.
    """
    db = SessionLocal()
    try:
        db.execute(text("UPDATE players_al SET depth_order = NULL"))
        db.execute(text("UPDATE players_nl SET depth_order = NULL"))
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def fetch_and_update() -> None:
    """
    Scrape ESPN depth charts for all 30 teams and update players tables.
    Called by daily_update.py.
    """
    _reset_depth_order()

    total_matched   = 0
    total_unmatched = 0
    failed_teams    = []

    for slug, league in TEAMS:
        try:
            rows = _scrape_team(slug)
            if not rows:
                logger.warning(f"[depth] {slug}: no rows scraped")
                failed_teams.append(slug)
                continue

            matched, unmatched = _update_players(rows, league)
            total_matched   += matched
            total_unmatched += unmatched
            logger.info(
                f"[depth] {slug}: scraped={len(rows)} "
                f"matched={matched} unmatched={unmatched}"
            )

            # Polite delay to avoid hammering ESPN
            time.sleep(2)

        except Exception as e:
            logger.error(f"[depth] {slug}: failed — {e}")
            failed_teams.append(slug)

    logger.info(
        f"[depth] done | total_matched={total_matched} "
        f"| total_unmatched={total_unmatched} "
        f"| failed_teams={failed_teams}"
    )


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    fetch_and_update()