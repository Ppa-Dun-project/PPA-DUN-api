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
    from data.compute_baselines import compute_and_store, push_to_api
    db = SessionLocal()
    try:
        baselines = compute_and_store(db)
    finally:
        db.close()
    push_to_api(baselines)


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
    Fetch all batter rows needed for FVARz recalculation.
    Pitcher stats columns not yet in DB (pending ALG-02b) — pitchers skipped.
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


PITCHER_POSITIONS = {"SP", "RP", "CL"}

def _call_player_value(player: dict) -> float | None:
    """
    POST to /player/value and return player_value float.
    Skips pitchers until pitcher stat columns are added (ALG-02b).
    Returns None on failure or skip.
    """
    position = (player["position"] or "").upper()
    if position in PITCHER_POSITIONS:
        return None

    if player["ab"] is None or player["avg"] is None:
        return None

    payload = {
        "player_name": str(player["player_id"]),
        "position":    position,
        "stats": {
            "player_type":  "batter",
            "AB":  player["ab"]   or 0,
            "R":   player["r"]    or 0,
            "HR":  player["hr"]   or 0,
            "RBI": player["rbi"]  or 0,
            "SB":  player["sb"]   or 0,
            "CS":  player["cs"]   or 0,
            "AVG": player["avg"]  or 0.0,
            "age":          player["current_age"],
            "depth_order":  player["depth_order"],
            "injury_status": player["injury_status"],
        },
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


def _compute_player_value_local(player: dict) -> float | None:
    """
    Compute player_value using FVARz algorithm directly (no HTTP call).
    Skips pitchers until pitcher stat columns are added (ALG-02b).
    Returns None on failure or if player is a pitcher.
    """
    from api.models.player import PlayerValueRequest, BatterStats

    position = (player["position"] or "").upper()
    if position in PITCHER_POSITIONS:
        return None  # pitcher stat columns not yet in DB

    # Skip players with no stat data
    if player["ab"] is None or player["avg"] is None:
        return None

    try:
        request = PlayerValueRequest(
            player_name=str(player["player_id"]),
            position=position,
            stats=BatterStats(
                AB=player["ab"]  or 0,
                R=player["r"]    or 0,
                HR=player["hr"]  or 0,
                RBI=player["rbi"] or 0,
                SB=player["sb"]  or 0,
                CS=player["cs"]  or 0,
                AVG=player["avg"] or 0.0,
                age=player["current_age"],
                depth_order=player["depth_order"],
                injury_status=player["injury_status"],
            ),
        )
        from api.services.player import compute_player_value
        response = compute_player_value(request)
        return response.player_value
    except Exception as e:
        logger.warning(f"[recalculate] player_id={player['player_id']} compute failed: {e}")
        return None


def _step_recalculate() -> None:
    """
    Fetch all players from both tables, compute player_value using FVARz,
    and write the result back to the DB.
    Pitchers are skipped until pitcher stat columns are added (ALG-02b).
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