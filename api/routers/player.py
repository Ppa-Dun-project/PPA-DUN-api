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

    Request body  : PlayerBidRequest  (PlayerValueRequest + draft_context)
    Response body : PlayerBidResponse (defined in api/models/player.py)
    Business logic: compute_recommended_bid() in api/services/player.py
    """
    return compute_recommended_bid(request)