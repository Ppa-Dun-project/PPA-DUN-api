# backend/data/init_players.py
#
# One-time initialization script. Populates players_al and players_nl tables by:
#   1. Fetching all 2025 MLB players from the MLB Stats API (statsapi.mlb.com)
#   2. Parsing AL and NL season stats from local SQL dump files
#   3. Matching each SQL dump row to an API player using (normalized_name, team)
#   4. Inserting matched rows into the appropriate league table
#
# Run once after the DB is initialized:
#   python -m data.init_players
#
# Unmatched rows are logged to init_players_unmatched.log for review.

import os
import re
import logging
import unicodedata
import requests
from dotenv import load_dotenv
load_dotenv()

from sqlalchemy.orm import Session
from db.session import SessionLocal, engine, Base
from db.models import ALPlayer, NLPlayer, UnmatchedPlayer
from data.utils import normalize_name

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)

# File handler for unmatched rows
unmatched_handler = logging.FileHandler("init_players_unmatched.log")
unmatched_handler.setLevel(logging.WARNING)
unmatched_logger = logging.getLogger("unmatched")
unmatched_logger.addHandler(unmatched_handler)

# ── Constants ─────────────────────────────────────────────────────────────────

MLB_API_URL   = "https://statsapi.mlb.com/api/v1/sports/1/players?season=2025"
TEAMS_API_URL = "https://statsapi.mlb.com/api/v1/teams?sportId=1&season=2025"

AL_SQL_PATH = os.path.join(os.path.dirname(__file__), "players_stats_al_2025.sql")
NL_SQL_PATH = os.path.join(os.path.dirname(__file__), "players_stats_nl_2025.sql")

# SQL dump team abbreviations that differ from MLB API abbreviations.
TEAM_ABBR_MAP = {
    "CHW": "CWS",
    "KCR": "KC",
    "TBR": "TB",
    "ARI": "AZ",
    "WAS": "WSH",
}

# Baseball Reference numeric position codes mapped to standard abbreviations.
# Keys are single characters extracted from the raw position string.
_BR_NUM_TO_POS = {
    "1": "P",
    "2": "C",
    "3": "1B",
    "4": "2B",
    "5": "3B",
    "6": "SS",
    "7": "OF",
    "8": "OF",
    "9": "OF",
    "D": "DH",
}


# ── Helpers ───────────────────────────────────────────────────────────────────

def _normalize_position_al(raw: str) -> str:
    """
    Convert a Baseball Reference AL position string to a standard abbreviation.

    Baseball Reference encodes positions as numeric strings with modifiers:
      - Leading '*' marks a primary position (e.g. '*9' = primary RF)
      - '/' separates primary from secondary positions
      - 'H' = pinch hitter (not a fielding position — skip to next char)
      - 'D' = designated hitter

    Strategy: strip '*', take the first meaningful character, map via _BR_NUM_TO_POS.
    Falls back to 'UTIL' if the code is unrecognized.

    Examples:
      '9D/H'  -> '9' -> 'OF'
      '*6/DH' -> '6' -> 'SS'
      '*2H/D' -> '2' -> 'C'
      'D9/H'  -> 'D' -> 'DH'
      '3/DH'  -> '3' -> '1B'
    """
    cleaned = raw.strip().lstrip("*")
    if not cleaned:
        return "UTIL"

    first = cleaned[0].upper()

    # 'H' as first char = pinch hitter only; look at next char for fielding position
    if first == "H":
        if len(cleaned) > 1 and cleaned[1].upper() in _BR_NUM_TO_POS:
            return _BR_NUM_TO_POS[cleaned[1].upper()]
        return "UTIL"

    return _BR_NUM_TO_POS.get(first, "UTIL")


def _normalize_position_nl(raw: str) -> str:
    """
    Normalize an NL dump position string to a standard abbreviation.

    NL dump positions are already standard abbreviations but may be
    comma-separated multi-position strings (e.g. '2B,3B,SS').
    Take the first listed position as the primary.

    Examples:
      'OF'       -> 'OF'
      '2B,3B,SS' -> '2B'
      'C,1B'     -> 'C'
      'U,P'      -> 'UTIL'
    """
    first = raw.split(",")[0].strip()
    if first in ("U", ""):
        return "UTIL"
    return first


# def normalize_name(name: str) -> str:
#     """
#     Normalize a player name for matching:
#       1. Unescape SQL escape sequences (e.g. \\' → ')
#       2. Strip NFD diacritics so accented characters compare as ASCII
#       3. Lowercase and strip whitespace

#     Examples:
#       "Julio Rodríguez"   → "julio rodriguez"
#       "Travis d\\'Arnaud" → "travis d'arnaud"
#       "Tyler O\\'Neill"   → "tyler o'neill"
#     """
#     name = name.replace("\\'", "'")
#     # Remove periods so "C.J." matches "CJ", "Jr." matches "Jr"
#     name = name.replace(".", "")
#     nfkd = unicodedata.normalize("NFKD", name)
#     ascii_name = "".join(c for c in nfkd if not unicodedata.combining(c))
#     return ascii_name.lower().strip()


def build_match_key(name: str, team: str = "", position: str = "") -> tuple:
    """Build a (normalized_name,) tuple for matching."""
    return (normalize_name(name),)


# ── Step 1: Fetch MLB API data ────────────────────────────────────────────────

def fetch_api_players() -> tuple[dict, dict]:
    """
    Fetch all 2025 MLB players from the Stats API.
    Also fetches team data to build a team_id → abbreviation mapping.

    Returns:
      lookup       : dict keyed by (normalized_name, team_abbr) → player dict
      team_id_map  : dict of team_id → abbreviation
    """
    logger.info("Fetching team abbreviations from MLB API...")
    teams_resp = requests.get(TEAMS_API_URL, timeout=15)
    teams_resp.raise_for_status()
    team_id_to_abbr = {
        t["id"]: t["abbreviation"]
        for t in teams_resp.json().get("teams", [])
    }

    logger.info("Fetching player list from MLB API...")
    players_resp = requests.get(MLB_API_URL, timeout=15)
    players_resp.raise_for_status()
    api_players = players_resp.json().get("people", [])
    logger.info(f"Fetched {len(api_players)} players from MLB API")

    lookup = {}
    for p in api_players:
        team_id  = p.get("currentTeam", {}).get("id")
        # team_abbr = team_id_to_abbr.get(team_id, "")
        full_name = p.get("fullName", "")

        key = build_match_key(full_name)

        # If two players share the same normalized name + team (extremely rare),
        # keep both in a list and take the first match at insert time.
        if key in lookup:
            if not isinstance(lookup[key], list):
                lookup[key] = [lookup[key]]
            lookup[key].append(p)
        else:
            lookup[key] = p

    return lookup, team_id_to_abbr


# ── Step 2: Parse SQL dump files ──────────────────────────────────────────────

def parse_sql_dump(filepath: str, league: str) -> list[dict]:
    """
    Parse an AL or NL SQL dump file (UTF-8) and return a list of row dicts.

    Column layouts:
      AL: Name, Position, Team, AB, R, H, HR, 2B, 3B, RBI, BB, K, SB, CS,
          AVG, OBP, SLG  (no 1B column; single derived as H - 2B - 3B - HR)
      NL: Name, Position, Team, AB, R, H, 1B, 2B, 3B, HR, RBI, BB, K, SB, CS,
          AVG, OBP, SLG  (1B column present)
    """
    logger.info(f"Parsing {league} SQL dump: {filepath}")

    with open(filepath, "r", encoding="utf-8") as f:
        content = f.read()

    # The INSERT statement spans a single logical line ending with ;
    match = re.search(r"INSERT INTO\s+`\w+`\s+VALUES\s*(.*?);", content, re.DOTALL)
    if not match:
        raise ValueError(f"No INSERT VALUES block found in {filepath}")

    values_block = match.group(1)

    # Each row is wrapped in parentheses: (...), (...), ...
    # The inner regex captures quoted strings (handling \' escapes) and
    # unquoted numbers / NULL values.
    row_pattern = re.compile(r"\(([^)]+)\)")
    rows = []

    for row_match in row_pattern.finditer(values_block):
        raw_row = row_match.group(1)

        # Split fields while respecting quoted strings that may contain commas.
        # Pattern: quoted string (with \' escape support) OR bare token.
        fields = re.findall(r"'(?:[^'\\]|\\.)*'|[^,]+", raw_row)
        fields = [f.strip().strip("'") for f in fields]

        try:
            if league == "AL":
                name, position, team = fields[0], fields[1], fields[2]
                position = _normalize_position_al(position)
                ab  = int(fields[3])    if fields[3]  else None
                r   = int(fields[4])    if fields[4]  else None
                h   = int(fields[5])    if fields[5]  else None
                hr  = int(fields[6])    if fields[6]  else None
                dbl = int(fields[7])    if fields[7]  else None
                trp = int(fields[8])    if fields[8]  else None
                rbi = int(fields[9])    if fields[9]  else None
                bb  = int(fields[10])   if fields[10] else None
                k   = int(fields[11])   if fields[11] else None
                sb  = int(fields[12])   if fields[12] else None
                cs  = int(fields[13])   if fields[13] else None
                avg = float(fields[14]) if fields[14] else None
                obp = float(fields[15]) if fields[15] else None
                slg = float(fields[16]) if fields[16] else None
                sng = (h - dbl - trp - hr) if all(
                    v is not None for v in [h, dbl, trp, hr]
                ) else None

            else:  # NL
                name, position, team = fields[0], fields[1], fields[2]
                position = _normalize_position_nl(position)
                ab  = int(fields[3])    if fields[3]  else None
                r   = int(fields[4])    if fields[4]  else None
                h   = int(fields[5])    if fields[5]  else None
                sng = int(fields[6])    if fields[6]  else None
                dbl = int(fields[7])    if fields[7]  else None
                trp = int(fields[8])    if fields[8]  else None
                hr  = int(fields[9])    if fields[9]  else None
                rbi = int(fields[10])   if fields[10] else None
                bb  = int(fields[11])   if fields[11] else None
                k   = int(fields[12])   if fields[12] else None
                sb  = int(fields[13])   if fields[13] else None
                cs  = int(fields[14])   if fields[14] else None
                avg = float(fields[15]) if fields[15] else None
                obp = float(fields[16]) if fields[16] else None
                slg = float(fields[17]) if fields[17] else None

        except (IndexError, ValueError):
            continue

        if team == "2TM":
            continue

        team = TEAM_ABBR_MAP.get(team, team)

        # Skip pitchers — position has already been normalized to standard abbreviation
        if position == "P":
            continue

        rows.append({
            "name":     name,
            "position": position,
            "team":     team,
            "ab":  ab,  "r":   r,   "h":  h,
            "single": sng, "double": dbl, "triple": trp,
            "hr": hr,  "rbi": rbi, "bb": bb,
            "k":  k,   "sb":  sb,  "cs": cs,
            "avg": avg, "obp": obp, "slg": slg,
        })

    logger.info(f"Parsed {len(rows)} rows from {league} dump")
    return rows


# ── Step 3: Match and insert ──────────────────────────────────────────────────

def _build_player_kwargs(row: dict, api_player: dict) -> dict:
    """
    Build the keyword arguments dict shared by both ALPlayer and NLPlayer
    constructors. Centralizes the field mapping so it is not duplicated.
    """
    return dict(
        # Identity from SQL dump (use API full name to preserve Unicode)
        name     = api_player.get("fullName", row["name"]),
        position = row["position"],
        team     = row["team"],

        # Identity from MLB API
        player_id      = api_player["id"],
        first_name     = api_player.get("firstName"),
        last_name      = api_player.get("lastName"),
        primary_number = api_player.get("primaryNumber"),
        birth_date     = api_player.get("birthDate"),
        birth_city     = api_player.get("birthCity"),
        birth_country  = api_player.get("birthCountry"),
        height         = api_player.get("height"),
        weight         = api_player.get("weight"),
        current_age    = api_player.get("currentAge"),
        position_name  = api_player.get("primaryPosition", {}).get("name"),
        team_id        = api_player.get("currentTeam", {}).get("id"),
        bat_side       = api_player.get("batSide", {}).get("code"),
        pitch_hand     = api_player.get("pitchHand", {}).get("code"),
        mlb_debut_date = api_player.get("mlbDebutDate"),
        active         = 1 if api_player.get("active") else 0,

        # Season stats
        ab     = row["ab"],
        r      = row["r"],
        h      = row["h"],
        single = row["single"],
        double = row["double"],
        triple = row["triple"],
        hr     = row["hr"],
        rbi    = row["rbi"],
        bb     = row["bb"],
        k      = row["k"],
        sb     = row["sb"],
        cs     = row["cs"],
        avg    = row["avg"],
        obp    = row["obp"],
        slg    = row["slg"],

        # Status fields — null until first daily update
        injury_status = None,
        depth_order   = None,
        player_value  = None,
        updated_at    = None,
    )


def insert_league(
    db: Session,
    sql_rows: list[dict],
    api_lookup: dict,
    model_class,
    league: str,
) -> None:
    """
    Match SQL dump rows for one league to MLB API players and insert them
    into the given ORM model class (ALPlayer or NLPlayer).

    Matching key: (normalize_name(name), team_abbr)
    Unmatched rows are logged to init_players_unmatched.log.
    """
    matched   = 0
    unmatched = 0

    seen_ids = set()

    for row in sql_rows:
        key        = build_match_key(row["name"])
        api_player = api_lookup.get(key)

        if api_player is None:
            unmatched_logger.warning(...)
            unmatched += 1

            # Save to DB for later review
            db.add(UnmatchedPlayer(
                league   = league,
                name     = row["name"],
                team     = row["team"],
                position = row["position"],
                ab       = row.get("ab"),
                r        = row.get("r"),
                h        = row.get("h"),
                hr       = row.get("hr"),
                rbi      = row.get("rbi"),
                sb       = row.get("sb"),
                avg      = row.get("avg"),
            ))
            continue

        # Resolve duplicate-key list (same normalized name, extremely rare)
        if isinstance(api_player, list):
            api_player = api_player[0]

        # Skip if this player_id was already inserted in this session
        pid = api_player["id"]
        if pid in seen_ids:
            logger.warning(f"DUPLICATE player_id={pid} name={row['name']} | skipping")
            continue
        seen_ids.add(pid)

        player = model_class(**_build_player_kwargs(row, api_player))
        db.merge(player)
        matched += 1

    db.commit()
    logger.info(f"{league}: inserted/updated {matched} | unmatched {unmatched}")


# ── Entry point ───────────────────────────────────────────────────────────────

def run():
    # Create players_al and players_nl tables if they do not yet exist.
    # Safe to call on every run — existing tables are never dropped.
    Base.metadata.create_all(bind=engine)

    api_lookup, _ = fetch_api_players()

    al_rows = parse_sql_dump(AL_SQL_PATH, "AL")
    nl_rows = parse_sql_dump(NL_SQL_PATH, "NL")

    db = SessionLocal()
    try:
        insert_league(db, al_rows, api_lookup, ALPlayer, "AL")
        insert_league(db, nl_rows, api_lookup, NLPlayer, "NL")
    finally:
        db.close()

    logger.info("init_players complete")


if __name__ == "__main__":
    run()