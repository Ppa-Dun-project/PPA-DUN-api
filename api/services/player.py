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

# ── League Baseline Constants (Roto 5x5 standard) ───────────────────────────
# These values represent the mean and standard deviation of each scoring
# category across a typical 12-team Roto 5x5 fantasy-relevant player pool.
#
# They are used to compute z-scores:
#   z = (player_stat - mean) / std
#
# A player exactly at league average scores z = 0.
# A player one standard deviation above average scores z = 1.
#
# Source: derived from historical MLB fantasy league data.
# These are internal constants — clients do not need to provide them.

BATTER_BASELINES = {
    "R":   {"mean": 75.0,  "std": 20.0},
    "HR":  {"mean": 18.0,  "std": 10.0},
    "RBI": {"mean": 72.0,  "std": 20.0},
    "SB":  {"mean": 12.0,  "std": 10.0},
    "AVG": {"mean": 0.260, "std": 0.025},
}

PITCHER_BASELINES = {
    "W":    {"mean": 10.0,  "std": 4.0},
    "SV":   {"mean": 10.0,  "std": 14.0},  # High std because closers skew the pool
    "K":    {"mean": 130.0, "std": 50.0},
    "ERA":  {"mean": 4.00,  "std": 0.70},
    "WHIP": {"mean": 1.25,  "std": 0.15},
}

# ── Normalization Ceilings ───────────────────────────────────────────────────
# Z_MAX_* = approximate z_total of an all-time elite player in a single season.
# RAW_MAX  = Z_MAX + maximum possible position_bonus (C = +1.5 → RAW_MAX = 11.5,
#            rounded up to 12.0 for headroom).
# These are used to scale raw scores into the [0.0, 100.0] range.
# Values above the ceiling are clipped to 100.0.

Z_MAX_BATTER  = 10.0
Z_MAX_PITCHER = 10.0
RAW_MAX       = 12.0

# ── Hitter / Pitcher Budget Split ────────────────────────────────────────────
# Standard Roto 5x5 auction convention: ~67% of budget goes to batters,
# ~33% to pitchers. Used in base_price calculation.

HIT_PITCH_RATIO = {
    "batter":  0.67,
    "pitcher": 0.33,
}

# ── Positional Scarcity Bonus ────────────────────────────────────────────────
# Added to z_total (in z-score units) before normalization.
# Reflects the fact that scarce positions (C, SS) carry extra value even when
# raw stats are equal to a less scarce position (1B, OF).
# A catcher at league-average batting is worth more than a first baseman at
# the same stats because elite catchers are much harder to find.

POSITION_BONUS = {
    "C":  1.5,   # Fewest quality options; highest scarcity in the player pool
    "SS": 0.8,   # Historically thin talent pool
    "RP": 0.6,   # Saves are scarce; role instability adds a value premium
    "CL": 0.6,   # Treated same as RP
    "SP": 0.4,   # Quality depth exists but elite SPs still command a premium
    "2B": 0.5,   # Moderately scarce
    "3B": 0.3,   # Slight scarcity
    "1B": 0.0,   # Deepest positions; no scarcity premium
    "OF": 0.0,
    "DH": 0.0,
}

# ── Positional Scarcity Multiplier ───────────────────────────────────────────
# Applied to base_price (in dollars) during bid calculation.
# Separate from POSITION_BONUS — this multiplier directly inflates the dollar
# bid to reflect real auction market behavior where C and SS prices carry
# visible premiums over their raw stat contribution.

SCARCITY_MULTIPLIER = {
    "C":  1.15,   # +15% bid premium
    "SS": 1.08,   # +8%
    "2B": 1.05,   # +5%
    "SP": 1.05,
    "RP": 1.05,
    "CL": 1.05,
    "3B": 1.02,   # +2%
    "1B": 1.00,   # No adjustment
    "OF": 1.00,
    "DH": 1.00,
}


# ── Internal Helpers ─────────────────────────────────────────────────────────

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
    Scale a raw value to the [0.0, 100.0] range using a linear mapping,
    then clip to ensure the result never falls outside the boundary.

    Formula: scaled = clip((value / max_val) * 100, 0, 100)
    """
    if max_val == 0:
        return 0.0
    scaled = (value / max_val) * 100.0
    return max(0.0, min(100.0, scaled))


def _compute_z_scores(stats: BatterStats | PitcherStats, player_type: str) -> float:
    """
    Sum z-scores across all 5 Roto categories for the given player type.

    Batters:  R + HR + RBI + SB + AVG  (all higher = better)
    Pitchers: W + SV + K - ERA - WHIP  (ERA and WHIP are negated because
              lower values are better; negating the z-score flips the sign
              so that a below-average ERA yields a positive contribution)

    Returns z_total: the sum of all 5 category z-scores.
    An elite player typically scores z_total >> 0.
    A replacement-level player typically scores z_total < 0.
    """
    if player_type == "batter":
        b = BATTER_BASELINES
        z_total = (
            _zscore(stats.R,   b["R"]["mean"],   b["R"]["std"])
            + _zscore(stats.HR,  b["HR"]["mean"],  b["HR"]["std"])
            + _zscore(stats.RBI, b["RBI"]["mean"], b["RBI"]["std"])
            + _zscore(stats.SB,  b["SB"]["mean"],  b["SB"]["std"])
            + _zscore(stats.AVG, b["AVG"]["mean"], b["AVG"]["std"])
        )
    else:
        p = PITCHER_BASELINES
        # Negate ERA and WHIP z-scores: lower stat value → higher fantasy value
        z_total = (
            _zscore(stats.W,    p["W"]["mean"],    p["W"]["std"])
            + _zscore(stats.SV,   p["SV"]["mean"],   p["SV"]["std"])
            + _zscore(stats.K,    p["K"]["mean"],    p["K"]["std"])
            - _zscore(stats.ERA,  p["ERA"]["mean"],  p["ERA"]["std"])
            - _zscore(stats.WHIP, p["WHIP"]["mean"], p["WHIP"]["std"])
        )
    return z_total


def _get_position_bonus(position: str) -> float:
    """
    Return the positional scarcity bonus (in z-score units) for the given
    position string. Defaults to 0.0 for unrecognized positions.
    """
    return POSITION_BONUS.get(position.upper(), 0.0)


def _get_risk_penalty(stats: BatterStats | PitcherStats, player_type: str) -> float:
    """
    Compute the total risk penalty (in z-score units) based on conditions
    that reduce the reliability of a player's expected output.

    All conditions are evaluated independently — multiple penalties can
    stack if more than one condition is met simultaneously.

    Batter conditions:
      - AB < 300       : insufficient playing time, high variance  → -0.5
      - CS/(SB+CS) > 0.35 : poor stolen base efficiency           → -0.2

    Pitcher conditions:
      - IP < 100       : insufficient innings, likely part-time    → -0.5
      - ERA > 4.50     : ERA above this threshold hurts roto standings → -0.3
    """
    penalty = 0.0

    if player_type == "batter":
        if stats.AB < 300:
            penalty += 0.5
        total_attempts = stats.SB + stats.CS
        # Guard against division by zero when a player has 0 SB and 0 CS
        if total_attempts > 0 and (stats.CS / total_attempts) > 0.35:
            penalty += 0.2

    else:  # pitcher
        if stats.IP < 100:
            penalty += 0.5
        if stats.ERA > 4.50:
            penalty += 0.3

    return penalty


# ── Core Function 1: player_value ────────────────────────────────────────────

def compute_player_value(request: PlayerValueRequest) -> PlayerValueResponse:
    """
    Compute player_value (0.0 ~ 100.0) using the Roto 5x5 FVARz algorithm.

    Full pipeline:
      Step 1 — z_total      = sum of z-scores across 5 roto categories
      Step 2 — position_bonus = scarcity bonus for the player's position (z units)
      Step 3 — risk_penalty   = stacked risk deductions (z units)
      Step 4 — raw_score    = z_total + position_bonus - risk_penalty
      Step 5 — stat_score   = normalize(z_total,   Z_MAX)   → 0~100 (stats only)
      Step 6 — player_value = normalize(raw_score, RAW_MAX) → 0~100 (final)

    stat_score is included in value_breakdown to show the pure stat contribution
    before bonuses and penalties are applied.
    position_bonus and risk_penalty are scaled to 0~100 for readability in the
    response breakdown, but internally they are in z-score units.
    """
    z_max = Z_MAX_BATTER if request.player_type == "batter" else Z_MAX_PITCHER

    z_total        = _compute_z_scores(request.stats, request.player_type)
    position_bonus = _get_position_bonus(request.position)
    risk_penalty   = _get_risk_penalty(request.stats, request.player_type)

    raw_score    = z_total + position_bonus - risk_penalty
    stat_score   = _normalize(z_total,   z_max)
    player_value = _normalize(raw_score, RAW_MAX)

    # Scale bonus and penalty to 0~100 for readable response breakdown
    bonus_scaled   = _normalize(position_bonus, RAW_MAX)
    penalty_scaled = _normalize(risk_penalty,   RAW_MAX)

    return PlayerValueResponse(
        player_name=request.player_name,
        player_type=request.player_type,
        player_value=round(player_value, 1),
        value_breakdown=ValueBreakdown(
            stat_score=round(stat_score,     1),
            position_bonus=round(bonus_scaled,   1),
            risk_penalty=round(penalty_scaled,   1),
        ),
    )


# ── Core Function 2: recommended_bid ─────────────────────────────────────────

def compute_recommended_bid(request: PlayerBidRequest) -> PlayerBidResponse:
    """
    Compute recommended_bid (integer dollar amount) for auction drafts.

    Full pipeline:
      Step 1 — player_value   = reuse compute_player_value()
      Step 2 — base_price     = (player_value / 100) * total_budget * HIT_PITCH_RATIO
      Step 3 — adjusted_price = base_price * scarcity_multiplier
      Step 4 — spendable      = my_remaining_budget - (my_remaining_roster_spots - 1)
                                (each unfilled slot must cost at least $1)
      Step 5 — draft_progress = drafted_players_count / (league_size * roster_size)
               budget_ratio   = spendable / my_remaining_budget
               draft_multiplier = 1.0 + (budget_ratio - 0.5) * 0.2 * draft_progress
                 → budget_ratio > 0.5: plenty of budget → multiplier > 1.0 → bid UP
                 → budget_ratio < 0.5: budget is tight  → multiplier < 1.0 → bid DOWN
                 → draft_progress scales the effect: stronger adjustment late in draft
      Step 6 — recommended_bid = clip(round(adjusted_price * draft_multiplier), 1, spendable)
    """
    # Step 1: reuse the player_value pipeline rather than duplicating logic
    value_response = compute_player_value(
        PlayerValueRequest(
            player_name=request.player_name,
            player_type=request.player_type,
            position=request.position,
            stats=request.stats,
            league_context=request.league_context,
        )
    )
    player_value = value_response.player_value

    lc  = request.league_context
    dc  = request.draft_context
    pos = request.position.upper()

    # Step 2: base price — proportional to player value and total league budget
    ratio      = HIT_PITCH_RATIO.get(request.player_type, 0.5)
    base_price = (player_value / 100.0) * lc.total_budget * ratio

    # Step 3: apply positional scarcity multiplier to inflate bid for scarce positions
    multiplier     = SCARCITY_MULTIPLIER.get(pos, 1.0)
    adjusted_price = base_price * multiplier
    scarcity_adj   = adjusted_price - base_price  # dollar amount added by scarcity

    # Step 4: compute the hard ceiling on what the user can spend on a single player.
    # Each remaining unfilled roster slot must cost at least $1 at auction,
    # so the maximum spendable amount on this player is budget minus those reserves.
    min_reserve = dc.my_remaining_roster_spots - 1
    spendable   = max(1, dc.my_remaining_budget - min_reserve)

    # Step 5: draft progress adjustment
    # draft_progress approaches 1.0 as the draft nears completion.
    # budget_ratio > 0.5 means the user has more spendable budget than usual
    # → encourage spending by pushing the bid up.
    total_players    = lc.league_size * lc.roster_size
    draft_progress   = dc.drafted_players_count / total_players if total_players > 0 else 0.0
    budget_ratio     = spendable / dc.my_remaining_budget if dc.my_remaining_budget > 0 else 0.5

    draft_multiplier = 1.0 + (budget_ratio - 0.5) * 0.2 * draft_progress
    draft_adj        = adjusted_price * draft_multiplier - adjusted_price  # net dollar change

    # Step 6: apply multiplier, round to integer, clip to [1, spendable]
    raw_bid         = adjusted_price * draft_multiplier
    recommended_bid = max(1, min(round(raw_bid), spendable))

    return PlayerBidResponse(
        player_name=request.player_name,
        player_type=request.player_type,
        player_value=player_value,
        recommended_bid=recommended_bid,
        bid_breakdown=BidBreakdown(
            base_price=round(base_price,    2),
            scarcity_adjustment=round(scarcity_adj,  2),
            draft_adjustment=round(draft_adj,     2),
            max_spendable=spendable,
        ),
    )