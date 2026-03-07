from pydantic import BaseModel

class PlayerValueResponse(BaseModel):
    player_name: str
    player_value: int

class OpponentState(BaseModel):
    positions_filled: list[str]

class PlayerBidRequest(BaseModel):
    my_budget_remaining: int
    my_roster_filled: list[str]
    my_roster_empty: list[str]
    opponents: list[OpponentState]

class PlayerBidResponse(BaseModel):
    player_name: str
    recommended_bid: int