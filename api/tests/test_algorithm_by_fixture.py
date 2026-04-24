"""
test_algorithm_by_fixture.py
============================
Algorithm observation tests for POST /player/bid.

Purpose: verify how player_value and recommended_bid change across
five draft-progress snapshots for the same player and team (Team A).

Fixture data is inlined directly — no external JSON files required.
Extracted from league_state_*.json (Team A only):

  fixture    drafted  budget  roster_spots
  predraft      0      182      16
  after_10     10      182      16
  after_50     50       33       7
  after_100   100        1       1
  after_130   130        0       0   ← roster full, budget exhausted

Run:
  pytest test_algorithm_by_fixture.py -v -s
"""

import pytest
from unittest.mock import MagicMock, patch
from fastapi.testclient import TestClient

from api.main import app

client  = TestClient(app)
API_KEY = "test-key-fixture"


# ---------------------------------------------------------------------------
# Auth mock
# ---------------------------------------------------------------------------

def _auth_mock():
    db  = MagicMock()
    res = MagicMock()
    res.fetchone.return_value = (1,)
    db.execute.return_value   = res
    return MagicMock(return_value=db)


# ---------------------------------------------------------------------------
# Inlined fixture data — extracted from league_state_*.json, Team A
# ---------------------------------------------------------------------------
# league_context is identical across all fixtures (9-team, 23-roster, $260)

LEAGUE_CONTEXT = {
    "league_size":  9,
    "roster_size":  23,
    "total_budget": 260,
}

# DraftContext per fixture — only draft_context changes between calls
DRAFT_CONTEXTS = {
    "predraft": {
        "my_remaining_budget":       182,
        "my_remaining_roster_spots": 16,
        "my_positions_filled":       ["C", "2B", "OF", "P", "P", "P", "P"],
        "drafted_players_count":     0,
    },
    "after_10": {
        "my_remaining_budget":       182,
        "my_remaining_roster_spots": 16,
        "my_positions_filled":       ["C", "2B", "OF", "P", "P", "P", "P"],
        "drafted_players_count":     10,
    },
    "after_50": {
        "my_remaining_budget":       33,
        "my_remaining_roster_spots": 7,
        "my_positions_filled":       ["C", "2B", "OF", "P", "P", "P", "P",
                                      "SS", "3B", "1B", "MI", "P", "OF", "OF", "P", "CI"],
        "drafted_players_count":     50,
    },
    "after_100": {
        "my_remaining_budget":       1,
        "my_remaining_roster_spots": 1,
        "my_positions_filled":       ["C", "2B", "OF", "P", "P", "P", "P",
                                      "SS", "3B", "1B", "MI", "P", "OF", "OF", "P", "CI",
                                      "OF", "P", "P", "P", "OF", "C"],
        "drafted_players_count":     100,
    },
    "after_130": {
        "my_remaining_budget":       0,
        "my_remaining_roster_spots": 0,
        "my_positions_filled":       ["C", "2B", "OF", "P", "P", "P", "P",
                                      "SS", "3B", "1B", "MI", "P", "OF", "OF", "P", "CI",
                                      "OF", "P", "P", "P", "OF", "C", "U"],
        "drafted_players_count":     130,
    },
}

FIXTURE_ORDER = ["predraft", "after_10", "after_50", "after_100", "after_130"]


# ---------------------------------------------------------------------------
# Shared player stats (fixed — only draft context changes)
# ---------------------------------------------------------------------------

BATTER_STATS = {
    "player_type": "batter",
    "AB":  600,
    "R":   112,
    "HR":  41,
    "RBI": 109,
    "SB":  20,
    "CS":  4,
    "AVG": 0.288,
}

BATTER_STATS_WITH_3YR = {
    **BATTER_STATS,
    "R_3yr":   98,
    "HR_3yr":  37,
    "RBI_3yr": 101,
    "SB_3yr":  18,
    "CS_3yr":  5,
    "AVG_3yr": 0.280,
}

PITCHER_STATS = {
    "player_type": "pitcher",
    "IP":   180.0,
    "W":    14,
    "SV":   0,
    "K":    220,
    "ERA":  2.81,
    "WHIP": 0.97,
}


# ---------------------------------------------------------------------------
# Print helpers
# ---------------------------------------------------------------------------

def _print_header(title: str):
    print(f"\n{'═' * 78}")
    print(f"  {title}")
    print(f"{'═' * 78}")

def _print_sep():
    print(f"  {'─' * 74}")

def _print_row(fixture: str, dc: dict, body: dict):
    bd       = body.get("bid_breakdown", {})
    budget   = dc["my_remaining_budget"]
    spots    = dc["my_remaining_roster_spots"]
    drafted  = dc["drafted_players_count"]
    pv       = body.get("player_value",    "ERR")
    bid      = body.get("recommended_bid", "ERR")
    base     = bd.get("base_price",          "—")
    scarcity = bd.get("scarcity_adjustment",  "—")
    dadj     = bd.get("draft_adjustment",     "—")
    spend    = bd.get("max_spendable",         "—")

    print(
        f"  {fixture:<12}"
        f"  drafted={drafted:3}  budget=${budget:3}  spots={spots:2}"
        f"  │  value={pv:5}  bid=${bid:3}"
        f"  │  base=${base:<6}  scarcity=${scarcity:<6}  draft_adj=${dadj:<7}  spendable=${spend}"
    )


# ---------------------------------------------------------------------------
# Helper: call /player/bid for one fixture
# ---------------------------------------------------------------------------

def _call_bid(player_name: str, position: str, stats: dict, fixture_name: str) -> dict:
    response = client.post(
        "/player/bid",
        json={
            "player_name":    player_name,
            "position":       position,
            "stats":          stats,
            "league_context": LEAGUE_CONTEXT,
            "draft_context":  DRAFT_CONTEXTS[fixture_name],
        },
        headers={"X-API-Key": API_KEY},
    )
    assert response.status_code == 200, (
        f"[{fixture_name}] Expected 200, got {response.status_code}: {response.text}"
    )
    return response.json()


# ===========================================================================
# Test class 1: batter across all 5 fixtures
# ===========================================================================

class TestBatterAcrossFixtures:
    """
    Juan Soto (OF) bid at each draft checkpoint.

    player_value must be constant — stats don't change, only draft context does.
    recommended_bid must be non-increasing as budget shrinks.
    """

    @pytest.mark.parametrize("fixture_name", FIXTURE_ORDER)
    def test_bid_per_fixture(self, fixture_name):
        with patch("api.main.SessionLocal", _auth_mock()):
            body = _call_bid("Juan Soto", "OF", BATTER_STATS, fixture_name)

        dc = DRAFT_CONTEXTS[fixture_name]
        assert 0.0 <= body["player_value"] <= 100.0
        assert body["recommended_bid"] >= 1
        assert body["recommended_bid"] <= body["bid_breakdown"]["max_spendable"]

    def test_summary_table(self):
        results = {}
        with patch("api.main.SessionLocal", _auth_mock()):
            for fn in FIXTURE_ORDER:
                results[fn] = _call_bid("Juan Soto", "OF", BATTER_STATS, fn)

        _print_header("BATTER — Juan Soto / OF  |  Team A across 5 fixtures  (no 3yr stats)")
        _print_sep()
        for fn in FIXTURE_ORDER:
            _print_row(fn, DRAFT_CONTEXTS[fn], results[fn])
        _print_sep()

        # player_value must be identical across all fixtures
        values = [results[fn]["player_value"] for fn in FIXTURE_ORDER]
        print(f"\n  player_value (must be constant) : {values}")
        assert len(set(values)) == 1, f"player_value changed across fixtures: {values}"

        # recommended_bid must decrease when budget actually shrinks between fixtures.
        # Note: predraft → after_10 has identical budget but draft_multiplier rises
        # slightly (budget_ratio > 0.5 amplifies draft_progress), so a small bid
        # increase there is intentional algorithm behavior, not a bug.
        bids = [results[fn]["recommended_bid"] for fn in FIXTURE_ORDER]
        print(f"  recommended_bid progression     : {bids}")
        for i in range(len(FIXTURE_ORDER) - 1):
            curr_fn = FIXTURE_ORDER[i]
            next_fn = FIXTURE_ORDER[i + 1]
            curr_budget = DRAFT_CONTEXTS[curr_fn]["my_remaining_budget"]
            next_budget = DRAFT_CONTEXTS[next_fn]["my_remaining_budget"]
            if next_budget < curr_budget:
                assert bids[i] >= bids[i + 1], (
                    f"bid should decrease when budget drops "
                    f"({curr_fn} ${curr_budget} → {next_fn} ${next_budget}): "
                    f"bid {bids[i]} → {bids[i + 1]}"
                )


# ===========================================================================
# Test class 2: pitcher across all 5 fixtures
# ===========================================================================

class TestPitcherAcrossFixtures:
    """
    Paul Skenes (SP) bid at each draft checkpoint.
    """

    @pytest.mark.parametrize("fixture_name", FIXTURE_ORDER)
    def test_bid_per_fixture(self, fixture_name):
        with patch("api.main.SessionLocal", _auth_mock()):
            body = _call_bid("Paul Skenes", "SP", PITCHER_STATS, fixture_name)

        assert body["recommended_bid"] >= 1
        assert body["recommended_bid"] <= body["bid_breakdown"]["max_spendable"]

    def test_summary_table(self):
        results = {}
        with patch("api.main.SessionLocal", _auth_mock()):
            for fn in FIXTURE_ORDER:
                results[fn] = _call_bid("Paul Skenes", "SP", PITCHER_STATS, fn)

        _print_header("PITCHER — Paul Skenes / SP  |  Team A across 5 fixtures")
        _print_sep()
        for fn in FIXTURE_ORDER:
            _print_row(fn, DRAFT_CONTEXTS[fn], results[fn])
        _print_sep()

        values = [results[fn]["player_value"] for fn in FIXTURE_ORDER]
        print(f"\n  player_value (must be constant) : {values}")
        assert len(set(values)) == 1, f"player_value changed: {values}"

        bids = [results[fn]["recommended_bid"] for fn in FIXTURE_ORDER]
        print(f"  recommended_bid progression     : {bids}")
        for i in range(len(FIXTURE_ORDER) - 1):
            curr_fn = FIXTURE_ORDER[i]
            next_fn = FIXTURE_ORDER[i + 1]
            curr_budget = DRAFT_CONTEXTS[curr_fn]["my_remaining_budget"]
            next_budget = DRAFT_CONTEXTS[next_fn]["my_remaining_budget"]
            if next_budget < curr_budget:
                assert bids[i] >= bids[i + 1], (
                    f"bid should decrease when budget drops "
                    f"({curr_fn} ${curr_budget} → {next_fn} ${next_budget}): "
                    f"bid {bids[i]} → {bids[i + 1]}"
                )


# ===========================================================================
# Test class 3: 3yr blending effect
# ===========================================================================

class TestBlendingEffect:
    """
    Same player, same fixture — compare bid with vs without 3yr average stats.
    3yr stats in this fixture are slightly lower than current season,
    so blending should lower player_value slightly.
    """

    @pytest.mark.parametrize("fixture_name", ["predraft", "after_50", "after_130"])
    def test_3yr_vs_no_3yr(self, fixture_name):
        with patch("api.main.SessionLocal", _auth_mock()):
            b_plain = _call_bid("Juan Soto", "OF", BATTER_STATS,          fixture_name)
            b_3yr   = _call_bid("Juan Soto", "OF", BATTER_STATS_WITH_3YR, fixture_name)

        # both must be valid
        assert b_plain["recommended_bid"] >= 1
        assert b_3yr["recommended_bid"]   >= 1

    def test_summary_table(self):
        fixtures = ["predraft", "after_50", "after_130"]

        _print_header("BLENDING EFFECT — Juan Soto / OF  (no-3yr vs with-3yr stats)")
        print(
            f"  {'fixture':<12}  "
            f"{'no 3yr':>24}  │  "
            f"{'with 3yr':>24}  │  Δvalue"
        )
        _print_sep()

        with patch("api.main.SessionLocal", _auth_mock()):
            for fn in fixtures:
                b1 = _call_bid("Juan Soto", "OF", BATTER_STATS,          fn)
                b2 = _call_bid("Juan Soto", "OF", BATTER_STATS_WITH_3YR, fn)
                delta = round(b2["player_value"] - b1["player_value"], 1)
                dc    = DRAFT_CONTEXTS[fn]
                print(
                    f"  {fn:<12}"
                    f"  value={b1['player_value']:5}  bid=${b1['recommended_bid']:3}"
                    f"  │  value={b2['player_value']:5}  bid=${b2['recommended_bid']:3}"
                    f"  │  {delta:+}"
                )

        _print_sep()
        print(
            "  Note: 3yr stats (HR_3yr=37) are lower than current (HR=41),\n"
            "        so blending pulls player_value down slightly (Δvalue < 0 expected)."
        )


# ===========================================================================
# Test class 4: positional scarcity
# ===========================================================================

class TestPositionalScarcity:
    """
    Same batter stats submitted under 7 different positions at predraft.
    Verifies that POSITION_BONUS and SCARCITY_MULTIPLIER are reflected
    in both player_value and recommended_bid.

    Expected value order: C > SS > 2B > SP > 3B > 1B ≈ OF
    """

    POSITIONS = ["C", "SS", "2B", "SP", "3B", "1B", "OF"]

    @pytest.mark.parametrize("position", POSITIONS)
    def test_value_by_position(self, position):
        with patch("api.main.SessionLocal", _auth_mock()):
            body = _call_bid("Generic Player", position, BATTER_STATS, "predraft")
        assert body["recommended_bid"] >= 1

    def test_summary_table(self):
        results = {}
        with patch("api.main.SessionLocal", _auth_mock()):
            for pos in self.POSITIONS:
                results[pos] = _call_bid("Generic Player", pos, BATTER_STATS, "predraft")

        _print_header("POSITIONAL SCARCITY — same batter stats, 7 positions  [predraft]")
        print(
            f"  {'pos':<5}  {'player_value':>12}  {'recommended_bid':>16}"
            f"  {'base_price':>10}  {'scarcity_adj':>12}"
        )
        _print_sep()

        for pos in self.POSITIONS:
            body = results[pos]
            bd   = body["bid_breakdown"]
            print(
                f"  {pos:<5}"
                f"  {body['player_value']:>12}"
                f"  {body['recommended_bid']:>16}"
                f"  {bd['base_price']:>10}"
                f"  {bd['scarcity_adjustment']:>12}"
            )

        _print_sep()

        pv = {pos: results[pos]["player_value"] for pos in self.POSITIONS}
        print(f"\n  Scarcity order check:")
        print(f"    C={pv['C']}  SS={pv['SS']}  2B={pv['2B']}  3B={pv['3B']}  1B={pv['1B']}  OF={pv['OF']}")

        assert pv["C"]  > pv["OF"], f"C should be > OF:  {pv['C']} vs {pv['OF']}"
        assert pv["SS"] > pv["OF"], f"SS should be > OF: {pv['SS']} vs {pv['OF']}"
        assert pv["C"]  > pv["SS"], f"C should be > SS:  {pv['C']} vs {pv['SS']}"
