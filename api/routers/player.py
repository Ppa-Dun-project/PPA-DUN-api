from fastapi import APIRouter
from api.models.player import PlayerValueResponse, PlayerBidRequest, PlayerBidResponse
from api.services.player import get_player_value, get_recommended_bid

router = APIRouter()

@router.get("/player/{player_name}/value", response_model=PlayerValueResponse)
def player_value(player_name: str):
    return get_player_value(player_name)

@router.post("/player/{player_name}/bid", response_model=PlayerBidResponse)
def player_bid(player_name: str, request: PlayerBidRequest):
    return get_recommended_bid(player_name, request)