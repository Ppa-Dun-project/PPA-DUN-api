# backend/data/parsers/csv_parser.py
#
# Parses Baseball Reference AL/NL batter and pitcher CSV files.
# Returns normalized row dicts consumed by init_players.py insert_league().

import csv
import logging

from data.sources.mlb_api import build_match_key

logger = logging.getLogger(__name__)

# ── Constants ─────────────────────────────────────────────────────────────────

# SQL dump team abbreviations that differ from MLB API abbreviations.
TEAM_ABBR_MAP = {
    "CHW": "CWS",
    "KCR": "KC",
    "TBR": "TB",
    "ARI": "AZ",
    "WAS": "WSH",
}

# Baseball Reference numeric position codes mapped to standard abbreviations.
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

def _int(val: str):
    v = val.strip()
    return int(v) if v else None


def _float(val: str):
    v = val.strip()
    return float(v) if v else None


def _clean_name(raw: str) -> str:
    """Strip Baseball Reference handedness markers (* and #) from player names."""
    return raw.replace("#", "").replace("*", "").strip()


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


def _collect_traded_names(all_rows: list[dict]) -> set:
    """
    First pass: return the set of player names that appear with team 2TM or 3TM.
    These players were traded mid-season and have a separate aggregate row.
    """
    traded = set()
    for row in all_rows:
        if not row.get("Player", "").strip():
            continue
        if row["Team"] in ("2TM", "3TM"):
            traded.add(_clean_name(row["Player"]))
    return traded


def _resolve_team(name: str, team: str, traded_names: set) -> str | None:
    """
    Apply traded player logic and return the resolved team abbreviation.
    Returns None if the row should be skipped.

    Rules:
      - Traded player (name in traded_names): keep only the 2TM/3TM aggregate
        row and normalize team to "TOT"; skip all per-team rows.
      - Non-traded player: skip if team is 2TM/3TM (shouldn't happen, but guard).
    """
    if name in traded_names:
        if team not in ("2TM", "3TM"):
            return None
        return "TOT"
    else:
        if team in ("2TM", "3TM"):
            return None
        return team


# ── Public parsers ────────────────────────────────────────────────────────────

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

    with open(filepath, "r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        all_rows = list(reader)

    traded_names = _collect_traded_names(all_rows)

    rows = []
    for row in all_rows:
        raw_player = row.get("Player", "").strip()
        if not raw_player:
            continue

        try:
            name = _clean_name(raw_player)
            team = _resolve_team(name, row["Team"].strip(), traded_names)
            if team is None:
                continue

            team     = TEAM_ABBR_MAP.get(team, team)
            position = _normalize_position_al(row["Pos"])

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

    with open(filepath, "r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        all_rows = list(reader)

    traded_names = _collect_traded_names(all_rows)

    rows = []
    for row in all_rows:
        raw_player = row.get("Player", "").strip()
        if not raw_player:
            continue

        try:
            name = _clean_name(raw_player)
            team = _resolve_team(name, row["Team"].strip(), traded_names)
            if team is None:
                continue

            team = TEAM_ABBR_MAP.get(team, team)
            ip   = _float(row["IP"])

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