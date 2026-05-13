# backend/data/pipeline/init_players.py
#
# One-time initialization script. Populates batters_al, batters_nl,
# pitchers_al, and pitchers_nl tables by:
#   1. Fetching all 2025 MLB players from the MLB Stats API (statsapi.mlb.com)
#   2. Parsing AL and NL season stats from local CSV files (raw_data/)
#   3. Matching each CSV row to an API player using (normalized_name, team)
#   4. Inserting matched rows into the appropriate league table
#
# Run once after the DB is initialized:
#   python -m data.pipeline.init_players
#
# Unmatched rows are logged to init_players_unmatched.log for review.

import logging
import os

from dotenv import load_dotenv
load_dotenv()

from sqlalchemy import func
from sqlalchemy.orm import Session

from db.session import SessionLocal, engine, Base
from db.models import ALBatter, NLBatter, ALPitcher, NLPitcher
from data.sources.mlb_api import fetch_api_players, build_match_key
from data.parsers.csv_parser import parse_batter_csv, parse_pitcher_csv
from data.parsers.player_builder import build_batter_kwargs, build_pitcher_kwargs

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)

# File handler for unmatched rows
unmatched_handler = logging.FileHandler("init_players_unmatched.log", mode="w")
unmatched_handler.setLevel(logging.WARNING)
unmatched_logger = logging.getLogger("unmatched")
unmatched_logger.addHandler(unmatched_handler)

# ── Constants ─────────────────────────────────────────────────────────────────

_DATA_DIR = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
AL_BATTER_CSV_PATH  = os.path.join(_DATA_DIR, "raw_data", "AL_batters.csv")
NL_BATTER_CSV_PATH  = os.path.join(_DATA_DIR, "raw_data", "NL_batters.csv")
AL_PITCHER_CSV_PATH = os.path.join(_DATA_DIR, "raw_data", "AL_pitchers.csv")
NL_PITCHER_CSV_PATH = os.path.join(_DATA_DIR, "raw_data", "NL_pitchers.csv")


# ── Helpers ───────────────────────────────────────────────────────────────────

def _get_next_temp_id(db: Session, model_class) -> int:
    """
    Return the next available negative player_id for unmatched players.
    Queries the table for the current minimum player_id and returns min - 1.
    If no negative IDs exist yet, returns -1.
    """
    min_id = db.query(func.min(model_class.player_id)).scalar()
    if min_id is None or min_id >= 0:
        return -1
    return min_id - 1


# ── Insert ────────────────────────────────────────────────────────────────────

def insert_league(
    db: Session,
    sql_rows: list[dict],
    api_lookup: dict,
    model_class,
    league: str,
    team_id_to_abbr: dict,
    team_id_to_league: dict,
    seen_name_team: set,
) -> None:
    """
    Match SQL dump rows for one league to MLB API players and insert them
    into the given ORM model class (ALBatter, NLBatter, ALPitcher, or NLPitcher).

    Matching strategy:
      1. Primary match: (normalized_name, team_abbr)
      2. Fallback:      (normalized_name, "") — handles traded players (team="TOT")

    League validation is applied to MLB players only (minor leaguers have no AL/NL classification).
    Unmatched rows are logged to init_players_unmatched.log.
    """
    matched   = 0
    unmatched = 0
    seen_ids  = set()

    temp_id_counter = _get_next_temp_id(db, model_class)
    is_pitcher      = model_class in (ALPitcher, NLPitcher)

    for row in sql_rows:
        # Primary match: (name, team)
        key        = build_match_key(row["name"], row["team"])
        api_player = api_lookup.get(key)

        # Fallback: name only
        if api_player is None:
            api_player = api_lookup.get(build_match_key(row["name"]))

        if api_player is None:
            name_team_key = (row["name"], row["team"])
            if name_team_key in seen_name_team:
                logger.warning(f"DUPLICATE unmatched name={row['name']} team={row['team']} | skipping")
                continue
            seen_name_team.add(name_team_key)

            unmatched_logger.warning(
                f"UNMATCHED | league={league} name={row['name']} team={row['team']}"
            )
            unmatched += 1

            build_fn = build_pitcher_kwargs if is_pitcher else build_batter_kwargs
            db.merge(model_class(**build_fn(row, None, team_id_to_abbr, temp_id=temp_id_counter)))
            temp_id_counter -= 1
            continue

        # League validation — MLB players only (minor leaguers have no league mapping)
        api_team_id = api_player.get("currentTeam", {}).get("id")
        api_league  = team_id_to_league.get(api_team_id, "")
        if api_league:
            if league == "AL" and "American" not in api_league:
                unmatched_logger.warning(
                    f"LEAGUE MISMATCH | expected=AL api_league={api_league} "
                    f"name={row['name']} team={row['team']}"
                )
                unmatched += 1
                continue
            if league == "NL" and "National" not in api_league:
                unmatched_logger.warning(
                    f"LEAGUE MISMATCH | expected=NL api_league={api_league} "
                    f"name={row['name']} team={row['team']}"
                )
                unmatched += 1
                continue

        # Skip duplicate player_id within this session
        pid = api_player["id"]
        if pid in seen_ids:
            logger.warning(f"DUPLICATE player_id={pid} name={row['name']} | skipping")
            continue
        seen_ids.add(pid)

        build_fn = build_pitcher_kwargs if is_pitcher else build_batter_kwargs
        db.merge(model_class(**build_fn(row, api_player, team_id_to_abbr)))
        matched += 1

    db.commit()
    logger.info(f"{league}: inserted/updated {matched} | unmatched {unmatched}")


# ── Entry point ───────────────────────────────────────────────────────────────

def run():
    Base.metadata.create_all(bind=engine)

    api_lookup, team_id_to_abbr, team_id_to_league = fetch_api_players()

    al_batter_rows  = parse_batter_csv(AL_BATTER_CSV_PATH, "AL", api_lookup)
    nl_batter_rows  = parse_batter_csv(NL_BATTER_CSV_PATH, "NL", api_lookup)
    al_pitcher_rows = parse_pitcher_csv(AL_PITCHER_CSV_PATH, "AL", api_lookup)
    nl_pitcher_rows = parse_pitcher_csv(NL_PITCHER_CSV_PATH, "NL", api_lookup)

    db = SessionLocal()
    try:
        seen_name_team: set = set()
        insert_league(db, al_batter_rows,  api_lookup, ALBatter,  "AL", team_id_to_abbr, team_id_to_league, seen_name_team)
        insert_league(db, nl_batter_rows,  api_lookup, NLBatter,  "NL", team_id_to_abbr, team_id_to_league, seen_name_team)
        insert_league(db, al_pitcher_rows, api_lookup, ALPitcher, "AL", team_id_to_abbr, team_id_to_league, seen_name_team)
        insert_league(db, nl_pitcher_rows, api_lookup, NLPitcher, "NL", team_id_to_abbr, team_id_to_league, seen_name_team)
    finally:
        db.close()

    logger.info("init_players complete")


if __name__ == "__main__":
    run()