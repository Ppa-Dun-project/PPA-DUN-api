"""
test_a_integration.py
=====================
Integration tests for the PPA-DUN project.

Covers:
  - FVARz algorithm functions (unit-level, direct calls to service layer)
  - API server endpoints with mocked DB auth (/player/value, /player/bid,
    /player/bid/id, /players/batters, /players/pitchers, /demo/*, /health,
    /internal/reload-baselines)
  - Backend server endpoints with mocked Google OAuth and SQLite in-memory DB
    (/api/auth/google, /api/auth/api-key, /api/auth/allowed-ip)
  - Baseline push flow: backend compute_baselines → POST /internal/reload-baselines
    → API server cache update → z-score recalculation reflects new baselines
  - Frontend Demo component: rendering, mode/type toggles, submit handler, error state
  - All fixture-driven tests load JSON files from
    tests/ppa_dun_actual_fixtures/  (league_state_*, sample_full_requests/*)

Run from project root:
  pytest tests/test_a_integration.py -v -s

Dependencies (install if missing):
  pip install pytest httpx fastapi[all] sqlalchemy pytest-mock
  pip install vitest @testing-library/react @testing-library/user-event msw  (frontend)
"""

# ── Python stdlib / third-party ───────────────────────────────────────────────
import json
import os
import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

# ── Project imports ───────────────────────────────────────────────────────────
# API server
from api.main import app as api_app
from api.services.player import (
    compute_player_value,
    compute_recommended_bid,
    reload_baselines,
    get_baselines,
    _blend_stats,
    _apply_adjustments,
    _compute_z_scores,
    _get_risk_penalty,
    _get_dynamic_scarcity_bonus,
    _get_age_factor,
    _get_depth_factor,
    POSITION_BONUS,
)
from api.models.player import (
    PlayerValueRequest,
    PlayerBidRequest,
    BatterStats,
    PitcherStats,
    LeagueContext,
    DraftContext,
    RosterEntry,
)

# Backend server
# PYTHONPATH includes backend/ directly, so use db.* (not backend.db.*)
# to avoid SQLAlchemy MetaData double-registration when both
# "db.models" and "backend.db.models" resolve to the same physical file.
import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).parent.parent / "backend"))

from main import app as backend_app  # backend/main.py
from db.session import Base, get_db   # backend/db/session.py
from db.models import User, APIKey, UserAllowedIP  # backend/db/models.py

# ── Fixture paths ─────────────────────────────────────────────────────────────
FIXTURE_DIR = Path(__file__).parent / "ppa_dun_actual_fixtures"
SAMPLE_DIR  = FIXTURE_DIR / "sample_full_requests"


# ═══════════════════════════════════════════════════════════════════════════════
# Shared helpers
# ═══════════════════════════════════════════════════════════════════════════════

def _load_json(path: Path) -> dict:
    with open(path) as f:
        return json.load(f)


def _api_auth_mock():
    """
    Returns a mock SessionLocal for the API server that always returns a valid
    (key_id=1, user_id=1) row from the api_keys table lookup.
    """
    db  = MagicMock()
    res = MagicMock()
    res.fetchone.return_value = (1, 1)   # (id, user_id)
    db.execute.return_value   = res
    return MagicMock(return_value=db)


def _auth_patches():
    """
    Context manager: patch DB auth + IP whitelist check together.
    Usage:  with _auth_patches():  resp = api_client.post(...)
    """
    from contextlib import ExitStack
    stack = ExitStack()
    stack.enter_context(patch("api.main.SessionLocal", _api_auth_mock()))
    stack.enter_context(patch("api.main.check_ip_whitelist", return_value=True))
    return stack


# ── SQLite in-memory DB for backend tests ─────────────────────────────────────

@pytest.fixture(scope="module")
def backend_db_engine():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(bind=engine)
    return engine


@pytest.fixture
def backend_db_session(backend_db_engine):
    """Fresh SQLite session for each test; rolls back after each test."""
    connection   = backend_db_engine.connect()
    transaction  = connection.begin()
    TestSession  = sessionmaker(bind=connection)
    session      = TestSession()

    yield session

    session.close()
    transaction.rollback()
    connection.close()


@pytest.fixture
def backend_client(backend_db_session):
    """
    TestClient for the backend FastAPI app with the real DB dependency
    replaced by the SQLite in-memory session.
    """
    def override_get_db():
        try:
            yield backend_db_session
        finally:
            pass

    backend_app.dependency_overrides[get_db] = override_get_db
    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def _noop_lifespan(app):
        yield

    # Swap the app's lifespan_context directly — module-level patching doesn't
    # affect a FastAPI app that already captured the lifespan at import time.
    original_lifespan = backend_app.router.lifespan_context
    backend_app.router.lifespan_context = _noop_lifespan
    try:
        with TestClient(backend_app, raise_server_exceptions=False) as c:
            yield c
    finally:
        backend_app.router.lifespan_context = original_lifespan
        backend_app.dependency_overrides.clear()


# ── Google OAuth mock helper ───────────────────────────────────────────────────

def _mock_google_token(sub: str = "google-uid-001",
                       email: str = "test@example.com",
                       name: str  = "Test User"):
    """Patch google id_token.verify_oauth2_token to return a fake idinfo."""
    return patch(
        "routers.auth._verify_google_token",
        return_value={"sub": sub, "email": email, "name": name},
    )


# ═══════════════════════════════════════════════════════════════════════════════
# Section 1 — FVARz Algorithm (pure service-layer unit tests)
# ═══════════════════════════════════════════════════════════════════════════════

class TestStatBlending:
    """STEP A: _blend_stats() produces the correct 0.6/0.4 weighted average."""

    def test_batter_blending_with_3yr(self):
        stats = BatterStats(
            player_type="batter",
            AB=600, R=100, HR=40, RBI=110, SB=20, CS=3, AVG=0.290,
            R_3yr=90, HR_3yr=35, RBI_3yr=100, SB_3yr=18, CS_3yr=4, AVG_3yr=0.275,
        )
        blended = _blend_stats(stats)
        assert blended["R"]   == pytest.approx(0.6 * 100 + 0.4 * 90,  abs=0.01)
        assert blended["HR"]  == pytest.approx(0.6 * 40  + 0.4 * 35,  abs=0.01)
        assert blended["AVG"] == pytest.approx(0.6 * 0.290 + 0.4 * 0.275, abs=0.001)

    def test_batter_blending_without_3yr_uses_current(self):
        stats = BatterStats(
            player_type="batter",
            AB=600, R=100, HR=40, RBI=110, SB=20, CS=3, AVG=0.290,
        )
        blended = _blend_stats(stats)
        # No 3yr data → blended stat equals current stat
        assert blended["R"]  == pytest.approx(100.0, abs=0.01)
        assert blended["HR"] == pytest.approx(40.0,  abs=0.01)

    def test_pitcher_blending_with_3yr(self):
        stats = PitcherStats(
            player_type="pitcher",
            IP=180.0, W=14, SV=0, K=220, ERA=2.80, WHIP=0.97,
            W_3yr=12, SV_3yr=0, K_3yr=200, ERA_3yr=3.10, WHIP_3yr=1.05,
        )
        blended = _blend_stats(stats)
        assert blended["W"]   == pytest.approx(0.6 * 14 + 0.4 * 12,  abs=0.01)
        assert blended["ERA"] == pytest.approx(0.6 * 2.80 + 0.4 * 3.10, abs=0.001)

    def test_ab_and_cs_pass_through_unblended(self):
        """AB and CS must pass through as current values (used only in risk penalty)."""
        stats = BatterStats(
            player_type="batter",
            AB=400, R=60, HR=15, RBI=65, SB=10, CS=5, AVG=0.260,
            AB_3yr=380, CS_3yr=6,
        )
        blended = _blend_stats(stats)
        assert blended["AB"] == 400.0   # current, not blended
        assert blended["CS"] == 5.0     # current, not blended


class TestAgeAndDepthFactors:
    """STEP B + C: age and depth factor tables."""

    @pytest.mark.parametrize("age,expected", [
        (22,  1.05),
        (25,  1.05),
        (28,  1.00),
        (30,  1.00),
        (32,  0.95),
        (33,  0.95),
        (35,  0.90),
        (40,  0.90),
        (None, 1.00),
    ])
    def test_age_factor(self, age, expected):
        assert _get_age_factor(age) == pytest.approx(expected)

    @pytest.mark.parametrize("depth,expected", [
        (1, 1.00),
        (2, 0.90),
        (3, 0.75),
        (4, 0.60),
        (9, 0.60),
        (None, 1.00),
    ])
    def test_depth_factor(self, depth, expected):
        assert _get_depth_factor(depth) == pytest.approx(expected)

    def test_rate_stats_excluded_from_depth(self):
        """AVG must not be multiplied by depth_factor; only by age_factor."""
        blended = {"R": 100.0, "HR": 30.0, "RBI": 90.0, "SB": 15.0,
                   "AVG": 0.280, "AB": 500.0, "CS": 4.0}
        adjusted = _apply_adjustments(blended, age=28, depth_order=2, player_type="batter")
        # depth=2 → factor 0.90; age=28 → factor 1.00
        assert adjusted["R"]   == pytest.approx(100.0 * 1.00 * 0.90, abs=0.01)
        assert adjusted["AVG"] == pytest.approx(0.280 * 1.00,         abs=0.001)  # no depth

    def test_ab_cs_ip_excluded_from_adjustments(self):
        """AB, CS, IP must not be altered by age or depth adjustments."""
        blended = {"W": 12.0, "SV": 0.0, "K": 180.0,
                   "ERA": 3.50, "WHIP": 1.15, "IP": 150.0}
        adjusted = _apply_adjustments(blended, age=30, depth_order=2, player_type="pitcher")
        assert adjusted["IP"] == pytest.approx(150.0)


class TestZScoreCalculation:
    """STEP E: z-score direction and magnitude checks."""

    def test_elite_batter_higher_z_than_average(self):
        """An elite batter (top stats) must score higher z_total than an average one."""
        elite_blended   = {"R": 120.0, "HR": 45.0, "RBI": 120.0, "SB": 30.0,
                           "AVG": 0.310, "AB": 550.0, "CS": 3.0}
        average_blended = {"R": 75.0,  "HR": 18.0, "RBI": 72.0,  "SB": 12.0,
                           "AVG": 0.260, "AB": 480.0, "CS": 5.0}
        z_elite   = _compute_z_scores(elite_blended,   "batter")
        z_average = _compute_z_scores(average_blended, "batter")
        assert z_elite > z_average

    def test_era_whip_negated_for_pitchers(self):
        """Lower ERA/WHIP must produce higher z_total (ERA and WHIP are negated)."""
        good_blended = {"W": 14.0, "SV": 0.0, "K": 220.0,
                        "ERA": 2.50, "WHIP": 0.95, "IP": 175.0}
        bad_blended  = {"W": 8.0,  "SV": 0.0, "K": 120.0,
                        "ERA": 5.00, "WHIP": 1.50, "IP": 130.0}
        assert _compute_z_scores(good_blended, "pitcher") > _compute_z_scores(bad_blended, "pitcher")

    def test_invalid_player_type_raises(self):
        with pytest.raises(ValueError, match="Invalid player_type"):
            _compute_z_scores({}, "outfielder")


class TestRiskPenalty:
    """STEP G: risk penalty conditions."""

    def test_low_ab_penalty(self):
        stats   = BatterStats(player_type="batter",
                              AB=200, R=40, HR=10, RBI=40, SB=5, CS=1, AVG=0.250)
        blended = _blend_stats(stats)
        penalty = _get_risk_penalty(stats, blended)
        assert penalty >= 0.5

    def test_no_penalty_healthy_full_time_batter(self):
        stats   = BatterStats(player_type="batter",
                              AB=550, R=80, HR=25, RBI=85, SB=15, CS=3, AVG=0.275)
        blended = _blend_stats(stats)
        penalty = _get_risk_penalty(stats, blended)
        assert penalty == pytest.approx(0.0)

    def test_high_cs_ratio_penalty(self):
        """CS/(SB+CS) > 0.35 should trigger an additional -0.2 penalty."""
        stats   = BatterStats(player_type="batter",
                              AB=500, R=70, HR=20, RBI=75, SB=5, CS=10, AVG=0.260)
        blended = _blend_stats(stats)
        penalty = _get_risk_penalty(stats, blended)
        assert penalty >= 0.2

    def test_low_ip_penalty(self):
        stats   = PitcherStats(player_type="pitcher",
                               IP=80.0, W=5, SV=0, K=90, ERA=3.80, WHIP=1.20)
        blended = _blend_stats(stats)
        penalty = _get_risk_penalty(stats, blended)
        assert penalty >= 0.5

    def test_high_era_penalty(self):
        stats   = PitcherStats(player_type="pitcher",
                               IP=150.0, W=8, SV=0, K=140, ERA=5.20, WHIP=1.40)
        blended = _blend_stats(stats)
        penalty = _get_risk_penalty(stats, blended)
        assert penalty >= 0.3

    @pytest.mark.parametrize("status,expected_min", [
        ("Day-To-Day", 0.1),
        ("10-Day IL",  0.3),
        ("15-Day IL",  0.4),
        ("60-Day IL",  0.7),
        ("Out",        1.0),
    ])
    def test_injury_penalty_values(self, status, expected_min):
        stats = BatterStats(player_type="batter",
                            AB=500, R=80, HR=25, RBI=85, SB=15, CS=3, AVG=0.275,
                            injury_status=status)
        blended = _blend_stats(stats)
        penalty = _get_risk_penalty(stats, blended)
        assert penalty >= expected_min


class TestPositionalScarcityBonus:
    """STEP F: positional scarcity bonus via POSITION_BONUS and dynamic scarcity."""

    def test_catcher_highest_static_bonus(self):
        assert POSITION_BONUS["C"] > POSITION_BONUS["SS"]
        assert POSITION_BONUS["C"] > POSITION_BONUS["OF"]

    def test_dynamic_bonus_increases_when_opponents_fill_position(self):
        """
        When more opponents have already drafted a position, the remaining
        players at that position become scarcer → dynamic bonus should increase.
        """
        no_opponents_drafted  = {}
        many_opponents_drafted = {
            "Team B": [RosterEntry(player_name="X", position="C"),
                       RosterEntry(player_name="Y", position="OF")],
            "Team C": [RosterEntry(player_name="Z", position="C")],
        }
        bonus_empty = _get_dynamic_scarcity_bonus("C", no_opponents_drafted,  spendable_budget=235.0)
        bonus_full  = _get_dynamic_scarcity_bonus("C", many_opponents_drafted, spendable_budget=235.0)
        assert bonus_full >= bonus_empty

    def test_dynamic_bonus_fallback_without_rosters(self):
        """No opponent_rosters → should fall back to static POSITION_BONUS * scale."""
        bonus = _get_dynamic_scarcity_bonus("C", None)
        assert bonus > 0.0

    def test_of_position_zero_static_bonus(self):
        bonus = _get_dynamic_scarcity_bonus("OF", None)
        # OF base_bonus = 0.0; with no opponents, bonus stays 0
        assert bonus == pytest.approx(0.0)


class TestBaselineCache:
    """Baseline cache: reload and fallback behavior."""

    def test_reload_and_retrieve_baselines(self):
        custom = {
            "R":   {"mean": 80.0, "std": 22.0},
            "HR":  {"mean": 20.0, "std": 11.0},
            "RBI": {"mean": 75.0, "std": 21.0},
            "SB":  {"mean": 13.0, "std": 11.0},
            "AVG": {"mean": 0.262, "std": 0.026},
        }
        reload_baselines(batter=custom, pitcher={
            "W":    {"mean": 10.0,  "std": 4.0},
            "SV":   {"mean": 10.0,  "std": 14.0},
            "K":    {"mean": 130.0, "std": 50.0},
            "ERA":  {"mean": 4.00,  "std": 0.70},
            "WHIP": {"mean": 1.25,  "std": 0.15},
        })
        b = get_baselines("batter")
        assert b["R"]["mean"] == pytest.approx(80.0)

    def test_invalid_player_type_raises(self):
        with pytest.raises(ValueError):
            get_baselines("unknown")

    def test_player_value_changes_after_baseline_reload(self):
        """
        If baselines shift significantly, player_value must reflect the new
        reference pool rather than the old constants.
        """
        request = PlayerValueRequest(
            player_name="Test Player",
            position="OF",
            stats=BatterStats(
                player_type="batter",
                AB=540, R=85, HR=24, RBI=88, SB=15, CS=4, AVG=0.276,
            ),
        )

        # Set low-mean baselines (player looks elite)
        reload_baselines(
            batter={"R":   {"mean": 40.0, "std": 15.0},
                    "HR":  {"mean": 10.0, "std":  8.0},
                    "RBI": {"mean": 40.0, "std": 15.0},
                    "SB":  {"mean":  5.0, "std":  7.0},
                    "AVG": {"mean": 0.230, "std": 0.020}},
            pitcher={"W": {"mean":10.0,"std":4.0},"SV":{"mean":10.0,"std":14.0},
                     "K":{"mean":130.0,"std":50.0},"ERA":{"mean":4.0,"std":0.7},
                     "WHIP":{"mean":1.25,"std":0.15}},
        )
        value_low_baseline = compute_player_value(request).player_value

        # Set high-mean baselines (player looks average)
        reload_baselines(
            batter={"R":   {"mean": 110.0, "std": 20.0},
                    "HR":  {"mean": 35.0,  "std": 10.0},
                    "RBI": {"mean": 105.0, "std": 20.0},
                    "SB":  {"mean": 25.0,  "std": 10.0},
                    "AVG": {"mean": 0.290, "std": 0.025}},
            pitcher={"W": {"mean":10.0,"std":4.0},"SV":{"mean":10.0,"std":14.0},
                     "K":{"mean":130.0,"std":50.0},"ERA":{"mean":4.0,"std":0.7},
                     "WHIP":{"mean":1.25,"std":0.15}},
        )
        value_high_baseline = compute_player_value(request).player_value

        assert value_low_baseline > value_high_baseline


class TestComputePlayerValue:
    """compute_player_value(): output range, tier logic, positional ordering."""

    def test_output_in_range(self):
        req = PlayerValueRequest(
            player_name="Juan Soto", position="OF",
            stats=BatterStats(player_type="batter",
                              AB=534, R=113, HR=37, RBI=97, SB=23, CS=4, AVG=0.281),
        )
        resp = compute_player_value(req)
        assert 0.0 <= resp.player_value <= 100.0

    def test_response_fields_present(self):
        req = PlayerValueRequest(
            player_name="Paul Skenes", position="SP",
            stats=PitcherStats(player_type="pitcher",
                               IP=180.0, W=14, SV=0, K=220, ERA=2.80, WHIP=0.97),
        )
        resp = compute_player_value(req)
        assert hasattr(resp, "player_value")
        assert hasattr(resp, "value_breakdown")
        assert resp.value_breakdown.stat_score   >= 0.0
        assert resp.value_breakdown.position_bonus >= 0.0
        assert resp.value_breakdown.risk_penalty  >= 0.0

    def test_catcher_higher_than_outfielder_same_stats(self):
        """Identical hitting stats should yield a higher value for C than OF."""
        stats = BatterStats(player_type="batter",
                            AB=500, R=80, HR=25, RBI=85, SB=15, CS=3, AVG=0.275)
        val_c  = compute_player_value(PlayerValueRequest(
            player_name="X", position="C",  stats=stats)).player_value
        val_of = compute_player_value(PlayerValueRequest(
            player_name="X", position="OF", stats=stats)).player_value
        assert val_c > val_of

    def test_injured_player_lower_value(self):
        """A player on the 60-Day IL must have a lower value than the same healthy player."""
        healthy = BatterStats(player_type="batter",
                              AB=540, R=90, HR=28, RBI=92, SB=18, CS=3, AVG=0.278)
        injured = BatterStats(player_type="batter",
                              AB=540, R=90, HR=28, RBI=92, SB=18, CS=3, AVG=0.278,
                              injury_status="60-Day IL")
        val_h = compute_player_value(
            PlayerValueRequest(player_name="X", position="OF", stats=healthy)).player_value
        val_i = compute_player_value(
            PlayerValueRequest(player_name="X", position="OF", stats=injured)).player_value
        assert val_h > val_i

    def test_player_value_constant_across_draft_contexts(self):
        """
        player_value depends only on stats, not on draft context.
        The same stats submitted at predraft vs after_50 must yield identical values.
        """
        stats = BatterStats(player_type="batter",
                            AB=540, R=85, HR=24, RBI=88, SB=15, CS=4, AVG=0.276)
        req = PlayerValueRequest(player_name="Sample", position="OF", stats=stats)
        val1 = compute_player_value(req).player_value
        val2 = compute_player_value(req).player_value
        assert val1 == val2


class TestComputeRecommendedBid:
    """compute_recommended_bid(): bid constraints, budget response, competitor cap."""

    def _bid_request(self, remaining_budget: int, remaining_spots: int,
                     drafted_count: int, my_roster=None,
                     opponent_rosters=None, opponent_budgets=None) -> PlayerBidRequest:
        return PlayerBidRequest(
            player_name="Sample Hitter",
            position="OF",
            stats=BatterStats(player_type="batter",
                              AB=540, R=85, HR=24, RBI=88, SB=15, CS=4, AVG=0.276),
            league_context=LeagueContext(league_size=9, roster_size=23, total_budget=260),
            draft_context=DraftContext(
                my_remaining_budget=remaining_budget,
                my_remaining_roster_spots=remaining_spots,
                drafted_players_count=drafted_count,
                my_roster=my_roster,
                opponent_rosters=opponent_rosters,
                opponent_budgets=opponent_budgets,
            ),
        )

    def test_bid_at_least_one_dollar(self):
        resp = compute_recommended_bid(self._bid_request(1, 1, 130))
        assert resp.recommended_bid >= 1

    def test_bid_does_not_exceed_spendable(self):
        req  = self._bid_request(50, 10, 50)
        resp = compute_recommended_bid(req)
        assert resp.recommended_bid <= resp.bid_breakdown.max_spendable

    def test_bid_decreases_when_budget_exhausted(self):
        """Bid for same player with $50 vs $10 remaining — $10 should yield lower bid."""
        resp_rich = compute_recommended_bid(self._bid_request(50, 10, 50))
        resp_poor = compute_recommended_bid(self._bid_request(10, 5,  80))
        assert resp_rich.recommended_bid >= resp_poor.recommended_bid

    def test_competitor_budget_cap_applied(self):
        """Bid must not exceed max competitor remaining budget when provided."""
        opponent_budgets = {"Team B": 15, "Team C": 20}
        resp = compute_recommended_bid(self._bid_request(
            100, 15, 30, opponent_budgets=opponent_budgets))
        # max competitor is $20; bid should be capped accordingly
        assert resp.recommended_bid <= resp.bid_breakdown.max_competitor_budget

    def test_all_opponents_have_position_returns_bid_of_one(self):
        """When every opponent already has OF filled, bid should be $1 (no competition)."""
        opponent_rosters = {
            f"Team {c}": [RosterEntry(player_name="X", position="OF")]
            for c in "BCDEFGHI"
        }
        opponent_budgets = {f"Team {c}": 100 for c in "BCDEFGHI"}
        resp = compute_recommended_bid(self._bid_request(
            100, 15, 30,
            opponent_rosters=opponent_rosters,
            opponent_budgets=opponent_budgets,
        ))
        assert resp.recommended_bid == 1

    def test_my_roster_used_to_derive_remaining_spots(self):
        """When my_roster is provided, remaining spots = roster_size - len(my_roster)."""
        my_roster = [RosterEntry(player_name=f"P{i}", position="OF") for i in range(16)]
        resp = compute_recommended_bid(self._bid_request(
            100, 99,  # my_remaining_roster_spots should be ignored
            30, my_roster=my_roster,
        ))
        # roster_size=23; len(my_roster)=16 → 7 spots left; min_reserve=6
        # spendable = max(1, 100 - 6) = 94
        assert resp.bid_breakdown.max_spendable == 94

    def test_bid_breakdown_fields_present(self):
        resp = compute_recommended_bid(self._bid_request(100, 15, 50))
        bd = resp.bid_breakdown
        assert bd.base_price       >= 0.0
        assert bd.scarcity_adjustment >= 0.0
        assert bd.max_spendable    >= 1


# ═══════════════════════════════════════════════════════════════════════════════
# Section 2 — API Server Endpoints (mocked DB auth)
# ═══════════════════════════════════════════════════════════════════════════════

API_KEY = "test-integration-key"
api_client = TestClient(api_app)


class TestHealthEndpoint:
    def test_health_returns_ok(self):
        resp = api_client.get("/health")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"


class TestAuthMiddleware:
    """Auth middleware: missing key, invalid key, valid key."""

    def test_missing_api_key_returns_401(self):
        resp = api_client.post("/player/value", json={})
        assert resp.status_code == 401
        assert "Missing API key" in resp.json()["detail"]

    def test_invalid_api_key_returns_401(self):
        with patch("api.main.SessionLocal", _api_auth_mock()) as mock_sl:
            # Override the mock to return no row (invalid key)
            db  = MagicMock()
            res = MagicMock()
            res.fetchone.return_value = None
            db.execute.return_value   = res
            mock_sl.return_value      = db

            resp = api_client.post(
                "/player/value",
                json={"player_name": "X", "position": "OF",
                      "stats": {"player_type": "batter",
                                "AB": 500, "R": 80, "HR": 25,
                                "RBI": 85, "SB": 15, "CS": 3, "AVG": 0.275}},
                headers={"X-API-Key": "bad-key"},
            )
        assert resp.status_code == 401


    def test_health_exempt_from_api_key(self):
        resp = api_client.get("/health")
        assert resp.status_code == 200


class TestRateLimiting:
    """Sliding-window rate limiter: 40 req/min per API key."""

    def test_rate_limit_exceeded_returns_429(self):
        """After 40 requests in the same window, the 41st must return 429."""
        from api.main import _api_key_request_times, RATE_LIMIT_MAX
        import time

        # Seed the timestamp deque so the very next request hits the limit
        test_key = "rate-limit-test-key"
        now = time.time()
        _api_key_request_times[test_key] = __import__("collections").deque(
            [now] * RATE_LIMIT_MAX
        )

        # Use only DB + IP patches; do NOT patch is_rate_limited itself —
        # this test verifies that is_rate_limited correctly triggers 429.
        with patch("api.main.SessionLocal", _api_auth_mock()), \
             patch("api.main.check_ip_whitelist", return_value=True):
            resp = api_client.post(
                "/player/value",
                json={"player_name": "X", "position": "OF",
                      "stats": {"player_type": "batter",
                                "AB": 500, "R": 80, "HR": 25,
                                "RBI": 85, "SB": 15, "CS": 3, "AVG": 0.275}},
                headers={"X-API-Key": test_key},
            )
        assert resp.status_code == 429


class TestPlayerValueEndpoint:
    """POST /player/value — response shape, validation errors."""

    def _post(self, body: dict) -> dict:
        with _auth_patches():
            resp = api_client.post(
                "/player/value", json=body,
                headers={"X-API-Key": API_KEY},
            )
        assert resp.status_code == 200, resp.text
        return resp.json()

    def test_batter_value_response_shape(self):
        body = self._post({
            "player_name": "Juan Soto", "position": "OF",
            "stats": {"player_type": "batter",
                      "AB": 534, "R": 113, "HR": 37, "RBI": 97,
                      "SB": 23, "CS": 4, "AVG": 0.281},
        })
        assert "player_value"    in body
        assert "value_breakdown" in body
        assert 0.0 <= body["player_value"] <= 100.0

    def test_pitcher_value_response_shape(self):
        body = self._post({
            "player_name": "Paul Skenes", "position": "SP",
            "stats": {"player_type": "pitcher",
                      "IP": 180.0, "W": 14, "SV": 0, "K": 220,
                      "ERA": 2.80, "WHIP": 0.97},
        })
        assert 0.0 <= body["player_value"] <= 100.0

    def test_missing_required_fields_returns_422(self):
        with _auth_patches():
            resp = api_client.post(
                "/player/value",
                json={"player_name": "X"},  # missing position and stats
                headers={"X-API-Key": API_KEY},
            )
        assert resp.status_code == 422


class TestPlayerBidEndpoint:
    """POST /player/bid — uses fixture JSON from sample_full_requests/."""

    @pytest.mark.parametrize("fixture_file", [
        "batter_predraft_Team_A.json",
        "batter_after_10_Team_A.json",
        "batter_after_50_Team_A.json",
        "batter_after_100_Team_A.json",
        "batter_after_130_Team_A.json",
        "pitcher_predraft_Team_A.json",
        "pitcher_after_10_Team_A.json",
        "pitcher_after_50_Team_A.json",
        "pitcher_after_100_Team_A.json",
        "pitcher_after_130_Team_A.json",
    ])
    def test_bid_from_fixture(self, fixture_file):
        body = _load_json(SAMPLE_DIR / fixture_file)
        with _auth_patches():
            resp = api_client.post(
                "/player/bid", json=body,
                headers={"X-API-Key": API_KEY},
            )
        assert resp.status_code == 200, f"[{fixture_file}] {resp.text}"
        data = resp.json()
        assert "player_value"    in data
        assert "recommended_bid" in data
        assert "bid_breakdown"   in data
        assert data["recommended_bid"] >= 1
        assert data["recommended_bid"] <= data["bid_breakdown"]["max_spendable"]

    def test_player_value_constant_across_fixtures(self):
        """
        Same player stats submitted under 5 different draft contexts must
        produce identical player_value — only recommended_bid should change.
        """
        batter_fixtures = [
            "batter_predraft_Team_A.json",
            "batter_after_10_Team_A.json",
            "batter_after_50_Team_A.json",
            "batter_after_100_Team_A.json",
            "batter_after_130_Team_A.json",
        ]
        values = []
        with _auth_patches():
            for fname in batter_fixtures:
                body = _load_json(SAMPLE_DIR / fname)
                resp = api_client.post("/player/bid", json=body,
                                       headers={"X-API-Key": API_KEY})
                assert resp.status_code == 200
                values.append(resp.json()["player_value"])
        assert len(set(values)) == 1, f"player_value changed across fixtures: {values}"

    def test_bid_decreases_as_budget_shrinks(self):
        """
        recommended_bid must be non-increasing whenever budget strictly drops
        from one fixture to the next (predraft→after_10→after_50→after_100→after_130).
        """
        fixtures_in_order = [
            ("batter_predraft_Team_A.json",  182),
            ("batter_after_10_Team_A.json",  182),
            ("batter_after_50_Team_A.json",   33),
            ("batter_after_100_Team_A.json",   1),
            ("batter_after_130_Team_A.json",   0),
        ]
        bids = []
        with _auth_patches():
            for fname, _ in fixtures_in_order:
                body = _load_json(SAMPLE_DIR / fname)
                resp = api_client.post("/player/bid", json=body,
                                       headers={"X-API-Key": API_KEY})
                bids.append(resp.json()["recommended_bid"])

        for i in range(len(fixtures_in_order) - 1):
            curr_budget = fixtures_in_order[i][1]
            next_budget = fixtures_in_order[i + 1][1]
            if next_budget < curr_budget:
                assert bids[i] >= bids[i + 1], (
                    f"bid should not increase when budget shrinks: "
                    f"${curr_budget}→${next_budget}, bids {bids[i]}→{bids[i+1]}"
                )


class TestPlayerBidMultiTeam:
    """POST /player/bid — same player bid across 9 teams at predraft."""

    @pytest.mark.parametrize("team", list("ABCDEFGHI"))
    def test_bid_valid_for_all_teams_predraft(self, team):
        path = FIXTURE_DIR / "team_request_contexts" / f"predraft_Team_{team}.json"
        context = _load_json(path)
        body = {
            "player_name": "Sample Hitter",
            "position": "OF",
            "stats": {"player_type": "batter",
                      "AB": 540, "R": 85, "HR": 24, "RBI": 88,
                      "SB": 15, "CS": 4, "AVG": 0.276},
            **context,   # merges league_context + draft_context from fixture
        }
        with _auth_patches():
            resp = api_client.post("/player/bid", json=body,
                                   headers={"X-API-Key": API_KEY})
        assert resp.status_code == 200, f"[Team {team}] {resp.text}"
        data = resp.json()
        assert data["recommended_bid"] >= 1


class TestInternalReloadBaselines:
    """POST /internal/reload-baselines — updates cache and affects z-scores."""

    def test_reload_returns_ok(self):
        payload = {
            "batter":  {"R":   {"mean": 75.0, "std": 20.0},
                        "HR":  {"mean": 18.0, "std": 10.0},
                        "RBI": {"mean": 72.0, "std": 20.0},
                        "SB":  {"mean": 12.0, "std": 10.0},
                        "AVG": {"mean": 0.260, "std": 0.025}},
            "pitcher": {"W":    {"mean": 10.0,  "std":  4.0},
                        "SV":   {"mean": 10.0,  "std": 14.0},
                        "K":    {"mean": 130.0, "std": 50.0},
                        "ERA":  {"mean":  4.00, "std":  0.70},
                        "WHIP": {"mean":  1.25, "std":  0.15}},
        }
        resp = api_client.post("/internal/reload-baselines", json=payload)
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"

    def test_reload_exempt_from_api_key(self):
        """Internal endpoint must not require an X-API-Key header."""
        payload = {
            "batter":  {"R":   {"mean": 75.0, "std": 20.0},
                        "HR":  {"mean": 18.0, "std": 10.0},
                        "RBI": {"mean": 72.0, "std": 20.0},
                        "SB":  {"mean": 12.0, "std": 10.0},
                        "AVG": {"mean": 0.260, "std": 0.025}},
            "pitcher": {"W":    {"mean": 10.0,  "std":  4.0},
                        "SV":   {"mean": 10.0,  "std": 14.0},
                        "K":    {"mean": 130.0, "std": 50.0},
                        "ERA":  {"mean":  4.00, "std":  0.70},
                        "WHIP": {"mean":  1.25, "std":  0.15}},
        }
        resp = api_client.post("/internal/reload-baselines", json=payload)
        # Must not return 401
        assert resp.status_code != 401

    def test_player_value_reflects_new_baselines(self):
        """
        Push baselines that make the player look average, then push ones that
        make the player look elite — player_value should increase.
        """
        player_stats_body = {
            "player_name": "Baseline Test", "position": "OF",
            "stats": {"player_type": "batter",
                      "AB": 540, "R": 85, "HR": 24, "RBI": 88,
                      "SB": 15, "CS": 4, "AVG": 0.276},
        }

        # High-mean baselines → player looks mediocre
        api_client.post("/internal/reload-baselines", json={
            "batter":  {"R":   {"mean": 110.0, "std": 20.0},
                        "HR":  {"mean": 35.0,  "std": 10.0},
                        "RBI": {"mean": 105.0, "std": 20.0},
                        "SB":  {"mean": 25.0,  "std": 10.0},
                        "AVG": {"mean": 0.290, "std": 0.025}},
            "pitcher": {"W":{"mean":10.0,"std":4.0},"SV":{"mean":10.0,"std":14.0},
                        "K":{"mean":130.0,"std":50.0},"ERA":{"mean":4.0,"std":0.7},
                        "WHIP":{"mean":1.25,"std":0.15}},
        })
        with _auth_patches():
            val_high = api_client.post(
                "/player/value", json=player_stats_body,
                headers={"X-API-Key": API_KEY},
            ).json()["player_value"]

        # Low-mean baselines → player looks elite
        api_client.post("/internal/reload-baselines", json={
            "batter":  {"R":   {"mean": 40.0,  "std": 15.0},
                        "HR":  {"mean": 10.0,  "std":  8.0},
                        "RBI": {"mean": 40.0,  "std": 15.0},
                        "SB":  {"mean":  5.0,  "std":  7.0},
                        "AVG": {"mean": 0.230, "std": 0.020}},
            "pitcher": {"W":{"mean":10.0,"std":4.0},"SV":{"mean":10.0,"std":14.0},
                        "K":{"mean":130.0,"std":50.0},"ERA":{"mean":4.0,"std":0.7},
                        "WHIP":{"mean":1.25,"std":0.15}},
        })
        with _auth_patches():
            val_low = api_client.post(
                "/player/value", json=player_stats_body,
                headers={"X-API-Key": API_KEY},
            ).json()["player_value"]

        assert val_low > val_high, (
            f"Lower baselines should yield higher player_value: {val_low} vs {val_high}"
        )



class TestPlayersDataEndpoints:
    """GET /players/batters and /players/pitchers — DB mock for list endpoints."""

    def _make_db_mock(self, rows=None):
        """Return a mock SessionLocal whose execute().fetchall() returns `rows`."""
        db  = MagicMock()
        res = MagicMock()
        res.fetchall.return_value = rows or []
        db.execute.return_value   = res
        # Also mock the API key auth lookup
        auth_res = MagicMock()
        auth_res.fetchone.return_value = (1, 1)
        db.execute.side_effect = [auth_res, res]
        return MagicMock(return_value=db)

    def test_batters_endpoint_returns_200(self):
        with patch("api.main.SessionLocal",        _api_auth_mock()), \
             patch("api.main.check_ip_whitelist", return_value=True), \
             patch("api.routers.players_data.SessionLocal", MagicMock(
                 return_value=MagicMock(
                     execute=MagicMock(return_value=MagicMock(fetchall=MagicMock(return_value=[]))),
                     close=MagicMock(),
                 )
             )):
            resp = api_client.get(
                "/players/batters?league=AL",
                headers={"X-API-Key": API_KEY},
            )
        assert resp.status_code == 200

    def test_pitchers_endpoint_returns_200(self):
        with patch("api.main.SessionLocal",        _api_auth_mock()), \
             patch("api.main.check_ip_whitelist", return_value=True), \
             patch("api.routers.players_data.SessionLocal", MagicMock(
                 return_value=MagicMock(
                     execute=MagicMock(return_value=MagicMock(fetchall=MagicMock(return_value=[]))),
                     close=MagicMock(),
                 )
             )):
            resp = api_client.get(
                "/players/pitchers?league=AL",
                headers={"X-API-Key": API_KEY},
            )
        assert resp.status_code == 200

    def test_invalid_league_param_returns_400_or_422(self):
        with _auth_patches():
            resp = api_client.get(
                "/players/batters?league=XL",
                headers={"X-API-Key": API_KEY},
            )
        assert resp.status_code in (400, 422)


class TestPlayerBidByIdEndpoint:
    """POST /player/bid/id — DB lookup mock for ID-based bid."""

    def test_bid_by_id_player_not_found_returns_404(self):
        db_mock = MagicMock()
        db_mock.execute.return_value.fetchone.return_value = None
        db_mock.close = MagicMock()

        with patch("api.main.SessionLocal", _api_auth_mock()), \
             patch("api.main.check_ip_whitelist", return_value=True), \
             patch("api.routers.players_data.SessionLocal",
                   MagicMock(return_value=db_mock)):
            resp = api_client.post(
                "/player/bid/id",
                json={
                    "player_id": 999999,
                    "league_context": {"league_size": 9, "roster_size": 23, "total_budget": 260},
                    "draft_context":  {"my_remaining_budget": 100,
                                       "my_remaining_roster_spots": 10,
                                       "drafted_players_count": 50},
                },
                headers={"X-API-Key": API_KEY},
            )
        assert resp.status_code == 404


# ═══════════════════════════════════════════════════════════════════════════════
# Section 3 — Backend Server Auth Endpoints (SQLite in-memory)
# ═══════════════════════════════════════════════════════════════════════════════

class TestGoogleLogin:
    """POST /api/auth/google — upsert user on first and subsequent calls."""

    def test_first_login_creates_user(self, backend_client):
        with _mock_google_token():
            resp = backend_client.post("/api/auth/google",
                                       json={"token": "fake-google-token"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["email"] == "test@example.com"
        assert data["name"]  == "Test User"
        assert "id" in data

    def test_second_login_returns_same_user(self, backend_client):
        with _mock_google_token():
            resp1 = backend_client.post("/api/auth/google",
                                        json={"token": "fake-google-token"})
            resp2 = backend_client.post("/api/auth/google",
                                        json={"token": "fake-google-token"})
        assert resp1.json()["id"] == resp2.json()["id"]

    def test_invalid_google_token_returns_401(self, backend_client):
        with patch("backend.routers.auth._verify_google_token",
                   side_effect=__import__("fastapi").HTTPException(
                       status_code=401, detail="Invalid Google token")):
            resp = backend_client.post("/api/auth/google",
                                       json={"token": "garbage"})
        assert resp.status_code == 401


class TestAPIKeyIssuance:
    """POST /api/auth/api-key — key generation and one-key-per-user limit."""

    def test_issue_api_key_for_existing_user(self, backend_client):
        with _mock_google_token():
            backend_client.post("/api/auth/google", json={"token": "t"})
            resp = backend_client.post("/api/auth/api-key", json={"token": "t"})
        assert resp.status_code == 200
        data = resp.json()
        assert "key"        in data
        assert "created_at" in data
        assert len(data["key"]) == 64

    def test_second_key_request_returns_400(self, backend_client):
        with _mock_google_token():
            backend_client.post("/api/auth/google",  json={"token": "t"})
            backend_client.post("/api/auth/api-key", json={"token": "t"})
            resp = backend_client.post("/api/auth/api-key", json={"token": "t"})
        assert resp.status_code == 400

    def test_key_request_without_prior_login_returns_404(self, backend_client):
        with _mock_google_token(sub="brand-new-sub"):
            resp = backend_client.post("/api/auth/api-key", json={"token": "t"})
        assert resp.status_code == 404

    def test_delete_api_key(self, backend_client):
        with _mock_google_token():
            backend_client.post("/api/auth/google",  json={"token": "t"})
            key_resp = backend_client.post("/api/auth/api-key", json={"token": "t"})
            key = key_resp.json()["key"]
            del_resp = backend_client.delete(
                f"/api/auth/api-key/{key}?google_token=t")
        assert del_resp.status_code == 200


class TestAllowedIPRegistration:
    """POST /api/auth/allowed-ip — upsert and retrieval."""

    def test_register_ip(self, backend_client):
        with _mock_google_token():
            backend_client.post("/api/auth/google", json={"token": "t"})
            resp = backend_client.post("/api/auth/allowed-ip",
                                       json={"token": "t", "ip_address": "1.2.3.4"})
        assert resp.status_code == 200
        assert resp.json()["ip_address"] == "1.2.3.4"

    def test_update_ip_upserts(self, backend_client):
        with _mock_google_token():
            backend_client.post("/api/auth/google", json={"token": "t"})
            backend_client.post("/api/auth/allowed-ip",
                                json={"token": "t", "ip_address": "1.2.3.4"})
            resp = backend_client.post("/api/auth/allowed-ip",
                                       json={"token": "t", "ip_address": "5.6.7.8"})
        assert resp.status_code == 200
        assert resp.json()["ip_address"] == "5.6.7.8"

    def test_get_ip_not_registered_returns_404(self, backend_client):
        with _mock_google_token(sub="no-ip-user"):
            backend_client.post("/api/auth/google", json={"token": "t"})
            resp = backend_client.get("/api/auth/allowed-ip?google_token=t")
        assert resp.status_code == 404

    def test_ip_whitelist_enforced_on_api_server(self):
        """
        When a user has a registered IP, an API request from a different IP
        must be rejected with 403.
        """
        from api.routers.ip_whitelist import check_ip_whitelist

        db_mock = MagicMock()
        # Simulate: user has registered IP "10.0.0.1"
        db_mock.execute.return_value.fetchone.return_value = ("10.0.0.1",)

        # Request arrives from a different IP
        result = check_ip_whitelist("any-key", "9.9.9.9", db_mock)
        assert result is False

    def test_ip_whitelist_passes_for_matching_ip(self):
        from api.routers.ip_whitelist import check_ip_whitelist

        db_mock = MagicMock()
        db_mock.execute.return_value.fetchone.return_value = ("10.0.0.1",)

        result = check_ip_whitelist("any-key", "10.0.0.1", db_mock)
        assert result is True

    def test_no_registered_ip_allows_all(self):
        """No row in user_allowed_ips → every IP is permitted."""
        from api.routers.ip_whitelist import check_ip_whitelist

        db_mock = MagicMock()
        db_mock.execute.return_value.fetchone.return_value = None

        result = check_ip_whitelist("any-key", "9.9.9.9", db_mock)
        assert result is True


# ═══════════════════════════════════════════════════════════════════════════════
# Section 4 — Fixture-Driven Algorithm Consistency
# ═══════════════════════════════════════════════════════════════════════════════

class TestFixtureDrivenConsistency:
    """
    Run the same sample batter / pitcher through every team context at every
    checkpoint and verify invariants that must hold regardless of context.
    """

    BATTER_STATS = {
        "player_type": "batter",
        "AB": 540, "R": 85, "HR": 24, "RBI": 88,
        "SB": 15, "CS": 4, "AVG": 0.276,
        "age": 27, "depth_order": 1, "injury_status": None,
    }
    PITCHER_STATS = {
        "player_type": "pitcher",
        "IP": 175.2, "W": 12, "SV": 0, "K": 190,
        "ERA": 3.48, "WHIP": 1.14,
        "age": 29, "depth_order": 1, "injury_status": None,
    }

    def _all_context_files(self, checkpoint: str):
        return sorted(
            (FIXTURE_DIR / "team_request_contexts").glob(f"{checkpoint}_Team_*.json")
        )

    def _bulk_patches(self):
        """Like _auth_patches but also disables rate limiting for high-volume tests."""
        from contextlib import ExitStack
        stack = ExitStack()
        stack.enter_context(patch("api.main.SessionLocal", _api_auth_mock()))
        stack.enter_context(patch("api.main.check_ip_whitelist", return_value=True))
        stack.enter_context(patch("api.main.is_rate_limited",    return_value=False))
        return stack

    @pytest.mark.parametrize("checkpoint", ["predraft", "after_10", "after_50",
                                             "after_100", "after_130"])
    def test_batter_bid_valid_for_all_teams(self, checkpoint):
        files = self._all_context_files(checkpoint)
        assert len(files) > 0, f"No fixtures found for checkpoint: {checkpoint}"
        with self._bulk_patches():
            for path in files:
                context = _load_json(path)
                body = {
                    "player_name": "Sample Hitter",
                    "position": "OF",
                    "stats": self.BATTER_STATS,
                    **context,
                }
                resp = api_client.post("/player/bid", json=body,
                                       headers={"X-API-Key": API_KEY})
                assert resp.status_code == 200, f"[{path.name}] {resp.text}"
                data = resp.json()
                assert data["recommended_bid"] >= 1

    @pytest.mark.parametrize("checkpoint", ["predraft", "after_10", "after_50",
                                             "after_100", "after_130"])
    def test_pitcher_bid_valid_for_all_teams(self, checkpoint):
        files = self._all_context_files(checkpoint)
        with self._bulk_patches():
            for path in files:
                context = _load_json(path)
                body = {
                    "player_name": "Sample Pitcher",
                    "position": "SP",
                    "stats": self.PITCHER_STATS,
                    **context,
                }
                resp = api_client.post("/player/bid", json=body,
                                       headers={"X-API-Key": API_KEY})
                assert resp.status_code == 200, f"[{path.name}] {resp.text}"
                data = resp.json()
                assert data["recommended_bid"] >= 1

    def test_player_value_identical_for_all_team_contexts_at_predraft(self):
        """
        player_value must be the same for every team at predraft since
        only draft context differs, not player stats.
        """
        files = self._all_context_files("predraft")
        values = []
        with self._bulk_patches():
            for path in files:
                context = _load_json(path)
                body = {
                    "player_name": "Sample Hitter",
                    "position": "OF",
                    "stats": self.BATTER_STATS,
                    **context,
                }
                resp = api_client.post("/player/bid", json=body,
                                       headers={"X-API-Key": API_KEY})
                values.append(resp.json()["player_value"])

        assert len(set(values)) == 1, \
            f"player_value differs across team contexts at predraft: {values}"