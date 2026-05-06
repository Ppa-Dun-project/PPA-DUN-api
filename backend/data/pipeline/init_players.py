# backend/data/init_players.py
#
# One-time initialization script. Populates batters_al, batters_nl,
# pitchers_al, and pitchers_nl tables by:
#   1. Fetching all 2025 MLB players from the MLB Stats API (statsapi.mlb.com)
#   2. Parsing AL and NL season stats from local CSV files (raw_data/)
#   3. Matching each CSV row to an API player using (normalized_name, team)
#   4. Inserting matched rows into the appropriate league table
#
# Run once after the DB is initialized:
#   python -m data.init_players
#
# Unmatched rows are logged to init_players_unmatched.log for review.

import csv
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
unmatched_handler = logging.FileHandler("init_players_unmatched.log", mode="w")
unmatched_handler.setLevel(logging.WARNING)
unmatched_logger = logging.getLogger("unmatched")
unmatched_logger.addHandler(unmatched_handler)

# ── Constants ─────────────────────────────────────────────────────────────────

# MLB_API_URL   = "https://statsapi.mlb.com/api/v1/sports/1/players?season=2025"

# MLB API sport IDs to fetch players from.
# 1=MLB, 11=AAA, 12=AA, 13=High-A, 14=Single-A, 16=Dominican Summer League
SPORT_IDS = [1, 11, 12, 13, 14, 16]
TEAMS_API_URL = "https://statsapi.mlb.com/api/v1/teams?sportId=1&season=2025"

_DATA_DIR = os.path.dirname(os.path.dirname(__file__))
AL_BATTER_CSV_PATH  = os.path.join(_DATA_DIR, "raw_data", "AL_batters.csv")
NL_BATTER_CSV_PATH  = os.path.join(_DATA_DIR, "raw_data", "NL_batters.csv")
AL_PITCHER_CSV_PATH = os.path.join(_DATA_DIR, "raw_data", "AL_pitchers.csv")
NL_PITCHER_CSV_PATH = os.path.join(_DATA_DIR, "raw_data", "NL_pitchers.csv")

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


# ── Step 2: Parse CSV files ────────────────────────────────────────────────────

def parse_batter_csv(filepath: str, league: str, api_lookup: dict = None) -> list[dict]:
    """
    Parse an AL or NL batter CSV file (UTF-8 with BOM) and return a list of row dicts.

    Both AL and NL CSV files share the same column layout:
      Rk, Player, Age, Team, WAR, G, PA, AB, R, H, 2B, 3B, HR, RBI,
      SB, CS, BB, SO, BA, OBP, SLG, OPS, OPS+, rOBA, Rbat+, TB,
      GIDP, HBP, SH, SF, IBB, Pos, Awards, Player-additional

    1B (single) is not present in either file — derived as H - 2B - 3B - HR.

    Two-pass logic for traded players:
      - 1st pass: collect Player names that appear with Team 2TM or 3TM
      - 2nd pass: for traded players, keep only the 2TM/3TM aggregate row (team="TOT");
                  for single-team players, keep as-is

    TWP (Two-Way Players) are allowed through the position=="P" filter
    when their MLB API primaryPosition is confirmed as "TWP".
    """
    logger.info(f"Parsing {league} batter CSV: {filepath}")

    def _int(val: str):
        v = val.strip()
        return int(v) if v else None

    def _float(val: str):
        v = val.strip()
        return float(v) if v else None

    def _clean_name(raw: str) -> str:
        # Baseball Reference appends '#' (switch hitter) or '*' (left-handed)
        return raw.replace("#", "").replace("*", "").strip()

    with open(filepath, "r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        all_rows = list(reader)

    # 1st pass: collect traded player names
    traded_names = set()
    for row in all_rows:
        if not row.get("Player", "").strip():
            continue
        if row["Team"] in ("2TM", "3TM"):
            traded_names.add(_clean_name(row["Player"]))

    # 2nd pass: parse rows
    rows = []
    for row in all_rows:
        raw_player = row.get("Player", "").strip()
        if not raw_player:
            continue

        try:
            name     = _clean_name(raw_player)
            team     = row["Team"].strip()
            position = _normalize_position_al(row["Pos"])

            # Traded player handling
            if name in traded_names:
                if team not in ("2TM", "3TM"):
                    continue
                team = "TOT"
            else:
                if team in ("2TM", "3TM"):
                    continue

            team = TEAM_ABBR_MAP.get(team, team)

            ab  = _int(row["AB"])
            r   = _int(row["R"])
            h   = _int(row["H"])
            dbl = _int(row["2B"])
            trp = _int(row["3B"])
            hr  = _int(row["HR"])
            rbi = _int(row["RBI"])
            bb  = _int(row["BB"])
            k   = _int(row["SO"])
            sb  = _int(row["SB"])
            cs  = _int(row["CS"])
            avg = _float(row["BA"])
            obp = _float(row["OBP"])
            slg = _float(row["SLG"])
            sng = (h - dbl - trp - hr) if all(
                v is not None for v in [h, dbl, trp, hr]
            ) else None

        except (KeyError, ValueError):
            continue

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

    logger.info(f"Parsed {len(rows)} rows from {league} batter CSV")
    return rows


# ── Step 2b: Parse pitcher CSV files ─────────────────────────────────────────

def parse_pitcher_csv(filepath: str, league: str, api_lookup: dict = None) -> list[dict]:
    """
    Parse an AL or NL pitcher CSV file (UTF-8 with BOM) and return a list of row dicts.

    Both AL and NL CSV files share the same column layout:
      Rk, Player, Age, Team, WAR, W, L, W-L%, ERA, G, GS, GF, CG, SHO, SV,
      IP, H, R, ER, HR, BB, IBB, SO, HBP, BK, WP, BF,
      ERA+, FIP, WHIP, H9, HR9, BB9, SO9, SO/BB

    Two-pass logic for traded players:
      - 1st pass: collect Player names that appear with Team 2TM or 3TM
      - 2nd pass: for traded players, keep only the 2TM/3TM aggregate row (team="TOT");
                  for single-team players, keep as-is

    Filtering rules:
      - Skip rows with empty Player field
      - Skip rows with IP < 10.0 (position players with mop-up appearances)
    """
    logger.info(f"Parsing {league} pitcher CSV: {filepath}")

    def _int(val: str):
        v = val.strip()
        return int(v) if v else None

    def _float(val: str):
        v = val.strip()
        return float(v) if v else None

    def _clean_name(raw: str) -> str:
        return raw.replace("#", "").replace("*", "").strip()

    with open(filepath, "r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        all_rows = list(reader)

    # 1st pass: collect traded player names
    traded_names = set()
    for row in all_rows:
        if not row.get("Player", "").strip():
            continue
        if row["Team"] in ("2TM", "3TM"):
            traded_names.add(_clean_name(row["Player"]))

    # 2nd pass: parse rows
    rows = []
    for row in all_rows:
        raw_player = row.get("Player", "").strip()
        if not raw_player:
            continue

        try:
            name = _clean_name(raw_player)
            team = row["Team"].strip()

            # Traded player handling
            if name in traded_names:
                if team not in ("2TM", "3TM"):
                    continue
                team = "TOT"
            else:
                if team in ("2TM", "3TM"):
                    continue

            team = TEAM_ABBR_MAP.get(team, team)

            ip = _float(row["IP"])

            # Skip non-pitchers (position players with mop-up appearances)
            if ip is None or ip < 10.0:
                continue

            # For TWP: confirm via MLB API that this player is a Two-Way Player
            if api_lookup:
                candidate = api_lookup.get(build_match_key(name, team)) \
                            or api_lookup.get(build_match_key(name))
                if candidate:
                    pos_abbr = candidate.get("primaryPosition", {}).get("abbreviation")
                    if pos_abbr not in ("P", "TWP"):
                        continue

            rows.append({
                "name":     name,
                "position": "P",
                "team":     team,

                # FVARz inputs
                "w":    _int(row["W"]),
                "sv":   _int(row["SV"]),
                "so":   _int(row["SO"]),
                "era":  _float(row["ERA"]),
                "whip": _float(row["WHIP"]),
                "ip":   ip,

                # Reference stats
                "l":        _int(row["L"]),
                "g":        _int(row["G"]),
                "gs":       _int(row["GS"]),
                "war":      _float(row["WAR"]),
                "fip":      _float(row["FIP"]),
                "h":        _int(row["H"]),
                "r":        _int(row["R"]),
                "er":       _int(row["ER"]),
                "hr":       _int(row["HR"]),
                "bb":       _float(row["BB"]),
                "hbp":      _int(row["HBP"]),
                "bf":       _int(row["BF"]),
                "era_plus": _float(row["ERA+"]),
                "h9":       _float(row["H9"]),
                "hr9":      _float(row["HR9"]),
                "bb9":      _float(row["BB9"]),
                "so9":      _float(row["SO9"]),
                "so_bb":    _float(row["SO/BB"]),
            })

        except (KeyError, ValueError):
            continue

    logger.info(f"Parsed {len(rows)} pitcher rows from {league} CSV")
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

    al_batter_rows  = parse_batter_csv(AL_BATTER_CSV_PATH, "AL", api_lookup)
    nl_batter_rows  = parse_batter_csv(NL_BATTER_CSV_PATH, "NL", api_lookup)
    al_pitcher_rows = parse_pitcher_csv(AL_PITCHER_CSV_PATH, "AL", api_lookup)
    nl_pitcher_rows = parse_pitcher_csv(NL_PITCHER_CSV_PATH, "NL", api_lookup)

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