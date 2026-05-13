from fastapi import APIRouter
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

    Accepts player stats and returns player_value (0.0 ~ 100.0).
    Requires a valid X-API-Key header (enforced by the middleware in main.py).

    Request body  : PlayerValueRequest (defined in api/models/player.py)
    Response body : PlayerValueResponse (defined in api/models/player.py)
    Business logic: compute_player_value() in api/services/player.py

    PlayerValueRequest fields:
      player_name : required — player's full name
      position    : required — e.g. "OF", "SP", "C"
      stats       : required — BatterStats or PitcherStats (discriminated by player_type)
                    includes optional 3yr avg fields, age, depth_order, injury_status
    """
    return compute_player_value(request)


@router.post("/player/bid", response_model=PlayerBidResponse)
def player_bid(request: PlayerBidRequest):
    """
    POST /player/bid

    Accepts player stats, league context, and draft context.
    Returns both player_value (0.0 ~ 100.0) and recommended_bid (integer $).
    Requires a valid X-API-Key header (enforced by the middleware in main.py).

    Request body  : PlayerBidRequest (defined in api/models/player.py)
    Response body : PlayerBidResponse (defined in api/models/player.py)
    Business logic: compute_recommended_bid() in api/services/player.py

    PlayerBidRequest fields:
      player_name    : required — player's full name
      position       : required — e.g. "OF", "SP", "C"
      stats          : required — BatterStats or PitcherStats
      league_context : required — league_size, roster_size, total_budget
      draft_context  : required — see below

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