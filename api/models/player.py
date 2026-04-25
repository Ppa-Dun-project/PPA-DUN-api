from __future__ import annotations
from typing import Annotated, Literal
from pydantic import BaseModel, Field


# ── Stat Models ───────────────────────────────────────────────────────────────
# player_type is embedded as a Literal field in each stat model so that
# Pydantic can use it as a discriminator when parsing the request body.
# This ensures the correct model is selected based on the player_type value
# rather than relying on field overlap heuristics.

class BatterStats(BaseModel):
    player_type: Literal["batter"] = "batter"

    # Core stats (required) — used for z-score calculation
    AB:  int
    R:   int
    HR:  int
    RBI: int
    SB:  int
    CS:  int
    AVG: float

    # Optional: 3-year average stats for blending (STEP A)
    # If omitted, stats_current (above) is used as-is.
    # Each field mirrors a core stat; all must be provided together or all omitted.
    AB_3yr:  int   | None = None
    R_3yr:   int   | None = None
    HR_3yr:  int   | None = None
    RBI_3yr: int   | None = None
    SB_3yr:  int   | None = None
    CS_3yr:  int   | None = None
    AVG_3yr: float | None = None

    # Optional: player age for age adjustment (STEP B)
    # If omitted, age_factor = 1.00 (no adjustment).
    age: int | None = None

    # Optional: depth chart order for playing time adjustment (STEP C)
    # 1 = starter, 2 = backup, etc. If omitted, depth_factor = 1.00.
    depth_order: int | None = None

    # Optional: injury status for risk penalty (ALG-03)
    # Canonical ESPN status string. If omitted, no injury penalty is applied.
    injury_status: str | None = None


class PitcherStats(BaseModel):
    player_type: Literal["pitcher"] = "pitcher"

    # Core stats (required) — used for z-score calculation
    IP:   float
    W:    int
    SV:   int
    K:    int
    ERA:  float
    WHIP: float

    # Optional: 3-year average stats for blending (STEP A)
    IP_3yr:   float | None = None
    W_3yr:    int   | None = None
    SV_3yr:   int   | None = None
    K_3yr:    int   | None = None
    ERA_3yr:  float | None = None
    WHIP_3yr: float | None = None

    # Optional: player age for age adjustment (STEP B)
    age: int | None = None

    # Optional: depth chart order (STEP C)
    depth_order: int | None = None

    # Optional: injury status for risk penalty (ALG-03)
    injury_status: str | None = None


# ── Context Models ────────────────────────────────────────────────────────────

class LeagueContext(BaseModel):
    league_size:  int
    roster_size:  int
    total_budget: int


class RosterEntry(BaseModel):
    player_name: str
    position:    str   # e.g. "C", "SS", "OF"


class DraftContext(BaseModel):
    my_remaining_budget:       int
    my_remaining_roster_spots: int
    drafted_players_count:     int

    # Optional: full roster state for dynamic scarcity bonus (ALG-03)
    # If omitted, _get_dynamic_scarcity_bonus() falls back to static POSITION_BONUS.
    my_roster:         list[RosterEntry]        | None = None
    opponent_rosters:  dict[str, list[RosterEntry]] | None = None

    # Optional: remaining budget per opponent for bid cap (ALG-04)
    # Key = opponent team name (must match keys in opponent_rosters if provided)
    opponent_budgets: dict[str, int] | None = None


# ── Request Models ────────────────────────────────────────────────────────────
# stats field uses a discriminated union on player_type.
# Pydantic reads the player_type value from the incoming JSON and selects
# the matching model (BatterStats or PitcherStats) automatically.
# This prevents mismatched stats fields from passing validation silently.

PlayerStats = Annotated[
    BatterStats | PitcherStats,
    Field(discriminator="player_type"),
]


class PlayerValueRequest(BaseModel):
    player_name: str
    position:    str       # e.g. "OF", "SP", "C"
    stats:       PlayerStats


class PlayerBidRequest(BaseModel):
    player_name:   str
    position:      str
    stats:         PlayerStats
    league_context: LeagueContext
    draft_context:  DraftContext


# ── Breakdown Models (for response detail) ────────────────────────────────────

class ValueBreakdown(BaseModel):
    stat_score:      float    # normalized z-score contribution (0~100)
    position_bonus:  float    # positional scarcity bonus applied (0~100)
    risk_penalty:    float    # risk deduction applied (0~100)


class BidBreakdown(BaseModel):
    base_price:          float    # initial price from player_value
    scarcity_adjustment: float    # dollar adjustment from positional scarcity
    draft_adjustment:    float    # dollar adjustment from draft state
    max_spendable:       int      # maximum the user can spend right now
    max_competitor_budget:  int     # max budget among competing opponents; equals max_spendable if opponent_budgets not provided


# ── Response Models ───────────────────────────────────────────────────────────

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


# ── player_name Based Bid Models ──────────────────────────────────────────────

class PlayerBidByNameRequest(BaseModel):
    player_id:      int            # MLB stable integer player ID (replaces player_name)
    league_context: LeagueContext
    draft_context:  DraftContext


class BatterStatsSnapshot(BaseModel):
    """Batter stat fields returned in PlayerBidByNameResponse."""
    ab:  int   | None
    r:   int   | None
    hr:  int   | None
    rbi: int   | None
    sb:  int   | None
    cs:  int   | None
    avg: float | None


class PitcherStatsSnapshot(BaseModel):
    """Pitcher stat fields returned in PlayerBidByNameResponse."""
    ip:   float | None
    w:    int   | None
    sv:   int   | None
    k:    int   | None
    era:  float | None
    whip: float | None


class PlayerBidByNameResponse(BaseModel):
    player_name:    str
    player_type:    str             # "batter" or "pitcher"
    position:       str
    team:           str
    stats:          BatterStatsSnapshot | PitcherStatsSnapshot
    injury_status:  str  | None
    depth_order:    int  | None
    player_value:   float           # stored value from DB
    recommended_bid: int
    bid_breakdown:  BidBreakdown