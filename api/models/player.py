from pydantic import BaseModel

# Request: data from client
class PlayerRequest(BaseModel):
    player_name: str

# Response: response to client
class PlayerResponse(BaseModel):
    player_name: str
    recommended_bid: int
    player_value: int