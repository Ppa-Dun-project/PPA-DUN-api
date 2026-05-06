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
API_VALUE_URL = os.getenv(
    "API_VALUE_URL",
    "http://api:8000/player/value",
)

INTERNAL_API_KEY = os.getenv("INTERNAL_API_KEY", "")


# ── Step 0: Compute league baselines ─────────────────────────────────────────

def _step_baselines() -> None:
    from backend.data.pipeline.compute_baselines import compute_and_store, push_to_api
    db = SessionLocal()
    try:
        baselines = compute_and_store(db)
    finally:
        db.close()
    push_to_api(baselines)


# ── Step 1: Injuries ──────────────────────────────────────────────────────────

def _step_injuries() -> None:
    from backend.data.sources.injury import fetch_and_update
    fetch_and_update()


# ── Step 2: Depth Charts ──────────────────────────────────────────────────────

def _step_depth_charts() -> None:
    from backend.data.sources.depth_charts import fetch_and_update
    fetch_and_update()


# ── Step 3: Recalculate player_value ─────────────────────────────────────────

def _fetch_all_batters(db, table: str) -> list[dict]:
    """
    Fetch all batter rows needed for FVARz recalculation.
    """
    rows = db.execute(
        text(f"""
            SELECT player_id, position,
                   ab, r, hr, rbi, sb, cs, avg,
                   current_age, injury_status, depth_order
            FROM {table}
        """)
    ).fetchall()

    return [
        {
            "player_id":     row.player_id,
            "position":      row.position,
            "player_type":   "batter",
            "ab":            row.ab,
            "r":             row.r,
            "hr":            row.hr,
            "rbi":           row.rbi,
            "sb":            row.sb,
            "cs":            row.cs,
            "avg":           row.avg,
            "current_age":   row.current_age,
            "injury_status": row.injury_status,
            "depth_order":   row.depth_order,
            "table":         table,
        }
        for row in rows
    ]

def _fetch_all_pitchers(db, table: str) -> list[dict]:
    """
    Fetch all pitcher rows needed for FVARz recalculation.
    """
    rows = db.execute(
        text(f"""
            SELECT player_id, position,
                   w, sv, so, era, whip, ip,
                   current_age, injury_status, depth_order
            FROM {table}
        """)
    ).fetchall()

    return [
        {
            "player_id":     row.player_id,
            "position":      row.position,
            "player_type":   "pitcher",
            "w":             row.w,
            "sv":            row.sv,
            "so":            row.so,
            "era":           row.era,
            "whip":          row.whip,
            "ip":            row.ip,
            "current_age":   row.current_age,
            "injury_status": row.injury_status,
            "depth_order":   row.depth_order,
            "table":         table,
        }
        for row in rows
    ]




def _call_player_value(player: dict) -> float | None:
    """
    POST to /player/value and return player_value float.
    Handles both batters and pitchers based on player_type field.
    Returns None on failure.
    """
    position    = (player["position"] or "").upper()
    player_type = player.get("player_type", "batter")

    if player_type == "pitcher":
        if player["ip"] is None or player["era"] is None:
            return None
        stats_payload = {
            "player_type":   "pitcher",
            "IP":            player["ip"]   or 0.0,
            "W":             player["w"]    or 0,
            "SV":            player["sv"]   or 0,
            "K":             player["so"]   or 0,
            "ERA":           player["era"]  or 0.0,
            "WHIP":          player["whip"] or 0.0,
            "age":           player["current_age"],
            "depth_order":   player["depth_order"],
            "injury_status": player["injury_status"],
        }
    else:
        if player["ab"] is None or player["avg"] is None:
            return None
        stats_payload = {
            "player_type":   "batter",
            "AB":            player["ab"]   or 0,
            "R":             player["r"]    or 0,
            "HR":            player["hr"]   or 0,
            "RBI":           player["rbi"]  or 0,
            "SB":            player["sb"]   or 0,
            "CS":            player["cs"]   or 0,
            "AVG":           player["avg"]  or 0.0,
            "age":           player["current_age"],
            "depth_order":   player["depth_order"],
            "injury_status": player["injury_status"],
        }

    payload = {
        "player_name": str(player["player_id"]),
        "position":    position,
        "stats":       stats_payload,
    }

    try:
        resp = requests.post(
            API_VALUE_URL,
            json=payload,
            headers={"X-API-Key": INTERNAL_API_KEY},
            timeout=5,
        )
        resp.raise_for_status()
        return resp.json()["player_value"]
    except Exception as e:
        logger.warning(f"[recalculate] player_id={player['player_id']} failed: {e}")
        return None


def _step_recalculate() -> None:
    """
    Fetch all batter and pitcher rows from all four tables, compute
    player_value using FVARz, and write the result back to the DB.
    """
    db = SessionLocal()
    try:
        players = (
            _fetch_all_batters(db, "batters_al")
            + _fetch_all_batters(db, "batters_nl")
            + _fetch_all_pitchers(db, "pitchers_al")
            + _fetch_all_pitchers(db, "pitchers_nl")
        )
    finally:
        db.close()

    logger.info(f"[recalculate] total players/pitchers to process: {len(players)}")

    updated = 0
    skipped = 0
    failed  = 0

    for player in players:
        new_value = _call_player_value(player)
        if new_value is None:
            skipped += 1
            continue

        db = SessionLocal()
        try:
            db.execute(
                text(f"""
                    UPDATE {player['table']}
                    SET player_value = :value,
                        updated_at   = :ts
                    WHERE player_id = :pid
                """),
                {
                    "value": new_value,
                    "ts":    datetime.now(),
                    "pid":   player["player_id"],
                },
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

    logger.info(f"[recalculate] updated={updated} | skipped={skipped} | failed={failed}")


# ── Pipeline ──────────────────────────────────────────────────────────────────

def run_daily_update() -> None:
    """
    Run the full daily pipeline:
      Step 0 — Compute league baselines and push to api server
      Step 1 — Fetch and apply injury data
      Step 2 — Fetch and apply depth chart data
      Step 3 — Recalculate player_value for all players
    Each step runs independently; failure in one step does not abort the rest.
    """
    start   = datetime.now()
    results = {}
    logger.info("=== Daily update started ===")

    # Step 0: Baselines
    try:
        logger.info("[0/3] Computing league baselines...")
        _step_baselines()
        results["baselines"] = "OK"
    except Exception as e:
        logger.error(f"[0/3] Baselines failed: {e}")
        results["baselines"] = f"FAILED: {e}"

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