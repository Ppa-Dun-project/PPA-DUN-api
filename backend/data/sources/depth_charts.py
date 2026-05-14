import os
import time
import logging
import requests
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

ESPN_TEAMS_URL = "https://site.api.espn.com/apis/site/v2/sports/baseball/mlb/teams"
ESPN_DEPTH_URL = "https://site.api.espn.com/apis/site/v2/sports/baseball/mlb/teams/{team_id}/depthcharts"

TEAMS = [
    # AL
    ("BAL", "AL"), ("BOS", "AL"), ("NYY", "AL"), ("TB",  "AL"), ("TOR", "AL"),
    ("CHW", "AL"), ("CLE", "AL"), ("DET", "AL"), ("KC",  "AL"), ("MIN", "AL"),
    ("HOU", "AL"), ("LAA", "AL"), ("ATH", "AL"), ("SEA", "AL"), ("TEX", "AL"),
    # NL
    ("ARI", "NL"), ("ATL", "NL"), ("CHC", "NL"), ("CIN", "NL"), ("COL", "NL"),
    ("LAD", "NL"), ("MIA", "NL"), ("MIL", "NL"), ("NYM", "NL"), ("PHI", "NL"),
    ("PIT", "NL"), ("SD",  "NL"), ("SF",  "NL"), ("STL", "NL"), ("WSH", "NL"),
]


# ── Scrape ────────────────────────────────────────────────────────────────────

def _fetch_espn_team_ids() -> dict[str, int]:
    """
    Fetch ESPN team_id for all MLB teams via ESPN teams API.
    Returns dict of {abbreviation (upper): espn_team_id}.
    """
    resp  = requests.get(ESPN_TEAMS_URL, timeout=15)
    resp.raise_for_status()
    teams = (
        resp.json()
        .get("sports", [{}])[0]
        .get("leagues", [{}])[0]
        .get("teams", [])
    )
    result = {}
    for entry in teams:
        team = entry.get("team", {})
        abbr = team.get("abbreviation", "").upper()
        tid  = team.get("id")
        if abbr and tid:
            result[abbr] = int(tid)
    logger.info(f"[depth] fetched {len(result)} ESPN team IDs")
    return result



PITCHER_POSITIONS = {"SP", "RP", "CP"}

def _fetch_team_depth(team_id: int, abbr: str) -> list[dict]:
    """
    Fetch depth chart for one team via ESPN JSON API.
    Returns list of dicts: {player_name, position, depth_order, is_pitcher}
    """
    url  = ESPN_DEPTH_URL.format(team_id=team_id)
    resp = requests.get(url, timeout=15)
    resp.raise_for_status()
    data = resp.json()

    rows = []
    depthchart = data.get("depthchart", [])
    if not depthchart:
        return []

    positions_map = depthchart[0].get("positions", {})

    for pos_key, pos_data in positions_map.items():
        position   = pos_data.get("position", {}).get("abbreviation", "").upper()
        is_pitcher = position in PITCHER_POSITIONS
        athletes   = pos_data.get("athletes", [])

        for depth_order, athlete in enumerate(athletes, start=1):
            name = athlete.get("displayName", "").strip()
            if name:
                rows.append({
                    "player_name": name,
                    "position":    position,
                    "depth_order": depth_order,
                    "is_pitcher":  is_pitcher,
                })
    return rows


# ── Update ────────────────────────────────────────────────────────────────────

def _update_players(rows: list[dict], league: str) -> tuple[int, int]:
    """
    Update depth_order in the appropriate batter or pitcher table.

    Strategy:
      - Batters : primary = batters_al/batters_nl based on league,
                  fallback = the other batter table
      - Pitchers: primary = pitchers_al/pitchers_nl based on league,
                  fallback = the other pitcher table
    Match is done by normalize_name() applied to both sides at query time.

    Returns (matched_count, unmatched_count).
    """
    batter_primary   = "batters_al"  if league == "AL" else "batters_nl"
    batter_fallback  = "batters_nl"  if league == "AL" else "batters_al"
    pitcher_primary  = "pitchers_al" if league == "AL" else "pitchers_nl"
    pitcher_fallback = "pitchers_nl" if league == "AL" else "pitchers_al"

    db      = SessionLocal()
    matched = 0

    try:
        for row in rows:
            norm        = normalize_name(row["player_name"])
            depth_order = row["depth_order"]
            position    = row["position"]

            # Route to pitcher or batter tables based on is_pitcher flag
            if row.get("is_pitcher"):
                table_pair = (pitcher_primary, pitcher_fallback)
            else:
                table_pair = (batter_primary, batter_fallback)

            updated = False
            for table in table_pair:
                result = db.execute(
                    text(f"""
                        UPDATE {table}
                        SET depth_order = :depth_order,
                            position    = :position
                        WHERE LOWER(REPLACE(REPLACE(name, '.', ''), '\\'', '''')) = :norm
                    """),
                    {"depth_order": depth_order, "position": position, "norm": norm},
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
    Clear depth_order for all batter and pitcher tables before applying today's data.
    Runs once per pipeline run so stale entries from yesterday do not persist,
    while allowing the 30-team loop to accumulate today's values without
    overwriting each other.
    """
    db = SessionLocal()
    try:
        db.execute(text("UPDATE batters_al  SET depth_order = NULL"))
        db.execute(text("UPDATE batters_nl  SET depth_order = NULL"))
        db.execute(text("UPDATE pitchers_al SET depth_order = NULL"))
        db.execute(text("UPDATE pitchers_nl SET depth_order = NULL"))
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def fetch_and_update() -> None:
    """
    Scrape ESPN depth charts for all 30 teams and update batter and pitcher tables.
    Called by daily_update.py.
    """
    _reset_depth_order()

    try:
        team_id_map = _fetch_espn_team_ids()
    except Exception as e:
        logger.error(f"[depth] Failed to fetch ESPN team IDs: {e}")
        return

    total_matched   = 0
    total_unmatched = 0
    failed_teams    = []

    for abbr, league in TEAMS:
        team_id = team_id_map.get(abbr)
        if team_id is None:
            logger.warning(f"[depth] {abbr}: no ESPN team_id found, skipping")
            failed_teams.append(abbr)
            continue

        try:
            rows = _fetch_team_depth(team_id, abbr)
            if not rows:
                logger.warning(f"[depth] {abbr}: no rows fetched")
                failed_teams.append(abbr)
                continue

            matched, unmatched = _update_players(rows, league)
            total_matched   += matched
            total_unmatched += unmatched
            logger.info(
                f"[depth] {abbr}: fetched={len(rows)} "
                f"matched={matched} unmatched={unmatched}"
            )
            time.sleep(0.5)

        except Exception as e:
            logger.error(f"[depth] {abbr}: failed — {e}")
            failed_teams.append(abbr)

    logger.info(
        f"[depth] done | total_matched={total_matched} "
        f"| total_unmatched={total_unmatched} "
        f"| failed_teams={failed_teams}"
    )


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    fetch_and_update()