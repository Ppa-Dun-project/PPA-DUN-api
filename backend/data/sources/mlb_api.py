# backend/data/sources/mlb_api.py
#
# MLB Stats API client.
# Fetches player rosters and team metadata for the 2025 season.

import logging
import requests

from data.utils import normalize_name

logger = logging.getLogger(__name__)

# ── Constants ─────────────────────────────────────────────────────────────────

# MLB API sport IDs to fetch players from.
# 1=MLB, 11=AAA, 12=AA, 13=High-A, 14=Single-A, 16=Dominican Summer League
SPORT_IDS = [1, 11, 12, 13, 14, 16]
TEAMS_API_URL = "https://statsapi.mlb.com/api/v1/teams?sportId=1&season=2025"


# ── Helpers ───────────────────────────────────────────────────────────────────

def build_match_key(name: str, team: str = "") -> tuple:
    """
    Build a (normalized_name, team_abbr) tuple for matching.
    team is uppercased and used as a secondary key to resolve same-name collisions.
    """
    return (normalize_name(name), team.upper())


# ── Public API ────────────────────────────────────────────────────────────────

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