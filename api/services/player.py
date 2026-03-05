from api.models.player import PlayerResponse

def evaluate_player(player_name: str) -> PlayerResponse:
    return PlayerResponse(
        player_name=player_name,
        recommended_bid=777, # Placeholder values for demonstration
        player_value=100 # Placeholder values for demonstration
    )