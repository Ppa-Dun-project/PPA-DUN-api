import statistics
from fastapi import HTTPException
from api.models.player import PlayerValueResponse, PlayerBidResponse, PlayerBidRequest
from api.data.mock_players import MOCK_PLAYER_POOL

# ── Constants ───────────────────────────────────────────
NUM_TEAMS = 12
BUDGET_PER_TEAM = 260
HITTER_SPLIT = 0.635        # Portion of total budget allocated to hitters
ROSTER_SPOTS = 14           # Hitter roster slots per team
MIN_AB = 150                # Players below this AB threshold are excluded from pool
REPLACEMENT_N = NUM_TEAMS * 2  # Replacement level = Nth best player in pool

# ── Helper: filter player pool ──────────────────────────
def _get_pool() -> list[dict]:
    """Return only players with AB >= MIN_AB"""
    return [p for p in MOCK_PLAYER_POOL if p["AB"] >= MIN_AB]

# ── Helper: z-score ─────────────────────────────────────
def _zscore(value: float, mean: float, std: float) -> float:
    """Returns 0 if std is 0 to prevent division by zero"""
    if std == 0:
        return 0.0
    return (value - mean) / std

# ── Helper: weighted z-score for AVG ────────────────────
def _avg_zscore(player: dict, pool: list[dict]) -> float:
    """
    AVG is a rate stat and cannot be z-scored directly.
    Measures: 'how much does this player shift the team AVG
    when added to an average team?'

    team_avg_with_player = (team_H + player_H) / (team_AB + player_AB)
    delta = team_avg_with_player - baseline_team_avg
    z_AVG = delta / std_dev(deltas across all players)
    """
    avg_AB = statistics.mean(p["AB"] for p in pool)
    avg_H  = statistics.mean(p["H"]  for p in pool)

    baseline_team_avg = (avg_H * ROSTER_SPOTS) / (avg_AB * ROSTER_SPOTS)

    deltas = []
    for p in pool:
        team_avg_with = (avg_H * ROSTER_SPOTS + p["H"]) / (avg_AB * ROSTER_SPOTS + p["AB"])
        deltas.append(team_avg_with - baseline_team_avg)

    delta_std = statistics.stdev(deltas) if len(deltas) > 1 else 1.0

    player_delta = (avg_H * ROSTER_SPOTS + player["H"]) / (avg_AB * ROSTER_SPOTS + player["AB"]) - baseline_team_avg

    return player_delta / delta_std if delta_std != 0 else 0.0

# ── Helper: compute FVARz for all players ───────────────
def _compute_all_fvarz(pool: list[dict]) -> dict[str, float]:
    """
    Returns {player_name: fvarz} for all players in pool.

    FVARz = sum(z_R, z_HR, z_RBI, z_SB, z_AVG) - replacement_z
    replacement_z = raw z-score sum of the REPLACEMENT_N-th best player
    """
    stats = {}
    for cat in ["R", "HR", "RBI", "SB"]:
        values = [p[cat] for p in pool]
        stats[cat] = {
            "mean": statistics.mean(values),
            "std":  statistics.stdev(values) if len(values) > 1 else 1.0
        }

    raw_scores = {}
    for p in pool:
        z = (
            _zscore(p["R"],   stats["R"]["mean"],   stats["R"]["std"])
            + _zscore(p["HR"],  stats["HR"]["mean"],  stats["HR"]["std"])
            + _zscore(p["RBI"], stats["RBI"]["mean"], stats["RBI"]["std"])
            + _zscore(p["SB"],  stats["SB"]["mean"],  stats["SB"]["std"])
            + _avg_zscore(p, pool)
        )
        raw_scores[p["Player"]] = z

    sorted_scores = sorted(raw_scores.values(), reverse=True)
    replacement_z = sorted_scores[REPLACEMENT_N - 1] if len(sorted_scores) >= REPLACEMENT_N else sorted_scores[-1]

    fvarz = {name: score - replacement_z for name, score in raw_scores.items()}
    return fvarz

# ── Helper: convert FVARz to auction dollars ────────────
def _fvarz_to_dollar(fvarz: float, all_fvarz: dict[str, float]) -> int:
    """
    total_budget = NUM_TEAMS x BUDGET_PER_TEAM x HITTER_SPLIT
    player_value = (fvarz / sum_of_positive_fvarz) x total_budget
    Minimum value: $1
    """
    total_budget = NUM_TEAMS * BUDGET_PER_TEAM * HITTER_SPLIT
    sum_positive = sum(v for v in all_fvarz.values() if v > 0)

    if sum_positive == 0 or fvarz <= 0:
        return 1

    dollar = (fvarz / sum_positive) * total_budget
    return max(1, round(dollar))

# ── Core function 1: player_value ───────────────────────
def get_player_value(player_name: str) -> PlayerValueResponse:
    pool = _get_pool()

    player = next(
        (p for p in pool if p["Player"].lower() == player_name.lower()),
        None
    )
    if player is None:
        raise HTTPException(status_code=404, detail=f"Player '{player_name}' not found")

    all_fvarz = _compute_all_fvarz(pool)
    player_fvarz = all_fvarz.get(player["Player"], 0.0)
    value = _fvarz_to_dollar(player_fvarz, all_fvarz)

    return PlayerValueResponse(player_name=player["Player"], player_value=value)

# ── Core function 2: recommended_bid ────────────────────
def get_recommended_bid(player_name: str, draft_state: PlayerBidRequest) -> PlayerBidResponse:
    # Base value from player_value calculation
    base = get_player_value(player_name).player_value

    # ── Factor 1: Position need ──
    # Full position matching deferred until player position data is added
    need_factor = 1.0
    all_opponents_have = all(
        player_name.lower() in [p.lower() for p in opp.positions_filled]
        for opp in draft_state.opponents
    )
    if all_opponents_have:
        need_factor = 0.80  # No competition — all opponents already filled this

    # ── Factor 2: Draft stage discount ──
    budget_ratio = draft_state.my_budget_remaining / BUDGET_PER_TEAM
    if budget_ratio < 0.30:
        stage_discount = 0.80   # End game
    elif budget_ratio < 0.60:
        stage_discount = 0.90   # Mid draft
    else:
        stage_discount = 1.00   # Early

    # ── Factor 3: Budget ceiling ──
    max_safe_bid = draft_state.my_budget_remaining - len(draft_state.my_roster_empty)

    adjusted = base * need_factor * stage_discount
    recommended = max(1, min(round(adjusted), max_safe_bid))

    return PlayerBidResponse(player_name=player_name, recommended_bid=recommended)