# backend/data/parsers/player_builder.py
#
# Builds ORM constructor kwargs for batter and pitcher models.
# Centralizes field mapping so it is not duplicated across AL/NL variants.

from data.sources.mlb_api import build_match_key


# ── API identity helpers ──────────────────────────────────────────────────────

def _build_api_identity(api_player: dict) -> dict:
    """
    Extract the MLB API identity fields shared by all four player model classes.
    Used when a CSV row has been successfully matched to an API player.
    """
    return dict(
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
    )


def _build_api_identity_empty() -> dict:
    """
    Return a dict of all MLB API identity fields set to None.
    Used when a CSV row could not be matched to an API player.
    """
    return dict(
        player_id      = None,
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
    )


# ── Public builders ───────────────────────────────────────────────────────────

def build_batter_kwargs(row: dict, api_player: dict | None, team_id_to_abbr: dict, temp_id: int = None) -> dict:
    """
    Build the keyword arguments dict for ALBatter / NLBatter constructors.

    If api_player is None (unmatched), temp_id is used as player_id and all
    API identity fields are set to None.
    For traded players (row["team"] == "TOT"), team is resolved from MLB API currentTeam.
    """
    if api_player is not None:
        identity = _build_api_identity(api_player)
        team_id  = api_player.get("currentTeam", {}).get("id")
        name     = api_player.get("fullName", row["name"])
        team     = team_id_to_abbr.get(team_id, row["team"])
    else:
        identity = _build_api_identity_empty()
        identity["player_id"] = temp_id
        name = row["name"]
        team = row["team"]

    return dict(
        name     = name,
        position = row["position"],
        team     = team,
        **identity,

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


def build_pitcher_kwargs(row: dict, api_player: dict | None, team_id_to_abbr: dict, temp_id: int = None) -> dict:
    """
    Build the keyword arguments dict for ALPitcher / NLPitcher constructors.

    If api_player is None (unmatched), temp_id is used as player_id and all
    API identity fields are set to None.
    For traded players (row["team"] == "TOT"), team is resolved from MLB API currentTeam.
    """
    if api_player is not None:
        identity = _build_api_identity(api_player)
        team_id  = api_player.get("currentTeam", {}).get("id")
        name     = api_player.get("fullName", row["name"])
        team     = team_id_to_abbr.get(team_id, row["team"])
    else:
        identity = _build_api_identity_empty()
        identity["player_id"] = temp_id
        name = row["name"]
        team = row["team"]

    return dict(
        name     = name,
        position = row["position"],
        team     = team,
        **identity,

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