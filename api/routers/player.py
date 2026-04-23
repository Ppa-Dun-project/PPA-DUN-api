from fastapi import APIRouter
from pydantic import BaseModel
from api.models.player import (
    PlayerValueRequest,
    PlayerValueResponse,
    PlayerBidRequest,
    PlayerBidResponse,
)
from api.services.player import compute_player_value, compute_recommended_bid

router = APIRouter()


@router.post("/player/value", response_model=PlayerValueResponse)
def player_value(request: PlayerValueRequest):
    """
    POST /player/value

    Accepts player stats and league context, returns player_value (0.0 ~ 100.0).
    Requires a valid X-API-Key header (enforced by the middleware in main.py).

    Request body  : PlayerValueRequest  (defined in api/models/player.py)
    Response body : PlayerValueResponse (defined in api/models/player.py)
    Business logic: compute_player_value() in api/services/player.py
    """
    return compute_player_value(request)


@router.post("/player/bid", response_model=PlayerBidResponse)
def player_bid(request: PlayerBidRequest):
    """
    POST /player/bid

    Accepts player stats, league context, and draft context.
    Returns both player_value (0.0 ~ 100.0) and recommended_bid (integer $).
    Requires a valid X-API-Key header (enforced by the middleware in main.py).

    Request body  : PlayerBidRequest  (PlayerValueRequest + league_context + draft_context)
    Response body : PlayerBidResponse (defined in api/models/player.py)
    Business logic: compute_recommended_bid() in api/services/player.py

    DraftContext fields:
      my_remaining_budget       : required — client's current remaining budget
      my_remaining_roster_spots : required — used as fallback when my_roster is None
      drafted_players_count     : required — total players drafted across all teams
      my_roster                 : optional — list of {player_name, position};
                                  when provided, my_remaining_roster_spots is
                                  derived as roster_size - len(my_roster)
      opponent_rosters          : optional — used for dynamic scarcity bonus (ALG-03)
      opponent_budgets          : optional — used for competitor budget cap (ALG-04)
    """
    return compute_recommended_bid(request)


# ── Stub: player_value recalculation ─────────────────────────────────────────
# Temporary endpoint used by daily_update.py to recalculate player_value
# for all players after injury / depth chart data is refreshed.
#
# This stub encodes player state into a 5-digit integer:
#   Digits 1-3 : AB (zero-padded to 3 digits, capped at 999)
#   Digit  4   : injury status label (0-9, see INJURY_LABEL below)
#   Digit  5   : depth_order (capped at 9; 0 if not on depth chart)
#
# This encoding will be replaced by the real FVARz algorithm once finalized.
# Auth is NOT required — this endpoint is called internally by the backend,
# not exposed to external API consumers. It is exempt via the middleware
# INTERNAL_PATHS list in api/main.py.

INJURY_LABEL = {
    None:           0,
    "Day-To-Day":   1,
    "10-Day IL":    2,
    "15-Day IL":    3,
    "60-Day IL":    4,
    "Out":          5,
    "7-Day IL":     6,
    "Suspension":   7,
    "Bereavement":  8,
    "Paternity":    9,
}


class RecalculateRequest(BaseModel):
    player_id:     int
    player_type:   str            # "batter" or "pitcher"
    ab:            int | None     # At Bats (batters only; None for pitchers)
    injury_status: str | None     # Raw ESPN status string, or None if healthy
    depth_order:   int | None     # 1 = starter; None if not on depth chart


class RecalculateResponse(BaseModel):
    player_id:    int
    player_value: int             # 5-digit encoded integer (stub)


@router.post("/player/recalculate", response_model=RecalculateResponse)
def player_recalculate(request: RecalculateRequest):
    """
    POST /player/recalculate  [STUB — internal use only]

    Encodes player state as a 5-digit integer player_value.
    Called by daily_update.py after injury / depth chart refresh.
    Will be replaced by the real FVARz algorithm once finalized.

    Encoding:
      player_value = AB(3 digits) + injury_label(1 digit) + depth_order(1 digit)

    Examples:
      AB=534, injury=None,        depth=2  →  53402
      AB=120, injury=Day-To-Day,  depth=1  →  12011
      AB=89,  injury=15-Day IL,   depth=3  →  08933
    """
    ab          = min(request.ab or 0, 999)
    inj_label   = INJURY_LABEL.get(request.injury_status, 0)
    depth_digit = min(request.depth_order or 0, 9)

    player_value = int(f"{ab:03d}{inj_label}{depth_digit}")

    return RecalculateResponse(
        player_id=request.player_id,
        player_value=player_value,
    )