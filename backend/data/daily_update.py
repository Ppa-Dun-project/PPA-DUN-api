import os
import sys
import logging
import argparse
import requests
from datetime import datetime
from dotenv import load_dotenv
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

DATABASE_URL = "mysql+pymysql://root:{password}@{host}:3306/{db}".format(
    password=os.getenv("MYSQL_ROOT_PASSWORD", ""),
    host=os.getenv("MYSQL_HOST", "db"),
    db=os.getenv("MYSQL_DATABASE", "ppa_dun_api"),
)
engine       = create_engine(DATABASE_URL, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)

# Internal API endpoint for player_value recalculation (stub).
# Points to the api service inside the Docker Compose network.
API_RECALCULATE_URL = os.getenv(
    "API_RECALCULATE_URL",
    "http://api:8000/player/recalculate",
)


# ── Step 1: Injuries ──────────────────────────────────────────────────────────

def _step_injuries() -> None:
    from data.injury import fetch_and_update
    fetch_and_update()


# ── Step 2: Depth Charts ──────────────────────────────────────────────────────

def _step_depth_charts() -> None:
    from data.depth_charts import fetch_and_update
    fetch_and_update()


# ── Step 3: Recalculate player_value ─────────────────────────────────────────

def _fetch_all_players(db, table: str) -> list[dict]:
    """
    Fetch all rows needed for recalculation from a players table.
    Returns list of dicts with keys: player_id, ab, injury_status, depth_order, table.
    """
    rows = db.execute(
        text(f"""
            SELECT player_id, ab, injury_status, depth_order
            FROM {table}
        """)
    ).fetchall()

    return [
        {
            "player_id":     row.player_id,
            "ab":            row.ab,
            "injury_status": row.injury_status,
            "depth_order":   row.depth_order,
            "table":         table,
        }
        for row in rows
    ]


def _call_recalculate(player: dict) -> int | None:
    """
    POST to /player/recalculate stub and return the player_value integer.
    Returns None on failure.
    """
    payload = {
        "player_id":     player["player_id"],
        "player_type":   "batter",   # stub does not differentiate types
        "ab":            player["ab"],
        "injury_status": player["injury_status"],
        "depth_order":   player["depth_order"],
    }

    try:
        resp = requests.post(API_RECALCULATE_URL, json=payload, timeout=5)
        resp.raise_for_status()
        return resp.json()["player_value"]
    except Exception as e:
        logger.warning(f"[recalculate] player_id={player['player_id']} failed: {e}")
        return None


def _step_recalculate() -> None:
    """
    Fetch all players from both tables, call the recalculate stub for each,
    and write the returned player_value back to the DB.
    """
    db = SessionLocal()
    try:
        players = (
            _fetch_all_players(db, "players_al")
            + _fetch_all_players(db, "players_nl")
        )
    finally:
        db.close()

    logger.info(f"[recalculate] total players to process: {len(players)}")

    updated = 0
    failed  = 0

    for player in players:
        new_value = _call_recalculate(player)
        if new_value is None:
            failed += 1
            continue

        db = SessionLocal()
        try:
            db.execute(
                text(f"""
                    UPDATE {player['table']}
                    SET player_value = :value
                    WHERE player_id = :pid
                """),
                {"value": new_value, "pid": player["player_id"]},
            )
            db.commit()
            updated += 1
        except Exception as e:
            db.rollback()
            logger.error(
                f"[recalculate] DB update failed for player_id={player['player_id']}: {e}"
            )
            failed += 1
        finally:
            db.close()

    logger.info(f"[recalculate] updated={updated} | failed={failed}")


# ── Pipeline ──────────────────────────────────────────────────────────────────

def run_daily_update() -> None:
    """
    Run the full daily pipeline:
      Step 1 — Fetch and apply injury data
      Step 2 — Fetch and apply depth chart data
      Step 3 — Recalculate player_value for all players
    Each step runs independently; failure in one step does not abort the rest.
    """
    start   = datetime.now()
    results = {}
    logger.info("=== Daily update started ===")

    # Step 1: Injuries
    try:
        logger.info("[1/3] Updating injuries...")
        _step_injuries()
        results["injuries"] = "OK"
    except Exception as e:
        logger.error(f"[1/3] Injuries failed: {e}")
        results["injuries"] = f"FAILED: {e}"

    # Step 2: Depth charts
    try:
        logger.info("[2/3] Updating depth charts...")
        _step_depth_charts()
        results["depth_charts"] = "OK"
    except Exception as e:
        logger.error(f"[2/3] Depth charts failed: {e}")
        results["depth_charts"] = f"FAILED: {e}"

    # Step 3: Recalculate player_value
    try:
        logger.info("[3/3] Recalculating player_value...")
        _step_recalculate()
        results["player_value"] = "OK"
    except Exception as e:
        logger.error(f"[3/3] player_value recalculation failed: {e}")
        results["player_value"] = f"FAILED: {e}"

    elapsed = (datetime.now() - start).total_seconds()
    logger.info(f"=== Daily update finished in {elapsed:.1f}s ===")
    for name, status in results.items():
        logger.info(f"  {name}: {status}")


# ── Scheduler ─────────────────────────────────────────────────────────────────

def start_scheduler():
    """
    Start a background scheduler that runs run_daily_update() at 3:00 AM ET daily.
    Returns the scheduler instance so the caller can shut it down on app exit.
    Called from backend/main.py lifespan event.
    """
    try:
        from apscheduler.schedulers.background import BackgroundScheduler
        from apscheduler.triggers.cron import CronTrigger
    except ImportError:
        logger.error("apscheduler is required: pip install apscheduler")
        return None

    scheduler = BackgroundScheduler()
    scheduler.add_job(
        run_daily_update,
        trigger=CronTrigger(hour=3, minute=0, timezone="America/New_York"),
        id="daily_update",
        name="Daily MLB data update — 3AM ET",
    )
    scheduler.start()
    logger.info("Scheduler started — daily_update runs at 3:00 AM ET")
    return scheduler


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Daily MLB data updater")
    parser.add_argument(
        "--scheduled",
        action="store_true",
        help="Run as a blocking scheduler (3AM ET daily). "
             "Without this flag, runs once immediately and exits.",
    )
    args = parser.parse_args()

    if args.scheduled:
        import time
        scheduler = start_scheduler()
        if scheduler:
            try:
                while True:
                    time.sleep(60)
            except KeyboardInterrupt:
                scheduler.shutdown()
                logger.info("Scheduler stopped")
    else:
        run_daily_update()