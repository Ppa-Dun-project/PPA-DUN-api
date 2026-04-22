import os
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
engine       = create_engine(DATABASE_URL, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)

ESPN_API_URL  = "https://site.api.espn.com/apis/site/v2/sports/baseball/mlb/injuries"
ESPN_HTML_URL = "https://www.espn.com/mlb/injuries"

# Canonical injury status strings stored in DB.
# These exact strings are used by the algorithm's INJURY_PENALTY mapping.
STATUS_MAP = {
    "Day-To-Day":    "Day-To-Day",
    "10-Day IL":     "10-Day IL",
    "10-Day-IL":     "10-Day IL",
    "15-Day IL":     "15-Day IL",
    "15-Day-IL":     "15-Day IL",
    "60-Day IL":     "60-Day IL",
    "60-Day-IL":     "60-Day IL",
    "Out":           "Out",
    "7-Day IL":      "7-Day IL",
    "Suspension":    "Suspension",
    "Bereavement":   "Bereavement",
    "Paternity":     "Paternity",
    "Restricted":    "Restricted List",
}


def _canonicalize(raw: str) -> str:
    """
    Map a raw ESPN status string to our canonical form.
    Falls back to the raw string if no mapping is found,
    so new ESPN statuses are preserved rather than silently dropped.
    """
    return STATUS_MAP.get(raw, raw)


# ── Fetch ─────────────────────────────────────────────────────────────────────

def _fetch_from_api() -> list[dict]:
    """
    Primary source: ESPN JSON API.
    Returns list of dicts with keys: player_name, injury_status.
    Raises on HTTP error or empty response so the caller can fallback.
    """
    resp = requests.get(ESPN_API_URL, timeout=10)
    resp.raise_for_status()
    data = resp.json()

    rows = []
    for team_block in data.get("injuries", []):
        for player in team_block.get("injuries", []):
            athlete    = player.get("athlete", {})
            raw_status = player.get("status", "")
            name       = athlete.get("displayName", "").strip()

            if name and raw_status:
                rows.append({
                    "player_name":   name,
                    "injury_status": _canonicalize(raw_status),
                })

    if not rows:
        raise ValueError("API returned empty injury list")

    return rows


def _fetch_from_html() -> list[dict]:
    """
    Fallback source: ESPN HTML scraping via Selenium + BeautifulSoup.
    Returns list of dicts with keys: player_name, injury_status.

    ESPN injury page column layout per row:
      [0] Player name + position  [1] Date  [2] Detail  [3] Status
    """
    from selenium import webdriver
    from selenium.webdriver.chrome.options import Options
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC
    from bs4 import BeautifulSoup
    import time

    options = Options()
    options.add_argument("--headless")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument(
        "user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
    )

    driver = webdriver.Chrome(options=options)
    rows   = []

    try:
        driver.get(ESPN_HTML_URL)
        WebDriverWait(driver, 15).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "div.ResponsiveTable"))
        )
        time.sleep(3)

        soup = BeautifulSoup(driver.page_source, "html.parser")

        for section in soup.select("div.ResponsiveTable"):
            for tr in section.select("tbody tr"):
                cells = tr.find_all("td")
                if len(cells) < 4:
                    continue

                name       = cells[0].get_text(separator=" ", strip=True)
                raw_status = cells[3].get_text(strip=True)

                if name and raw_status:
                    rows.append({
                        "player_name":   name,
                        "injury_status": _canonicalize(raw_status),
                    })
    finally:
        driver.quit()

    return rows


# ── Update ────────────────────────────────────────────────────────────────────

def _reset_injury_status() -> None:
    """
    Clear injury_status for all players before applying today's data.
    Players not on today's injury report are considered healthy (NULL).
    """
    db = SessionLocal()
    try:
        db.execute(text("UPDATE players_al SET injury_status = NULL"))
        db.execute(text("UPDATE players_nl SET injury_status = NULL"))
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def _update_players(rows: list[dict]) -> tuple[int, int]:
    """
    Update injury_status in players_al and players_nl.
    Matches by normalize_name() applied to both sides at query time.
    Tries players_al first, then players_nl as fallback (handles traded players).
    Returns (matched_count, unmatched_count).
    """
    db      = SessionLocal()
    matched = 0

    try:
        for row in rows:
            norm   = normalize_name(row["player_name"])
            status = row["injury_status"]

            updated = False
            for table in ("players_al", "players_nl"):
                result = db.execute(
                    text(f"""
                        UPDATE {table}
                        SET injury_status = :status
                        WHERE LOWER(REPLACE(REPLACE(name, '.', ''), '\\'', '''')) = :norm
                    """),
                    {"status": status, "norm": norm},
                )
                if result.rowcount > 0:
                    matched += 1
                    updated  = True
                    break

            if not updated:
                logger.debug(f"[injury] UNMATCHED: {row['player_name']}")

        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()

    unmatched = len(rows) - matched
    return matched, unmatched


# ── Public entry point ────────────────────────────────────────────────────────

def fetch_and_update() -> None:
    """
    Fetch injury data (API-first, HTML fallback) and update players tables.
    Called by daily_update.py as Step 1 of the daily pipeline.
    """
    # 1st attempt: JSON API
    try:
        rows   = _fetch_from_api()
        source = "api"
        logger.info(f"[injury] API fetch success: {len(rows)} players")
    except Exception as e:
        logger.warning(f"[injury] API failed ({e}), switching to HTML fallback")
        try:
            rows   = _fetch_from_html()
            source = "html"
            logger.info(f"[injury] HTML fetch success: {len(rows)} players")
        except Exception as e2:
            logger.error(f"[injury] HTML fallback also failed: {e2}")
            return

    if not rows:
        logger.error("[injury] No data retrieved — skipping update")
        return

    # Clear yesterday's injury data before writing today's
    _reset_injury_status()

    matched, unmatched = _update_players(rows)
    logger.info(
        f"[injury] source={source} | fetched={len(rows)} "
        f"| matched={matched} | unmatched={unmatched}"
    )


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    fetch_and_update()