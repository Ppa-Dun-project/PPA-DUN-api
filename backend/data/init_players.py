# backend/data/init_players.py
#
# One-time initialization script. Populates batters_al, batters_nl,
# pitchers_al, and pitchers_nl tables by:
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
from db.models import ALBatter, NLBatter, ALPitcher, NLPitcher
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

# MLB_API_URL   = "https://statsapi.mlb.com/api/v1/sports/1/players?season=2025"

# MLB API sport IDs to fetch players from.
# 1=MLB, 11=AAA, 12=AA, 13=High-A, 14=Single-A, 16=Dominican Summer League
SPORT_IDS = [1, 11, 12, 13, 14, 16]
TEAMS_API_URL = "https://statsapi.mlb.com/api/v1/teams?sportId=1&season=2025"

AL_BATTER_SQL_PATH  = os.path.join(os.path.dirname(__file__), "batters_stats_al_2025.sql")
NL_BATTER_SQL_PATH  = os.path.join(os.path.dirname(__file__), "batters_stats_nl_2025.sql")
AL_PITCHER_SQL_PATH = os.path.join(os.path.dirname(__file__), "pitchers_stats_al_2025.sql")
NL_PITCHER_SQL_PATH = os.path.join(os.path.dirname(__file__), "pitchers_stats_nl_2025.sql")

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


def build_match_key(name: str, team: str = "") -> tuple:
    """
    Build a (normalized_name, team_abbr) tuple for matching.
    team is uppercased and used as a secondary key to resolve same-name collisions.
    """
    return (normalize_name(name), team.upper())

def _build_batter_kwargs_no_api(row: dict, temp_id: int) -> dict:
    """
    Build kwargs for a batter that could not be matched to the MLB API.
    Assigns a negative temporary player_id to satisfy the primary key constraint.
    All API-sourced fields are set to None.
    """
    return dict(
        player_id = temp_id,
        name     = row["name"],
        position = row["position"],
        team     = row["team"],

        # API fields — unknown
        first_name     = None,
        last_name      = None,
        primary_number = None,
        birth_date     = None,
        birth_city     = None,
        birth_country  = None,
        height         = None,
        weight         = None,
        current_age    = None,
        position_name  = None,
        team_id        = None,
        bat_side       = None,
        pitch_hand     = None,
        mlb_debut_date = None,
        active         = None,

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

        # Status fields
        injury_status = None,
        depth_order   = None,
        player_value  = None,
        updated_at    = None,
    )


def _build_pitcher_kwargs_no_api(row: dict, temp_id: int) -> dict:
    """
    Build kwargs for a pitcher that could not be matched to the MLB API.
    Assigns a negative temporary player_id to satisfy the primary key constraint.
    All API-sourced fields are set to None.
    """
    return dict(
        player_id = temp_id,
        name     = row["name"],
        position = row["position"],
        team     = row["team"],

        # API fields — unknown
        first_name     = None,
        last_name      = None,
        primary_number = None,
        birth_date     = None,
        birth_city     = None,
        birth_country  = None,
        height         = None,
        weight         = None,
        current_age    = None,
        position_name  = None,
        team_id        = None,
        bat_side       = None,
        pitch_hand     = None,
        mlb_debut_date = None,
        active         = None,

        # Season stats — FVARz inputs
        w    = row["w"],
        sv   = row["sv"],
        so   = row["so"],
        era  = row["era"],
        whip = row["whip"],
        ip   = row["ip"],

        # Season stats — reference only
        l        = row["l"],
        g        = row["g"],
        gs       = row["gs"],
        war      = row["war"],
        fip      = row["fip"],
        h        = row["h"],
        r        = row["r"],
        er       = row["er"],
        hr       = row["hr"],
        bb       = row["bb"],
        hbp      = row["hbp"],
        bf       = row["bf"],
        era_plus = row["era_plus"],
        h9       = row["h9"],
        hr9      = row["hr9"],
        bb9      = row["bb9"],
        so9      = row["so9"],
        so_bb    = row["so_bb"],

        # Status fields
        injury_status = None,
        depth_order   = None,
        player_value  = None,
        updated_at    = None,
    )

def _get_next_temp_id(db: Session, model_class) -> int:
    """
    Return the next available negative player_id for unmatched players.
    Queries the table for the current minimum player_id and returns min - 1.
    If no negative IDs exist yet, returns -1.
    """
    from sqlalchemy import func
    min_id = db.query(func.min(model_class.player_id)).scalar()
    if min_id is None or min_id >= 0:
        return -1
    return min_id - 1


# ── Step 1: Fetch MLB API data ────────────────────────────────────────────────

def fetch_api_players() -> tuple[dict, dict, dict]:
    """
    Fetch all 2025 players across MLB and minor league sport IDs.
    Also fetches team data to build team_id → abbreviation and team_id → league mappings.

    sport_id=1  : MLB (40-man roster)
    sport_id=11 : AAA
    sport_id=12 : AA
    sport_id=13 : High-A
    sport_id=14 : Single-A
    sport_id=16 : Dominican Summer League

    Returns:
      lookup           : dict keyed by (normalized_name, team_abbr) → player dict
      team_id_to_abbr  : dict of team_id → abbreviation (MLB teams only)
      team_id_to_league: dict of team_id → league name (MLB teams only,
                         "American League" / "National League")
    """
    logger.info("Fetching team abbreviations from MLB API...")
    teams_resp = requests.get(TEAMS_API_URL, timeout=15)
    teams_resp.raise_for_status()
    teams = teams_resp.json().get("teams", [])
    team_id_to_abbr = {
        t["id"]: t["abbreviation"] for t in teams
    }
    team_id_to_league = {
        t["id"]: t.get("league", {}).get("name", "") for t in teams
    }

    # Fetch players across all sport IDs — deduplicate by player_id (keep first)
    all_players: dict[int, dict] = {}
    for sport_id in SPORT_IDS:
        url = f"https://statsapi.mlb.com/api/v1/sports/{sport_id}/players?season=2025"
        logger.info(f"Fetching players for sport_id={sport_id}...")
        resp = requests.get(url, timeout=15)
        resp.raise_for_status()
        for p in resp.json().get("people", []):
            pid = p["id"]
            if pid not in all_players:
                all_players[pid] = p
    logger.info(f"Fetched {len(all_players)} unique players across all sport IDs")

    lookup = {}
    for p in all_players.values():
        team_id   = p.get("currentTeam", {}).get("id")
        team_abbr = team_id_to_abbr.get(team_id, "")
        full_name = p.get("fullName", "")

        key_with_team = build_match_key(full_name, team_abbr)
        key_name_only = build_match_key(full_name)

        if key_with_team in lookup:
            logger.warning(f"Duplicate key={key_with_team} for player '{full_name}' | skipping")
        else:
            lookup[key_with_team] = p

        # Also store name-only key for fallback matching
        # Only store if no collision (don't overwrite existing name-only entry)
        if key_name_only not in lookup:
            lookup[key_name_only] = p


    return lookup, team_id_to_abbr, team_id_to_league


# ── Step 2: Parse SQL dump files ──────────────────────────────────────────────

def parse_batter_sql_dump(filepath: str, league: str, api_lookup: dict = None) -> list[dict]:
    """
    Parse an AL or NL SQL dump file (UTF-8) and return a list of row dicts.

    Two-pass parsing for traded players:
      - 1st pass: collect names that have a 2TM/3TM aggregate row
      - 2nd pass: for those names, skip per-team rows and save 2TM/3TM row as team="TOT"
                  for single-team players, process as before

    TWP (Two-Way Players) are allowed through the position=="P" filter
    when their MLB API primaryPosition is confirmed as "TWP".

    Column layouts:
      AL: Name, Position, Team, AB, R, H, HR, 2B, 3B, RBI, BB, K, SB, CS,
          AVG, OBP, SLG  (no 1B column; single derived as H - 2B - 3B - HR)
      NL: Name, Position, Team, AB, R, H, 1B, 2B, 3B, HR, RBI, BB, K, SB, CS,
          AVG, OBP, SLG  (1B column present)
    """
    logger.info(f"Parsing {league} SQL dump: {filepath}")

    with open(filepath, "r", encoding="utf-8") as f:
        content = f.read()

    match = re.search(r"INSERT INTO\s+`\w+`\s+VALUES\s*(.*?);", content, re.DOTALL)
    if not match:
        raise ValueError(f"No INSERT VALUES block found in {filepath}")

    values_block = match.group(1)
    row_pattern = re.compile(r"\(([^)]+)\)")

    # 1st pass: collect names that have a 2TM/3TM aggregate row
    traded_names = set()
    for row_match in row_pattern.finditer(values_block):
        raw_row = row_match.group(1)
        fields = re.findall(r"'(?:[^'\\]|\\.)*'|[^,]+", raw_row)
        fields = [f.strip().strip("'") for f in fields]
        try:
            name = fields[0]
            team = fields[2]
        except IndexError:
            continue
        if team in ("2TM", "3TM"):
            traded_names.add(name)

    # 2nd pass: parse rows
    rows = []
    for row_match in row_pattern.finditer(values_block):
        raw_row = row_match.group(1)
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

        # Traded player handling
        if name in traded_names:
            if team not in ("2TM", "3TM"):
                continue
            team = "TOT"
        else:
            if team in ("2TM", "3TM"):
                continue

        team = TEAM_ABBR_MAP.get(team, team)

        # Skip pitchers — batter tables contain batters only
        # TWP (Two-Way Players) are allowed through to batter table
        if position == "P":
            is_twp = False
            if api_lookup:
                candidate = api_lookup.get(build_match_key(name, team)) \
                            or api_lookup.get(build_match_key(name))
                if candidate and candidate.get(
                    "primaryPosition", {}
                ).get("abbreviation") == "TWP":
                    is_twp = True
            if not is_twp:
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


# ── Step 2b: Parse pitcher SQL dump files ─────────────────────────────────────

def parse_pitcher_sql_dump(filepath: str, league: str, api_lookup: dict = None) -> list[dict]:
    """
    Parse an AL or NL pitcher SQL dump file (UTF-8, pre-converted from UTF-16LE)
    and return a list of row dicts.

    Two-pass parsing for traded players:
      - 1st pass: collect names that have a 2TM/3TM aggregate row
      - 2nd pass: for those names, skip per-team rows and save 2TM/3TM row as team="TOT"

    Column layout (35 columns, 0-indexed):
      [0]Rk, [1]Player, [2]Age, [3]Team, [4]WAR,
      [5]W, [6]L, [7]W-L%, [8]ERA, [9]G, [10]GS,
      [11]GF, [12]CG, [13]SHO, [14]SV, [15]IP,
      [16]H, [17]R, [18]ER, [19]HR, [20]BB,
      [21]IBB, [22]SO, [23]HBP, [24]BK, [25]WP,
      [26]BF, [27]ERA+, [28]FIP, [29]WHIP,
      [30]H9, [31]HR9, [32]BB9, [33]SO9, [34]SO/BB

    Filtering rules:
      - Skip non-aggregate per-team rows for traded players
      - Skip non-pitcher rows: IP < 10.0
      - Skip trailing NULL rows: Player is NULL or empty
    """
    logger.info(f"Parsing {league} pitcher SQL dump: {filepath}")

    with open(filepath, "r", encoding="utf-8") as f:
        content = f.read()

    match = re.search(r"INSERT INTO\s+`\w+`\s+VALUES\s*(.*?);", content, re.DOTALL)
    if not match:
        raise ValueError(f"No INSERT VALUES block found in {filepath}")

    values_block = match.group(1)
    row_pattern  = re.compile(r"\(([^)]+)\)")

    # 1st pass: collect traded player names
    traded_names = set()
    for row_match in row_pattern.finditer(values_block):
        raw_row = row_match.group(1)
        fields  = re.findall(r"'(?:[^'\\]|\\.)*'|[^,]+", raw_row)
        fields  = [f.strip().strip("'") for f in fields]
        try:
            name = fields[1].replace("*", "").strip()
            team = fields[3].strip()
        except IndexError:
            continue
        if team in ("2TM", "3TM"):
            traded_names.add(name)

    # 2nd pass: parse rows
    rows = []
    for row_match in row_pattern.finditer(values_block):
        raw_row = row_match.group(1)
        fields  = re.findall(r"'(?:[^'\\]|\\.)*'|[^,]+", raw_row)
        fields  = [f.strip().strip("'") for f in fields]

        try:
            raw_name = fields[1].replace("*", "").strip()
            if not raw_name or raw_name.upper() == "NULL":
                continue

            team = fields[3].strip()

            # Traded player handling
            if raw_name in traded_names:
                if team not in ("2TM", "3TM"):
                    continue  # skip per-team rows
                team = "TOT"
            else:
                if team in ("2TM", "3TM"):
                    continue  # safety guard

            team = TEAM_ABBR_MAP.get(team, team)

            def _int(val: str):
                v = val.strip()
                return int(v) if v and v.upper() != "NULL" else None

            def _float(val: str):
                v = val.strip()
                return float(v) if v and v.upper() != "NULL" else None

            ip = _float(fields[15])

            # Skip non-pitchers (position players with mop-up appearances)
            # TWP (Two-Way Players) with sufficient IP are allowed through to pitcher table
            if ip is None or ip < 10.0:
                continue

            # For TWP: confirm via MLB API that this player is a Two-Way Player
            if api_lookup:
                candidate = api_lookup.get(build_match_key(raw_name, team)) \
                            or api_lookup.get(build_match_key(raw_name))
                if candidate:
                    pos_abbr = candidate.get("primaryPosition", {}).get("abbreviation")
                    # Non-pitcher, non-TWP appearing in pitcher dump — skip
                    if pos_abbr not in ("P", "TWP"):
                        continue

            rows.append({
                "name":     raw_name,
                "position": "P",
                "team":     team,

                # FVARz inputs
                "w":    _int(fields[5]),
                "sv":   _int(fields[14]),
                "so":   _int(fields[22]),
                "era":  _float(fields[8]),
                "whip": _float(fields[29]),
                "ip":   ip,

                # Reference stats
                "l":        _int(fields[6]),
                "g":        _int(fields[9]),
                "gs":       _int(fields[10]),
                "war":      _float(fields[4]),
                "fip":      _float(fields[28]),
                "h":        _int(fields[16]),
                "r":        _int(fields[17]),
                "er":       _int(fields[18]),
                "hr":       _int(fields[19]),
                "bb":       _float(fields[20]),
                "hbp":      _int(fields[23]),
                "bf":       _int(fields[26]),
                "era_plus": _float(fields[27]),
                "h9":       _float(fields[30]),
                "hr9":      _float(fields[31]),
                "bb9":      _float(fields[32]),
                "so9":      _float(fields[33]),
                "so_bb":    _float(fields[34]),
            })

        except (IndexError, ValueError):
            continue

    logger.info(f"Parsed {len(rows)} pitcher rows from {league} dump")
    return rows


# ── Step 3: Match and insert ──────────────────────────────────────────────────

def _build_batter_kwargs(row: dict, api_player: dict, team_id_to_abbr: dict) -> dict:
    """
    Build the keyword arguments dict shared by both ALBatter and NLBatter
    constructors. Centralizes the field mapping so it is not duplicated.
    For traded players (row["team"] == "TOT"), team is resolved from MLB API currentTeam.
    """
    team_id = api_player.get("currentTeam", {}).get("id")
    team = team_id_to_abbr.get(team_id, row["team"])

    return dict(
        # Identity from SQL dump (use API full name to preserve Unicode)
        name     = api_player.get("fullName", row["name"]),
        position = row["position"],
        team     = team,

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
        team_id        = team_id, # api_player.get("currentTeam", {}).get("id"),
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


def _build_pitcher_kwargs(row: dict, api_player: dict, team_id_to_abbr: dict) -> dict:
    """
    Build the keyword arguments dict shared by both ALPitcher and NLPitcher
    constructors. Centralizes the field mapping so it is not duplicated.
    For traded players (row["team"] == "TOT"), team is resolved from MLB API currentTeam.
    """
    team_id = api_player.get("currentTeam", {}).get("id")
    team = team_id_to_abbr.get(team_id, row["team"])

    return dict(
        # Identity from SQL dump (use API full name to preserve Unicode)
        name     = api_player.get("fullName", row["name"]),
        position = row["position"],   # "P" at init; overwritten by ESPN depth chart
        team     = team,

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
        team_id        = team_id, # api_player.get("currentTeam", {}).get("id"),
        bat_side       = api_player.get("batSide", {}).get("code"),
        pitch_hand     = api_player.get("pitchHand", {}).get("code"),
        mlb_debut_date = api_player.get("mlbDebutDate"),
        active         = 1 if api_player.get("active") else 0,

        # Season stats — FVARz inputs
        w    = row["w"],
        sv   = row["sv"],
        so   = row["so"],
        era  = row["era"],
        whip = row["whip"],
        ip   = row["ip"],

        # Season stats — reference only
        l        = row["l"],
        g        = row["g"],
        gs       = row["gs"],
        war      = row["war"],
        fip      = row["fip"],
        h        = row["h"],
        r        = row["r"],
        er       = row["er"],
        hr       = row["hr"],
        bb       = row["bb"],
        hbp      = row["hbp"],
        bf       = row["bf"],
        era_plus = row["era_plus"],
        h9       = row["h9"],
        hr9      = row["hr9"],
        bb9      = row["bb9"],
        so9      = row["so9"],
        so_bb    = row["so_bb"],

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
    team_id_to_abbr: dict,
    team_id_to_league: dict,
    seen_name_team: set,   # shared across all calls
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
    seen_ids = set()

    # Negative IDs for players unmatched to MLB API
    # Start from -1 and decrement to avoid collision with real player_ids
    temp_id_counter = _get_next_temp_id(db, model_class)

    for row in sql_rows:
        # Primary match: (name, team)
        key = build_match_key(row["name"], row["team"])
        api_player = api_lookup.get(key)

        # Fallback: name only
        if api_player is None:
            key_name_only = build_match_key(row["name"])
            api_player = api_lookup.get(key_name_only)

        if api_player is None:
            # Deduplicate unmatched players by (name, team)
            name_team_key = (row["name"], row["team"])
            if name_team_key in seen_name_team:
                logger.warning(f"DUPLICATE unmatched name={row['name']} team={row['team']} | skipping")
                continue
            seen_name_team.add(name_team_key)

            unmatched_logger.warning(
                f"UNMATCHED | league={league} name={row['name']} team={row['team']}"
            )
            unmatched += 1
            
            # Save to main table with player_id=NULL — API fields will be NULL
            if model_class in (ALPitcher, NLPitcher):
                kwargs = _build_pitcher_kwargs_no_api(row, temp_id_counter)
            else:
                kwargs = _build_batter_kwargs_no_api(row, temp_id_counter)
            temp_id_counter -= 1

            player = model_class(**kwargs)
            db.merge(player)
            continue

        # League validation — MLB players only (minor leaguers have no league mapping)
        api_team_id  = api_player.get("currentTeam", {}).get("id")
        api_league   = team_id_to_league.get(api_team_id, "")
        if api_league:  # empty string means minor leaguer → skip validation
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

        # Skip if this player_id was already inserted in this session
        pid = api_player["id"]
        if pid in seen_ids:
            logger.warning(f"DUPLICATE player_id={pid} name={row['name']} | skipping")
            continue
        seen_ids.add(pid)

        if model_class in (ALPitcher, NLPitcher):
            kwargs = _build_pitcher_kwargs(row, api_player, team_id_to_abbr)
        else:
            kwargs = _build_batter_kwargs(row, api_player, team_id_to_abbr)
        player = model_class(**kwargs)
        db.merge(player)
        matched += 1

    db.commit()
    logger.info(f"{league}: inserted/updated {matched} | unmatched {unmatched}")


# ── Entry point ───────────────────────────────────────────────────────────────

def run():
    # Create all tables (batters_al, batters_nl, pitchers_al, pitchers_nl, etc.)
    # if they do not yet exist. Safe to call on every run — existing tables
    # are never dropped.
    Base.metadata.create_all(bind=engine)

    api_lookup, team_id_to_abbr, team_id_to_league = fetch_api_players()

    al_batter_rows  = parse_batter_sql_dump(AL_BATTER_SQL_PATH, "AL", api_lookup)
    nl_batter_rows  = parse_batter_sql_dump(NL_BATTER_SQL_PATH, "NL", api_lookup)
    al_pitcher_rows = parse_pitcher_sql_dump(AL_PITCHER_SQL_PATH, "AL", api_lookup)
    nl_pitcher_rows = parse_pitcher_sql_dump(NL_PITCHER_SQL_PATH, "NL", api_lookup)

    db = SessionLocal()
    try:
        # Shared deduplication set across all insert_league calls
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