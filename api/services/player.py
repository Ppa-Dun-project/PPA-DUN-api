from api.models.player import (
    PlayerValueRequest,
    PlayerBidRequest,
    PlayerValueResponse,
    PlayerBidResponse,
    ValueBreakdown,
    BidBreakdown,
    BatterStats,
    PitcherStats,
)

import logging
import threading

logger = logging.getLogger(__name__)

# ── Fallback Baseline Constants ───────────────────────────────────────────────
# Used only when the in-memory cache has not yet been populated by a push
# from the backend server (i.e., before the first daily_update run).
# Do NOT use these directly in algorithm logic — always call get_baselines().

_BATTER_BASELINES_FALLBACK = {
    "R":   {"mean": 75.0,  "std": 20.0},
    "HR":  {"mean": 18.0,  "std": 10.0},
    "RBI": {"mean": 72.0,  "std": 20.0},
    "SB":  {"mean": 12.0,  "std": 10.0},
    "AVG": {"mean": 0.260, "std": 0.025},
}

_PITCHER_BASELINES_FALLBACK = {
    "W":    {"mean": 10.0,  "std": 4.0},
    "SV":   {"mean": 10.0,  "std": 14.0},
    "K":    {"mean": 130.0, "std": 50.0},
    "ERA":  {"mean": 4.00,  "std": 0.70},
    "WHIP": {"mean": 1.25,  "std": 0.15},
}

# ── In-memory baseline cache ──────────────────────────────────────────────────
# Populated by POST /internal/reload-baselines (called from daily_update.py).
# _baseline_lock ensures thread-safe writes since FastAPI may handle
# concurrent requests across multiple threads.

_baseline_lock  = threading.Lock()
_batter_baselines:  dict = {}   # empty = not yet loaded; fallback will be used
_pitcher_baselines: dict = {}


def reload_baselines(batter: dict, pitcher: dict) -> None:
    """
    Replace the in-memory baseline cache with newly computed values.
    Called by POST /internal/reload-baselines in api/main.py.
    Thread-safe via _baseline_lock.
    """
    global _batter_baselines, _pitcher_baselines
    with _baseline_lock:
        _batter_baselines  = batter
        _pitcher_baselines = pitcher
    logger.info("[baselines] cache updated")


def get_baselines(player_type: str) -> dict:
    """
    Return the current baseline dict for the given player_type.
    Falls back to hardcoded constants if the cache is empty,
    and logs a warning so the condition is visible in server logs.
    """
    with _baseline_lock:
        if player_type == "batter":
            if _batter_baselines:
                return _batter_baselines
            logger.warning("[baselines] batter cache empty — using fallback constants")
            return _BATTER_BASELINES_FALLBACK
        else:
            if _pitcher_baselines:
                return _pitcher_baselines
            logger.warning("[baselines] pitcher cache empty — using fallback constants")
            return _PITCHER_BASELINES_FALLBACK

# ── Normalization Ceilings ────────────────────────────────────────────────────
# Z_MAX_* = approximate z_total of an all-time elite player in a single season.
# RAW_MAX  = Z_MAX + maximum possible position_bonus (C = +1.5 → 11.5,
#            rounded up to 12.0 for headroom).
# Values above the ceiling are clipped to 100.0.

Z_MAX_BATTER  = 10.0
Z_MAX_PITCHER = 10.0
RAW_MAX       = 12.0

# ── Hitter / Pitcher Budget Split ─────────────────────────────────────────────
# Standard Roto 5x5 auction convention: ~67% of budget goes to batters,
# ~33% to pitchers. Used in base_price calculation.

HIT_PITCH_RATIO = {
    "batter":  0.67,
    "pitcher": 0.33,
}

# ── Positional Scarcity Bonus ─────────────────────────────────────────────────
# Added to z_total (in z-score units) before normalization.
# Reflects the fact that scarce positions (C, SS) carry extra value
# even when raw stats are equal to a less scarce position (1B, OF).

POSITION_BONUS = {
    "C":  1.5,
    "SS": 0.8,
    "RP": 0.6,
    "CL": 0.6,
    "SP": 0.4,
    "2B": 0.5,
    "3B": 0.3,
    "1B": 0.0,
    "OF": 0.0,
    "DH": 0.0,
}

# ── Total Eligible Players per Position ───────────────────────────────────────
# Approximate number of fantasy-relevant players per position across the league.
# Used as the denominator in dynamic scarcity bonus calculation.
# Source: standard 12-team Roto 5x5 player pool estimates.

TOTAL_ELIGIBLE = {
    "C":  30,
    "1B": 40,
    "2B": 35,
    "3B": 35,
    "SS": 30,
    "OF": 90,
    "DH": 20,
    "SP": 80,
    "RP": 50,
    "CL": 20,
}

# ── Positional Scarcity Multiplier ────────────────────────────────────────────
# Applied to base_price (in dollars) during bid calculation.
# Separate from POSITION_BONUS — this multiplier directly inflates the dollar
# bid to reflect real auction market behavior.

SCARCITY_MULTIPLIER = {
    "C":  1.15,
    "SS": 1.08,
    "2B": 1.05,
    "SP": 1.05,
    "RP": 1.05,
    "CL": 1.05,
    "3B": 1.02,
    "1B": 1.00,
    "OF": 1.00,
    "DH": 1.00,
}

# ── Age Factor Table ──────────────────────────────────────────────────────────
# Applied to blended_stat before z-score calculation (STEP B).
# Reflects career trajectory: young players have upside, older players decline.

AGE_FACTOR_TABLE = [
    (25, 1.05),   # 25 and under: growth potential
    (30, 1.00),   # 26~30: prime years
    (33, 0.95),   # 31~33: early decline
]
AGE_FACTOR_DEFAULT = 0.90   # 34 and older: decline phase
AGE_FACTOR_UNKNOWN = 1.00   # age not provided: no adjustment

# ── Depth Factor Table ────────────────────────────────────────────────────────
# Applied to blended_stat before z-score calculation (STEP C).
# Reflects expected playing time based on depth chart position.

DEPTH_FACTOR_TABLE = {
    1: 1.00,   # starter: full playing time expected
    2: 0.90,   # near-starter: semi-regular
    3: 0.75,   # platoon candidate
}
DEPTH_FACTOR_DEFAULT = 0.60   # 4 or deeper: limited role
DEPTH_FACTOR_UNKNOWN = 1.00   # depth_order not provided: no adjustment

# ── Injury Penalty Table ──────────────────────────────────────────────────────
# Subtracted from z_total as part of risk penalty (STEP G / ALG-03).
# Uses canonical ESPN status strings stored in the DB.

INJURY_PENALTY = {
    "Day-To-Day": 0.1,
    "10-Day IL":  0.3,
    "15-Day IL":  0.4,
    "60-Day IL":  0.7,
    "Out":        1.0,
}


# ── Internal Helpers ──────────────────────────────────────────────────────────

def _zscore(value: float, mean: float, std: float) -> float:
    """
    Compute the z-score of a single statistic.
    Returns 0.0 if std is 0 to prevent ZeroDivisionError.
    Formula: z = (value - mean) / std
    """
    if std == 0:
        return 0.0
    return (value - mean) / std


def _normalize(value: float, max_val: float) -> float:
    """
    Scale a raw value to the [0.0, 100.0] range and clip to boundary.
    Formula: scaled = clip((value / max_val) * 100, 0, 100)
    """
    if max_val == 0:
        return 0.0
    return max(0.0, min(100.0, (value / max_val) * 100.0))


def _get_age_factor(age: int | None) -> float:
    """
    Return the age adjustment factor for blended_stat (STEP B).
    Iterates the AGE_FACTOR_TABLE in ascending order and returns the factor
    for the first threshold the player's age does not exceed.
    Falls back to AGE_FACTOR_DEFAULT (0.90) for players 34 and older.
    Returns AGE_FACTOR_UNKNOWN (1.00) when age is not provided.
    """
    if age is None:
        return AGE_FACTOR_UNKNOWN
    for max_age, factor in AGE_FACTOR_TABLE:
        if age <= max_age:
            return factor
    return AGE_FACTOR_DEFAULT


def _get_depth_factor(depth_order: int | None) -> float:
    """
    Return the depth chart adjustment factor for blended_stat (STEP C).
    Returns DEPTH_FACTOR_UNKNOWN (1.00) when depth_order is not provided.
    Returns DEPTH_FACTOR_DEFAULT (0.60) for depth_order >= 4.
    """
    if depth_order is None:
        return DEPTH_FACTOR_UNKNOWN
    return DEPTH_FACTOR_TABLE.get(depth_order, DEPTH_FACTOR_DEFAULT)


# ── STEP A: Stat Blending ─────────────────────────────────────────────────────

def _blend_stats(stats: BatterStats | PitcherStats) -> dict[str, float]:
    """
    Blend stats_current and stats_3yr_avg at a 6:4 ratio (STEP A).
    Returns a dict mapping stat name → blended value.

    If any 3-year average field is None (i.e. not provided), the current
    season stat is used as-is for that field. This allows partial 3yr data
    to be provided without breaking the pipeline.

    Formula: blended = (0.6 * current) + (0.4 * avg_3yr)
    """
    if isinstance(stats, BatterStats):
        return {
            "R":   0.6 * stats.R   + 0.4 * (stats.R_3yr   if stats.R_3yr   is not None else stats.R),
            "HR":  0.6 * stats.HR  + 0.4 * (stats.HR_3yr  if stats.HR_3yr  is not None else stats.HR),
            "RBI": 0.6 * stats.RBI + 0.4 * (stats.RBI_3yr if stats.RBI_3yr is not None else stats.RBI),
            "SB":  0.6 * stats.SB  + 0.4 * (stats.SB_3yr  if stats.SB_3yr  is not None else stats.SB),
            "AVG": 0.6 * stats.AVG + 0.4 * (stats.AVG_3yr if stats.AVG_3yr is not None else stats.AVG),
            # AB and CS are used in risk penalty, not z-score; pass through current values
            "AB":  float(stats.AB),
            "CS":  float(stats.CS),
        }
    else:  # PitcherStats
        return {
            "W":    0.6 * stats.W    + 0.4 * (stats.W_3yr    if stats.W_3yr    is not None else stats.W),
            "SV":   0.6 * stats.SV   + 0.4 * (stats.SV_3yr   if stats.SV_3yr   is not None else stats.SV),
            "K":    0.6 * stats.K    + 0.4 * (stats.K_3yr     if stats.K_3yr    is not None else stats.K),
            "ERA":  0.6 * stats.ERA  + 0.4 * (stats.ERA_3yr  if stats.ERA_3yr  is not None else stats.ERA),
            "WHIP": 0.6 * stats.WHIP + 0.4 * (stats.WHIP_3yr if stats.WHIP_3yr is not None else stats.WHIP),
            # IP is used in risk penalty, not z-score; pass through current value
            "IP":   stats.IP,
        }


# ── STEP B + C: Age and Depth Adjustment ─────────────────────────────────────

def _apply_adjustments(
    blended: dict[str, float],
    age: int | None,
    depth_order: int | None,
    player_type: str,
) -> dict[str, float]:
    age_factor   = _get_age_factor(age)
    depth_factor = _get_depth_factor(depth_order)

    # Rate stats are excluded from depth_factor — multiplying AVG/ERA/WHIP
    # by a playing-time proxy produces nonsensical results.
    # Age factor still applies to rate stats (reflects skill trajectory).
    DEPTH_EXCLUDE = {"AVG", "ERA", "WHIP"}
    # Always exclude from both adjustments (used only for risk penalty)
    BOTH_EXCLUDE  = {"AB", "CS", "IP"}

    result = {}
    for k, v in blended.items():
        if k in BOTH_EXCLUDE:
            result[k] = v
        elif k in DEPTH_EXCLUDE:
            result[k] = v * age_factor        # age only, no depth
        else:
            result[k] = v * age_factor * depth_factor   # both
    return result


# ── STEP E: Z-Score Calculation ───────────────────────────────────────────────

def _compute_z_scores(blended: dict[str, float], player_type: str) -> float:
    """
    Sum z-scores across all 5 Roto categories using the blended stat dict.

    Batters:  R + HR + RBI + SB + AVG  (all higher = better)
    Pitchers: W + SV + K - ERA - WHIP  (ERA and WHIP negated: lower = better)

    Returns z_total.
    """
    if player_type == "batter":
        b = get_baselines("batter")
        return (
            _zscore(blended["R"],   b["R"]["mean"],   b["R"]["std"])
            + _zscore(blended["HR"],  b["HR"]["mean"],  b["HR"]["std"])
            + _zscore(blended["RBI"], b["RBI"]["mean"], b["RBI"]["std"])
            + _zscore(blended["SB"],  b["SB"]["mean"],  b["SB"]["std"])
            + _zscore(blended["AVG"], b["AVG"]["mean"], b["AVG"]["std"])
        )
    else:
        p = get_baselines("pitcher")
        return (
            _zscore(blended["W"],    p["W"]["mean"],    p["W"]["std"])
            + _zscore(blended["SV"],   p["SV"]["mean"],   p["SV"]["std"])
            + _zscore(blended["K"],    p["K"]["mean"],    p["K"]["std"])
            - _zscore(blended["ERA"],  p["ERA"]["mean"],  p["ERA"]["std"])
            - _zscore(blended["WHIP"], p["WHIP"]["mean"], p["WHIP"]["std"])
        )


# ── STEP F: Positional Scarcity Bonus ────────────────────────────────────────

def _get_dynamic_scarcity_bonus(
    position: str,
    opponent_rosters: dict[str, list] | None,
) -> tuple[float, int]:
    """
    Compute the positional scarcity bonus (in z-score units) and the number
    of competitors who have already drafted the given position.

    When opponent_rosters is provided:
      1. Count total_drafted_at_pos across all opponent rosters.
      2. Compute remaining_ratio = (total_eligible - total_drafted_at_pos)
                                   / total_eligible
      3. dynamic_bonus = base_bonus / remaining_ratio
         capped at base_bonus * 2 to prevent runaway values.

    When opponent_rosters is not provided:
      Falls back to static POSITION_BONUS constant.

    Returns:
      (bonus, competitors_at_pos)
      bonus             — scarcity bonus in z-score units
      competitors_at_pos — number of opponents who already have this position
                           (0 triggers early-exit in compute_recommended_bid)
    """
    pos        = position.upper()
    base_bonus = POSITION_BONUS.get(pos, 0.0)

    # Fallback: no roster data provided
    if opponent_rosters is None:
        return base_bonus, -1   # -1 signals "no data" — early-exit will not trigger

    # Count how many opponents have already drafted this position
    competitors_at_pos = sum(
        1
        for roster in opponent_rosters.values()
        for entry in roster
        if entry.position.upper() == pos
    )

    # Early-exit signal: no competitors need this position
    # (caller checks this and returns recommended_bid = 1)
    if competitors_at_pos == 0:
        return base_bonus, 0

    # Dynamic bonus calculation
    total_eligible     = TOTAL_ELIGIBLE.get(pos, 40)
    total_drafted      = competitors_at_pos
    remaining          = max(total_eligible - total_drafted, 1)  # floor at 1 to avoid division by zero
    remaining_ratio    = remaining / total_eligible
    raw_bonus          = base_bonus / remaining_ratio if remaining_ratio > 0 else base_bonus
    dynamic_bonus      = min(raw_bonus, base_bonus * 2)          # cap at 2x base

    return dynamic_bonus, competitors_at_pos


# ── STEP G: Risk Penalty ──────────────────────────────────────────────────────

def _get_risk_penalty(stats: BatterStats | PitcherStats, blended: dict[str, float]) -> float:
    """
    Compute the total risk penalty (in z-score units).
    All conditions are evaluated independently and summed.

    Batter conditions:
      - AB < 300              : insufficient playing time            → -0.5
      - CS/(SB+CS) > 0.35    : poor stolen base efficiency          → -0.2

    Pitcher conditions:
      - IP < 100              : insufficient innings                 → -0.5
      - ERA > 4.50            : ERA above roto-relevant threshold    → -0.3

    Injury conditions (all player types):
      - Day-To-Day            : short-term absence                   → -0.1
      - 10-Day IL             : short-term IL                        → -0.3
      - 15-Day IL             : mid-term IL                          → -0.4
      - 60-Day IL             : long-term IL                         → -0.7
      - Out                   : season-ending                        → -1.0

    AB, CS, IP values are taken from blended dict (pass-through, not adjusted).
    ERA is taken from blended dict (adjusted).
    """
    penalty = 0.0

    if isinstance(stats, BatterStats):
        if blended["AB"] < 300:
            penalty += 0.5
        total_attempts = blended["SB"] + blended["CS"] if "SB" in blended else stats.SB + stats.CS
        cs  = blended.get("CS", stats.CS)
        sb  = blended.get("SB", stats.SB)
        tot = sb + cs
        if tot > 0 and (cs / tot) > 0.35:
            penalty += 0.2
    else:
        if blended["IP"] < 100:
            penalty += 0.5
        if blended["ERA"] > 4.50:
            penalty += 0.3

    # Injury penalty (applicable to all player types)
    injury_status = stats.injury_status
    if injury_status and injury_status in INJURY_PENALTY:
        penalty += INJURY_PENALTY[injury_status]

    return penalty


# ── Core Function 1: player_value ─────────────────────────────────────────────

def compute_player_value(request: PlayerValueRequest) -> PlayerValueResponse:
    """
    Compute player_value (0.0 ~ 100.0) using the Roto 5x5 FVARz algorithm.

    Full pipeline:
      STEP A — Blend stats_current and stats_3yr_avg (6:4 ratio)
      STEP B — Apply age_factor to blended stats
      STEP C — Apply depth_factor to blended stats
      STEP E — Compute z_total from adjusted blended stats
      STEP F — Add positional scarcity bonus
      STEP G — Subtract risk penalty
      STEP H — Normalize raw_score to [0.0, 100.0]
    """
    stats       = request.stats
    player_type = stats.player_type

    # STEP A: blend current season and 3-year average stats
    blended = _blend_stats(stats)

    # STEP B + C: apply age and depth chart adjustments
    blended = _apply_adjustments(blended, stats.age, stats.depth_order, player_type)

    # STEP E: compute z-scores from adjusted blended stats
    z_total = _compute_z_scores(blended, player_type)

    # STEP F: positional scarcity bonus (static — PlayerValueRequest has no roster data)
    position_bonus = POSITION_BONUS.get(request.position.upper(), 0.0)


    # STEP G: risk penalty
    risk_penalty = _get_risk_penalty(stats, blended)

    # STEP H: normalize to [0.0, 100.0]
    z_max        = Z_MAX_BATTER if player_type == "batter" else Z_MAX_PITCHER
    raw_score    = z_total + position_bonus - risk_penalty
    stat_score   = _normalize(z_total,   z_max)
    player_value = _normalize(raw_score, RAW_MAX)

    # Scale bonus and penalty to 0~100 for readable response breakdown
    bonus_scaled   = _normalize(position_bonus, RAW_MAX)
    penalty_scaled = _normalize(risk_penalty,   RAW_MAX)

    return PlayerValueResponse(
        player_name=request.player_name,
        player_type=player_type,
        player_value=round(player_value, 1),
        value_breakdown=ValueBreakdown(
            stat_score=round(stat_score,     1),
            position_bonus=round(bonus_scaled,   1),
            risk_penalty=round(penalty_scaled,   1),
        ),
    )


# ── Core Function 2: recommended_bid ─────────────────────────────────────────

def compute_recommended_bid(request: PlayerBidRequest, player_value: float | None = None) -> PlayerBidResponse:
    """
    Compute recommended_bid (integer dollar amount) for auction drafts.

    Full pipeline:
      Step 1 — player_value    = reuse compute_player_value()
      Step 2 — base_price      = (player_value / 100) * total_budget * HIT_PITCH_RATIO
      Step 3 — dynamic_bonus   = _get_dynamic_scarcity_bonus()
               early-exit      → recommended_bid = 1 if competitors_at_pos == 0
      Step 4 — adjusted_price  = base_price * scarcity_multiplier
      Step 5 — spendable       = my_remaining_budget - (my_remaining_roster_spots - 1)
      Step 6 — max_competitor_budget:
               competing_opponents = opponents who have not yet filled target position
               max_competitor_budget = max(their remaining budgets)
               falls back to spendable if opponent_budgets not provided
      Step 7 — draft_progress adjustment
      Step 8 — recommended_bid = clip(round(adjusted_price * draft_multiplier),
                                       1, min(spendable, max_competitor_budget))
    """
    # Step 1: reuse the player_value pipeline
    if player_value is None:
        value_response = compute_player_value(
            PlayerValueRequest(
                player_name=request.player_name,
                position=request.position,
                stats=request.stats,
            )
        )
        player_value = value_response.player_value
    player_type = request.stats.player_type

    lc  = request.league_context
    dc  = request.draft_context
    pos = request.position.upper()

    # Step 2: base price proportional to player value and total league budget
    ratio      = HIT_PITCH_RATIO.get(player_type, 0.5)
    base_price = (player_value / 100.0) * lc.total_budget * ratio

    # Step 3: dynamic scarcity bonus + early-exit check
    _, competitors_at_pos = _get_dynamic_scarcity_bonus(pos, dc.opponent_rosters)
    if competitors_at_pos == 0:
        return PlayerBidResponse(
            player_name=request.player_name,
            player_type=player_type,
            player_value=player_value,
            recommended_bid=1,
            bid_breakdown=BidBreakdown(
                base_price=round(base_price, 2),
                scarcity_adjustment=0.0,
                draft_adjustment=0.0,
                max_spendable=1,
                max_competitor_budget=1,
            ),
        )

    # Step 4: apply positional scarcity multiplier
    multiplier     = SCARCITY_MULTIPLIER.get(pos, 1.0)
    adjusted_price = base_price * multiplier
    scarcity_adj   = adjusted_price - base_price

    # Step 5: compute spendable — each remaining roster slot costs at least $1
    # If my_roster is provided, derive remaining spots from roster_size - len(my_roster).
    # Otherwise, use the client-supplied my_remaining_roster_spots as-is.
    if dc.my_roster is not None:
        my_remaining_roster_spots = lc.roster_size - len(dc.my_roster)
    else:
        my_remaining_roster_spots = dc.my_remaining_roster_spots
    min_reserve = max(0, my_remaining_roster_spots - 1)
    spendable   = max(1, dc.my_remaining_budget - min_reserve)

    # Step 6: max_competitor_budget
    # Determine which opponents are still competing for this position,
    # then find the maximum remaining budget among them.
    if dc.opponent_budgets is None:
        # No budget data provided — no competitor cap applied
        max_competitor_budget = spendable
    else:
        if dc.opponent_rosters is not None:
            # Filter to opponents who have NOT yet filled the target position
            competing_opponents = [
                name for name, roster in dc.opponent_rosters.items()
                if not any(entry.position.upper() == pos for entry in roster)
            ]
        else:
            # No roster data — treat all opponents as competing
            competing_opponents = list(dc.opponent_budgets.keys())

        if not competing_opponents:
            # All opponents already have this position filled — minimal bid
            return PlayerBidResponse(
                player_name=request.player_name,
                player_type=player_type,
                player_value=player_value,
                recommended_bid=1,
                bid_breakdown=BidBreakdown(
                    base_price=round(base_price, 2),
                    scarcity_adjustment=round(scarcity_adj, 2),
                    draft_adjustment=0.0,
                    max_spendable=spendable,
                    max_competitor_budget=1,
                ),
            )

        max_competitor_budget = max(
            dc.opponent_budgets.get(name, 0) for name in competing_opponents
        )
        # Ensure at least 1 to avoid clipping recommended_bid below minimum
        max_competitor_budget = max(1, max_competitor_budget)

    # Step 7: draft progress adjustment
    draft_progress   = dc.drafted_players_count / (lc.league_size * lc.roster_size)
    budget_ratio     = spendable / dc.my_remaining_budget if dc.my_remaining_budget > 0 else 0.5
    draft_multiplier = 1.0 + (budget_ratio - 0.5) * 0.2 * draft_progress
    draft_adj        = adjusted_price * draft_multiplier - adjusted_price

    # Step 8: clip to [1, min(spendable, max_competitor_budget)]
    effective_cap   = min(spendable, max_competitor_budget)
    raw_bid         = adjusted_price * draft_multiplier
    recommended_bid = max(1, min(effective_cap, round(raw_bid)))

    return PlayerBidResponse(
        player_name=request.player_name,
        player_type=player_type,
        player_value=player_value,
        recommended_bid=recommended_bid,
        bid_breakdown=BidBreakdown(
            base_price=round(base_price,        2),
            scarcity_adjustment=round(scarcity_adj,  2),
            draft_adjustment=round(draft_adj,       2),
            max_spendable=spendable,
            max_competitor_budget=max_competitor_budget,
        ),
    )