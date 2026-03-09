from pydantic import BaseModel


# ── Stat Models ─────────────────────────────────────────────────────────────

class BatterStats(BaseModel):
    AB:  int
    R:   int
    HR:  int
    RBI: int
    SB:  int
    CS:  int
    AVG: float


class PitcherStats(BaseModel):
    IP:   float
    W:    int
    SV:   int
    K:    int
    ERA:  float
    WHIP: float


# ── Context Models ───────────────────────────────────────────────────────────

class LeagueContext(BaseModel):
    league_size:  int
    roster_size:  int
    total_budget: int


class DraftContext(BaseModel):
    my_remaining_budget:       int
    my_remaining_roster_spots: int
    my_positions_filled:       list[str]
    drafted_players_count:     int


# ── Request Models ───────────────────────────────────────────────────────────

class PlayerValueRequest(BaseModel):
    player_name:    str
    player_type:    str                       # "batter" or "pitcher"
    position:       str                       # e.g. "OF", "SP", "C"
    stats:          BatterStats | PitcherStats
    league_context: LeagueContext


class PlayerBidRequest(BaseModel):
    player_name:    str
    player_type:    str
    position:       str
    stats:          BatterStats | PitcherStats
    league_context: LeagueContext
    draft_context:  DraftContext


# ── Breakdown Models (for response detail) ───────────────────────────────────

class ValueBreakdown(BaseModel):
    stat_score:      float    # normalized z-score contribution (0~100)
    position_bonus:  float    # positional scarcity bonus applied (0~100)
    risk_penalty:    float    # risk deduction applied (0~100)


class BidBreakdown(BaseModel):
    base_price:          float    # initial price from player_value
    scarcity_adjustment: float    # dollar adjustment from positional scarcity
    draft_adjustment:    float    # dollar adjustment from draft state
    max_spendable:       int      # maximum the user can spend right now


# ── Response Models ──────────────────────────────────────────────────────────

class PlayerValueResponse(BaseModel):
    player_name:     str
    player_type:     str
    player_value:    float           # 0.0 ~ 100.0
    value_breakdown: ValueBreakdown


class PlayerBidResponse(BaseModel):
    player_name:     str
    player_type:     str
    player_value:    float           # 0.0 ~ 100.0
    recommended_bid: int             # integer dollar amount
    bid_breakdown:   BidBreakdown