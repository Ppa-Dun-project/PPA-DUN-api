from fastapi import APIRouter
from api.models.player import PlayerRequest, PlayerResponse
from api.services.player import evaluate_player

router = APIRouter()

@router.post("/player", response_model=PlayerResponse)
def get_player_value(request: PlayerRequest):
    return evaluate_player(request.player_name)