import logging
import requests
import statistics
from datetime import datetime, timezone
from sqlalchemy.orm import Session
from sqlalchemy import text

logger = logging.getLogger(__name__)

# ── Batter category definitions ───────────────────────────────────────────────
# Maps DB column name → canonical stat key used in api/services/player.py.
# Pitcher categories excluded until ALG-02b adds pitcher stat columns to DB.

BATTER_COLUMN_TO_STAT = {
    "r":   "R",
    "hr":  "HR",
    "rbi": "RBI",
    "sb":  "SB",
    "avg": "AVG",
}

# Internal api endpoint on the Docker Compose network.
# daily_update.py POSTs computed baselines here after each run.
API_RELOAD_URL = "http://api:8000/internal/reload-baselines"


def _fetch_column(db: Session, table: str, column: str) -> list[float]:
    """
    Fetch all non-NULL values of a single column from a player table.
    Returns a list of floats. Returns empty list if no rows found.
    """
    rows = db.execute(
        text(f"SELECT {column} FROM {table} WHERE {column} IS NOT NULL")
    ).fetchall()
    return [float(row[0]) for row in rows]


def _compute_mean_std(values: list[float]) -> tuple[float, float] | None:
    """
    Compute mean and population standard deviation from a list of values.
    Population std is used because the query covers the entire player pool,
    not a sample.
    Returns None if fewer than 2 values exist (std is undefined).
    Returns None if std is 0 (would cause ZeroDivisionError in z-score).
    """
    if len(values) < 2:
        return None
    mean = statistics.mean(values)
    std  = statistics.pstdev(values)
    if std == 0.0:
        return None
    return mean, std


def compute_and_store(db: Session) -> dict:
    """
    Compute batter league baselines from players_al and players_nl,
    upsert results into the league_baselines table, and return the
    computed values as a dict to be POSTed to the api server.

    Pitcher baselines are deferred until ALG-02b adds pitcher stat columns.

    Return format:
        {
            "batter":  {"R": {"mean": ..., "std": ...}, ...},
            "pitcher": {},
        }
    Returns {"batter": {}, "pitcher": {}} on complete failure.
    """
    computed_at = datetime.now(timezone.utc)
    batter_result = {}

    for col, stat_key in BATTER_COLUMN_TO_STAT.items():
        # Collect non-NULL values from both AL and NL tables
        values = (
            _fetch_column(db, "players_al", col)
            + _fetch_column(db, "players_nl", col)
        )

        computed = _compute_mean_std(values)
        if computed is None:
            logger.warning(
                f"[baselines] skipping batter.{stat_key} — "
                f"insufficient or zero-variance data ({len(values)} rows)"
            )
            continue

        mean, std = computed

        # Upsert: insert new row or update existing (player_type, category) pair
        db.execute(
            text("""
                INSERT INTO league_baselines (player_type, category, mean, std, computed_at)
                VALUES (:pt, :cat, :mean, :std, :ts)
                ON DUPLICATE KEY UPDATE
                    mean        = VALUES(mean),
                    std         = VALUES(std),
                    computed_at = VALUES(computed_at)
            """),
            {
                "pt":   "batter",
                "cat":  stat_key,
                "mean": mean,
                "std":  std,
                "ts":   computed_at,
            },
        )

        batter_result[stat_key] = {"mean": mean, "std": std}
        logger.info(
            f"[baselines] batter.{stat_key}: "
            f"mean={mean:.4f}, std={std:.4f} (n={len(values)})"
        )

    db.commit()
    logger.info("[baselines] upsert complete")
    return {"batter": batter_result, "pitcher": {}}


def push_to_api(baselines: dict) -> None:
    """
    POST computed baselines to api /internal/reload-baselines.
    Failure is logged as a warning and does not raise — baseline push
    must not abort the daily update pipeline.
    """
    if not baselines.get("batter"):
        logger.warning("[baselines] batter result empty — skipping api reload")
        return

    try:
        resp = requests.post(API_RELOAD_URL, json=baselines, timeout=5)
        resp.raise_for_status()
        logger.info("[baselines] api reload triggered successfully")
    except Exception as e:
        logger.warning(f"[baselines] api reload failed: {e}")