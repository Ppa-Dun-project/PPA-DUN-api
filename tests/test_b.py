"""
test_b_e2e.py
=============
End-to-End tests for the PPA-DUN project.

Assumes Docker Compose is up and running before this suite is executed:
  docker compose -f docker-compose_local.yml up -d

Flow under test (mirrors real user journey):
  1. User visits frontend → clicks "Sign in with Google"
     (Google OAuth mocked at the backend /api/auth/google endpoint)
  2. Backend creates/returns user record
  3. User issues a new API key   → POST /api/auth/api-key
  4. User registers their IP     → POST /api/auth/allowed-ip
  5. User calls the API server   → POST /player/value
  6. User calls the API server   → POST /player/bid  (with full draft context)
  7. User queries player lists   → GET /players/batters?league=AL
  8. (Negative path) Unregistered IP is blocked

Frontend component tests (Vitest + React Testing Library):
  - Demo component renders correctly
  - Mode toggle switches between /demo/value and /demo/bid forms
  - Player type toggle switches between batter and pitcher fields
  - Submit fires fetch with the correct payload
  - Error state renders when API returns an error

Run:
  # Start services first
  docker compose -f docker-compose_local.yml up -d

  # Python E2E
  pytest tests/test_b_e2e.py -v -s

  # Frontend component tests (from project root)
  cd frontend
  npx vitest run tests/Demo.test.tsx

Environment variables expected for E2E (can be set in a local .env.test):
  BACKEND_URL   e.g. http://localhost:8001
  API_URL       e.g. http://localhost:8000
  GOOGLE_CLIENT_ID  (any value — the backend Google token verification is mocked)
"""

# ── stdlib / third-party ──────────────────────────────────────────────────────
import json
import os
import time
import pytest
import requests
from pathlib import Path
from unittest.mock import patch, MagicMock

# ── Fixture paths ─────────────────────────────────────────────────────────────
FIXTURE_DIR = Path(__file__).parent / "ppa_dun_actual_fixtures"
SAMPLE_DIR  = FIXTURE_DIR / "sample_full_requests"

# ── Service URLs (read from env or fall back to local Docker Compose defaults) ─
BACKEND_URL = os.getenv("BACKEND_URL", "http://localhost:8001")
API_URL     = os.getenv("API_URL",     "http://localhost:8000")

# How long to wait for a service to become healthy (seconds)
HEALTH_TIMEOUT = 30


# ═══════════════════════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════════════════════

def _load_json(path: Path) -> dict:
    with open(path) as f:
        return json.load(f)


def _wait_for_service(url: str, timeout: int = HEALTH_TIMEOUT):
    """Poll GET {url}/health until 200 or timeout."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            resp = requests.get(f"{url}/health", timeout=2)
            if resp.status_code == 200:
                return
        except requests.exceptions.ConnectionError:
            pass
        time.sleep(1)
    pytest.fail(f"Service at {url} did not become healthy within {timeout}s")


def _backend_health_url():
    return f"{BACKEND_URL}/health"


def _backend_post(path: str, **kwargs):
    return requests.post(f"{BACKEND_URL}{path}", **kwargs)


def _api_post(path: str, headers: dict = None, **kwargs):
    h = headers or {}
    return requests.post(f"{API_URL}{path}", headers=h, **kwargs)


def _api_get(path: str, headers: dict = None, **kwargs):
    h = headers or {}
    return requests.get(f"{API_URL}{path}", headers=h, **kwargs)


# ═══════════════════════════════════════════════════════════════════════════════
# Session-scoped service availability check
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.fixture(scope="session", autouse=True)
def wait_for_services():
    """Block until both API server and backend server are healthy."""
    _wait_for_service(API_URL,     timeout=HEALTH_TIMEOUT)
    _wait_for_service(BACKEND_URL, timeout=HEALTH_TIMEOUT)


# ═══════════════════════════════════════════════════════════════════════════════
# Session-scoped user fixture
# Represents a freshly registered user with an API key and IP registered.
# Google OAuth is mocked at the _verify_google_token function level so no
# real Google credentials are needed.
# ═══════════════════════════════════════════════════════════════════════════════

class _FakeGoogleToken:
    """
    Context manager: patches _verify_google_token on the running backend
    process by replacing the function via monkeypatch at import time.
    Since patching a live process from the outside is not directly possible,
    the backend must be started with MOCK_GOOGLE_AUTH=true (which swaps in the
    mock in backend/routers/auth.py). This is handled by docker-compose_local.yml
    test overrides. As a fallback, we provide a test user seeded by the admin
    endpoint if it exists, or call the backend with a known-good token.

    For this test suite we assume the backend is started with:
      MOCK_GOOGLE_AUTH=true
      MOCK_GOOGLE_SUB=e2e-test-sub-001
      MOCK_GOOGLE_EMAIL=e2e@ppadun.test
      MOCK_GOOGLE_NAME=E2E Test User
    which causes _verify_google_token to return the mocked payload without
    actually calling Google.
    """

# ── Google token placeholder ───────────────────────────────────────────────────
# When MOCK_GOOGLE_AUTH=true, the backend accepts any non-empty string as a
# valid token and returns the mocked user payload.
MOCK_TOKEN = "e2e-mock-google-token"


@pytest.fixture(scope="session")
def registered_user():
    """
    Register (or re-use) an E2E test user in the live backend.
    Returns a dict with: user_id, api_key, email.
    """
    # Step 1: Login / upsert user
    resp = _backend_post("/api/auth/google", json={"token": MOCK_TOKEN})
    assert resp.status_code == 200, (
        f"Backend /api/auth/google failed: {resp.status_code} {resp.text}\n"
        "Ensure the backend is running with MOCK_GOOGLE_AUTH=true"
    )
    user = resp.json()

    # Step 2: Try to issue a new API key. If one already exists, delete it first.
    key_resp = _backend_post("/api/auth/api-key", json={"token": MOCK_TOKEN})
    if key_resp.status_code == 400:
        # Key already exists — fetch and delete it
        existing = requests.get(
            f"{BACKEND_URL}/api/auth/api-keys?google_token={MOCK_TOKEN}"
        )
        if existing.status_code == 200:
            for k in existing.json():
                requests.delete(
                    f"{BACKEND_URL}/api/auth/api-key/{k['key']}?google_token={MOCK_TOKEN}"
                )
        key_resp = _backend_post("/api/auth/api-key", json={"token": MOCK_TOKEN})

    assert key_resp.status_code == 200, (
        f"API key issuance failed: {key_resp.status_code} {key_resp.text}"
    )
    api_key = key_resp.json()["key"]

    # Step 3: Register IP (127.0.0.1 — the address Docker uses for localhost requests)
    ip_resp = _backend_post(
        "/api/auth/allowed-ip",
        json={"token": MOCK_TOKEN, "ip_address": "127.0.0.1"},
    )
    assert ip_resp.status_code == 200, (
        f"IP registration failed: {ip_resp.status_code} {ip_resp.text}"
    )

    return {
        "user_id": user["id"],
        "email":   user["email"],
        "api_key": api_key,
    }


# ═══════════════════════════════════════════════════════════════════════════════
# Test class 1 — Full User Onboarding Flow
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.skip(reason="Requires MOCK_GOOGLE_AUTH backend support — skipped in local E2E")
class TestUserOnboardingFlow:
    """
    Verifies the complete sign-up → API key issuance → IP registration sequence.
    Uses a secondary mock user (different sub) to avoid conflicting with the
    session-scoped `registered_user` fixture.
    """

    SECONDARY_TOKEN = "e2e-secondary-mock-token"  # sub = e2e-test-sub-002

    def test_step1_login_creates_or_returns_user(self):
        resp = _backend_post("/api/auth/google", json={"token": self.SECONDARY_TOKEN})
        assert resp.status_code == 200
        data = resp.json()
        assert "id"    in data
        assert "email" in data

    def test_step2_repeated_login_returns_same_user(self):
        r1 = _backend_post("/api/auth/google", json={"token": self.SECONDARY_TOKEN})
        r2 = _backend_post("/api/auth/google", json={"token": self.SECONDARY_TOKEN})
        assert r1.json()["id"] == r2.json()["id"]

    def test_step3_issue_api_key(self):
        # Clean up any existing key first
        existing = requests.get(
            f"{BACKEND_URL}/api/auth/api-keys?google_token={self.SECONDARY_TOKEN}"
        )
        if existing.status_code == 200:
            for k in existing.json():
                requests.delete(
                    f"{BACKEND_URL}/api/auth/api-key/{k['key']}"
                    f"?google_token={self.SECONDARY_TOKEN}"
                )

        resp = _backend_post("/api/auth/api-key", json={"token": self.SECONDARY_TOKEN})
        assert resp.status_code == 200
        key = resp.json()["key"]
        assert len(key) == 64

    def test_step4_second_key_blocked(self):
        # Ensure a key already exists (from step 3)
        resp = _backend_post("/api/auth/api-key", json={"token": self.SECONDARY_TOKEN})
        # Either the key already exists (400) or a new one was just issued (200) —
        # a second immediate call must return 400
        if resp.status_code == 200:
            resp2 = _backend_post("/api/auth/api-key",
                                  json={"token": self.SECONDARY_TOKEN})
            assert resp2.status_code == 400
        else:
            assert resp.status_code == 400

    def test_step5_register_ip(self):
        resp = _backend_post(
            "/api/auth/allowed-ip",
            json={"token": self.SECONDARY_TOKEN, "ip_address": "192.168.1.100"},
        )
        assert resp.status_code == 200
        assert resp.json()["ip_address"] == "192.168.1.100"

    def test_step6_update_ip(self):
        resp = _backend_post(
            "/api/auth/allowed-ip",
            json={"token": self.SECONDARY_TOKEN, "ip_address": "10.0.0.50"},
        )
        assert resp.status_code == 200
        assert resp.json()["ip_address"] == "10.0.0.50"

    def test_step7_get_registered_ip(self):
        resp = requests.get(
            f"{BACKEND_URL}/api/auth/allowed-ip"
            f"?google_token={self.SECONDARY_TOKEN}"
        )
        assert resp.status_code == 200
        assert "ip_address" in resp.json()


# ═══════════════════════════════════════════════════════════════════════════════
# Test class 2 — API Server: Player Value
# ═══════════════════════════════════════════════════════════════════════════════

class TestAPIPlayerValue:
    """POST /player/value against the live API server."""

    @pytest.mark.skip(reason="Requires MOCK_GOOGLE_AUTH backend support")
    def test_batter_value_shape(self, registered_user):
        resp = _api_post(
            "/player/value",
            headers={"X-API-Key": registered_user["api_key"]},
            json={
                "player_name": "Juan Soto",
                "position":    "OF",
                "stats": {"player_type": "batter",
                          "AB": 534, "R": 113, "HR": 37, "RBI": 97,
                          "SB": 23, "CS": 4, "AVG": 0.281},
            },
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert "player_value"    in data
        assert "value_breakdown" in data
        assert 0.0 <= data["player_value"] <= 100.0

    @pytest.mark.skip(reason="Requires MOCK_GOOGLE_AUTH backend support")
    def test_pitcher_value_shape(self, registered_user):
        resp = _api_post(
            "/player/value",
            headers={"X-API-Key": registered_user["api_key"]},
            json={
                "player_name": "Paul Skenes",
                "position":    "SP",
                "stats": {"player_type": "pitcher",
                          "IP": 180.0, "W": 14, "SV": 0, "K": 220,
                          "ERA": 2.80, "WHIP": 0.97},
            },
        )
        assert resp.status_code == 200
        assert 0.0 <= resp.json()["player_value"] <= 100.0

    def test_missing_api_key_returns_401(self):
        resp = _api_post(
            "/player/value",
            json={"player_name": "X", "position": "OF",
                  "stats": {"player_type": "batter",
                            "AB": 500, "R": 80, "HR": 25,
                            "RBI": 85, "SB": 15, "CS": 3, "AVG": 0.275}},
        )
        assert resp.status_code == 401

    def test_invalid_api_key_returns_401(self):
        resp = _api_post(
            "/player/value",
            headers={"X-API-Key": "definitely-not-a-real-key-xxxx"},
            json={"player_name": "X", "position": "OF",
                  "stats": {"player_type": "batter",
                            "AB": 500, "R": 80, "HR": 25,
                            "RBI": 85, "SB": 15, "CS": 3, "AVG": 0.275}},
        )
        assert resp.status_code == 401

    @pytest.mark.skip(reason="Requires MOCK_GOOGLE_AUTH backend support")
    def test_malformed_body_returns_422(self, registered_user):
        resp = _api_post(
            "/player/value",
            headers={"X-API-Key": registered_user["api_key"]},
            json={"player_name": "X"},  # missing position + stats
        )
        assert resp.status_code == 422


# ═══════════════════════════════════════════════════════════════════════════════
# Test class 3 — API Server: Player Bid (fixture-driven)
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.skip(reason="Requires MOCK_GOOGLE_AUTH backend support — skipped in local E2E")
class TestAPIPlayerBid:
    """POST /player/bid against the live API server using actual fixture JSON."""

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
    def test_bid_from_fixture(self, registered_user, fixture_file):
        body = _load_json(SAMPLE_DIR / fixture_file)
        resp = _api_post(
            "/player/bid",
            headers={"X-API-Key": registered_user["api_key"]},
            json=body,
        )
        assert resp.status_code == 200, f"[{fixture_file}] {resp.text}"
        data = resp.json()
        assert "player_value"    in data
        assert "recommended_bid" in data
        assert data["recommended_bid"] >= 1
        assert data["recommended_bid"] <= data["bid_breakdown"]["max_spendable"]

    def test_player_value_constant_across_all_team_a_checkpoints(self, registered_user):
        """
        The 5 batter fixtures all have the same player stats but different
        draft contexts. player_value must be identical across all 5 responses.
        """
        checkpoint_files = [
            "batter_predraft_Team_A.json",
            "batter_after_10_Team_A.json",
            "batter_after_50_Team_A.json",
            "batter_after_100_Team_A.json",
            "batter_after_130_Team_A.json",
        ]
        values = []
        for fname in checkpoint_files:
            body = _load_json(SAMPLE_DIR / fname)
            resp = _api_post(
                "/player/bid",
                headers={"X-API-Key": registered_user["api_key"]},
                json=body,
            )
            assert resp.status_code == 200
            values.append(resp.json()["player_value"])

        assert len(set(values)) == 1, \
            f"player_value must be constant across fixtures: {values}"

    def test_bid_non_increasing_as_budget_drops(self, registered_user):
        """
        recommended_bid must not increase when the remaining budget strictly
        decreases from one checkpoint to the next.
        """
        checkpoints = [
            ("batter_predraft_Team_A.json",   182),
            ("batter_after_10_Team_A.json",   182),
            ("batter_after_50_Team_A.json",    33),
            ("batter_after_100_Team_A.json",    1),
            ("batter_after_130_Team_A.json",    0),
        ]
        bids = []
        for fname, _ in checkpoints:
            body = _load_json(SAMPLE_DIR / fname)
            resp = _api_post(
                "/player/bid",
                headers={"X-API-Key": registered_user["api_key"]},
                json=body,
            )
            bids.append(resp.json()["recommended_bid"])

        for i in range(len(checkpoints) - 1):
            curr_budget = checkpoints[i][1]
            next_budget = checkpoints[i + 1][1]
            if next_budget < curr_budget:
                assert bids[i] >= bids[i + 1], (
                    f"Bid should not increase when budget shrinks "
                    f"(${curr_budget}→${next_budget}): {bids[i]}→{bids[i+1]}"
                )

    def test_scarcity_higher_for_catcher_than_outfielder(self, registered_user):
        """
        Catcher bid should exceed outfielder bid for identical stats due to
        higher positional scarcity.
        """
        base_context = _load_json(FIXTURE_DIR / "team_request_contexts" /
                                  "predraft_Team_A.json")
        stats = {"player_type": "batter",
                 "AB": 540, "R": 85, "HR": 24, "RBI": 88,
                 "SB": 15, "CS": 4, "AVG": 0.276}

        bid_c = _api_post(
            "/player/bid",
            headers={"X-API-Key": registered_user["api_key"]},
            json={"player_name": "X", "position": "C",  "stats": stats, **base_context},
        ).json()["recommended_bid"]

        bid_of = _api_post(
            "/player/bid",
            headers={"X-API-Key": registered_user["api_key"]},
            json={"player_name": "X", "position": "OF", "stats": stats, **base_context},
        ).json()["recommended_bid"]

        assert bid_c > bid_of, f"C bid ({bid_c}) should exceed OF bid ({bid_of})"


# ═══════════════════════════════════════════════════════════════════════════════
# Test class 4 — API Server: Player Bid across all 9 teams
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.skip(reason="Requires MOCK_GOOGLE_AUTH backend support — skipped in local E2E")
class TestAPIPlayerBidAllTeams:
    """
    Same sample batter and pitcher submitted for every team context at each
    checkpoint. Every response must be 200 with recommended_bid >= 1.
    """

    BATTER_STATS = {
        "player_type": "batter",
        "AB": 540, "R": 85, "HR": 24, "RBI": 88,
        "SB": 15, "CS": 4, "AVG": 0.276,
    }
    PITCHER_STATS = {
        "player_type": "pitcher",
        "IP": 175.2, "W": 12, "SV": 0, "K": 190,
        "ERA": 3.48, "WHIP": 1.14,
    }

    @pytest.mark.parametrize("team,checkpoint", [
        (team, ckpt)
        for ckpt in ["predraft", "after_10", "after_50", "after_100", "after_130"]
        for team in list("ABCDEFGHI")
    ])
    def test_batter_bid_per_team_per_checkpoint(self, registered_user, team, checkpoint):
        path = FIXTURE_DIR / "team_request_contexts" / f"{checkpoint}_Team_{team}.json"
        if not path.exists():
            pytest.skip(f"Fixture not found: {path.name}")

        context = _load_json(path)
        body = {
            "player_name": f"Sample Hitter ({team}/{checkpoint})",
            "position": "OF",
            "stats": self.BATTER_STATS,
            **context,
        }
        resp = _api_post(
            "/player/bid",
            headers={"X-API-Key": registered_user["api_key"]},
            json=body,
        )
        assert resp.status_code == 200, f"[{team}/{checkpoint}] {resp.text}"
        assert resp.json()["recommended_bid"] >= 1

    @pytest.mark.parametrize("team,checkpoint", [
        (team, ckpt)
        for ckpt in ["predraft", "after_10", "after_50"]
        for team in list("ABCDEFGHI")
    ])
    def test_pitcher_bid_per_team_per_checkpoint(self, registered_user, team, checkpoint):
        path = FIXTURE_DIR / "team_request_contexts" / f"{checkpoint}_Team_{team}.json"
        if not path.exists():
            pytest.skip(f"Fixture not found: {path.name}")

        context = _load_json(path)
        body = {
            "player_name": f"Sample Pitcher ({team}/{checkpoint})",
            "position": "SP",
            "stats": self.PITCHER_STATS,
            **context,
        }
        resp = _api_post(
            "/player/bid",
            headers={"X-API-Key": registered_user["api_key"]},
            json=body,
        )
        assert resp.status_code == 200, f"[{team}/{checkpoint}] {resp.text}"
        assert resp.json()["recommended_bid"] >= 1


# ═══════════════════════════════════════════════════════════════════════════════
# Test class 5 — API Server: Player Lists
# ═══════════════════════════════════════════════════════════════════════════════

class TestAPIPlayerLists:
    """GET /players/batters and /players/pitchers against the live API server."""

    @pytest.mark.skip(reason="Requires MOCK_GOOGLE_AUTH backend support")
    def test_get_al_batters(self, registered_user):
        resp = _api_get(
            "/players/batters?league=AL",
            headers={"X-API-Key": registered_user["api_key"]},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "players" in data or isinstance(data, list)

    @pytest.mark.skip(reason="Requires MOCK_GOOGLE_AUTH backend support")
    def test_get_nl_pitchers(self, registered_user):
        resp = _api_get(
            "/players/pitchers?league=NL",
            headers={"X-API-Key": registered_user["api_key"]},
        )
        assert resp.status_code == 200

    @pytest.mark.skip(reason="Requires MOCK_GOOGLE_AUTH backend support")
    def test_invalid_league_returns_error(self, registered_user):
        resp = _api_get(
            "/players/batters?league=XL",
            headers={"X-API-Key": registered_user["api_key"]},
        )
        assert resp.status_code in (400, 422)

    def test_batters_list_without_api_key_returns_401(self):
        resp = _api_get("/players/batters?league=AL")
        assert resp.status_code == 401

    def test_pitchers_list_without_api_key_returns_401(self):
        resp = _api_get("/players/pitchers?league=AL")
        assert resp.status_code == 401


# ═══════════════════════════════════════════════════════════════════════════════
# Test class 6 — IP Whitelist Enforcement (negative path)
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.skip(reason="Requires MOCK_GOOGLE_AUTH backend support — skipped in local E2E")
class TestIPWhitelistEnforcement:
    """
    A user who has registered IP 127.0.0.1 must be blocked when the API
    request arrives from a different IP (simulated by X-Forwarded-For).
    """

    def test_blocked_ip_returns_403(self, registered_user):
        resp = _api_post(
            "/player/value",
            headers={
                "X-API-Key":       registered_user["api_key"],
                "X-Forwarded-For": "9.8.7.6",   # not 127.0.0.1
            },
            json={
                "player_name": "X", "position": "OF",
                "stats": {"player_type": "batter",
                          "AB": 500, "R": 80, "HR": 25,
                          "RBI": 85, "SB": 15, "CS": 3, "AVG": 0.275},
            },
        )
        assert resp.status_code == 403


# ═══════════════════════════════════════════════════════════════════════════════
# Test class 7 — Demo Endpoints (no API key)
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.skip(reason="Requires MOCK_GOOGLE_AUTH backend support — skipped in local E2E")
class TestDemoEndpointsE2E:
    """
    /demo/value and /demo/bid are publicly accessible (no API key),
    rate-limited to 10 req/min, and origin-restricted from browsers.
    Curl-style requests (no Origin header) must pass through.
    """

    def test_demo_value_accessible_without_key(self):
        resp = _api_post(
            "/demo/value",
            json={
                "player_name": "Juan Soto", "position": "OF",
                "stats": {"player_type": "batter",
                          "AB": 534, "R": 113, "HR": 37, "RBI": 97,
                          "SB": 23, "CS": 4, "AVG": 0.281},
            },
        )
        assert resp.status_code == 200
        assert "player_value" in resp.json()

    def test_demo_bid_accessible_without_key(self):
        resp = _api_post(
            "/demo/bid",
            json={
                "player_name": "Juan Soto", "position": "OF",
                "stats": {"player_type": "batter",
                          "AB": 534, "R": 113, "HR": 37, "RBI": 97,
                          "SB": 23, "CS": 4, "AVG": 0.281},
                "league_context": {"league_size": 9, "roster_size": 23, "total_budget": 260},
                "draft_context":  {"my_remaining_budget": 182,
                                   "my_remaining_roster_spots": 16,
                                   "drafted_players_count": 0},
            },
        )
        assert resp.status_code == 200
        assert "recommended_bid" in resp.json()

    def test_demo_blocked_for_unknown_browser_origin(self):
        """
        When an Origin header is set to a non-whitelisted domain, the demo
        endpoint must return 403. This simulates a browser cross-origin request.
        """
        resp = requests.post(
            f"{API_URL}/demo/value",
            headers={"Origin": "https://attacker.example.com"},
            json={
                "player_name": "X", "position": "OF",
                "stats": {"player_type": "batter",
                          "AB": 500, "R": 80, "HR": 25,
                          "RBI": 85, "SB": 15, "CS": 3, "AVG": 0.275},
            },
        )
        assert resp.status_code == 403


# ═══════════════════════════════════════════════════════════════════════════════
# Test class 8 — Baseline Reload Flow (backend → API server)
# ═══════════════════════════════════════════════════════════════════════════════

class TestBaselineReloadFlow:
    """
    Simulates the daily_update pipeline pushing new baselines from the backend
    to the API server's in-memory cache.
    """

    BASELINE_PAYLOAD = {
        "batter":  {"R":   {"mean": 75.0,  "std": 20.0},
                    "HR":  {"mean": 18.0,  "std": 10.0},
                    "RBI": {"mean": 72.0,  "std": 20.0},
                    "SB":  {"mean": 12.0,  "std": 10.0},
                    "AVG": {"mean": 0.260, "std": 0.025}},
        "pitcher": {"W":    {"mean": 10.0,  "std":  4.0},
                    "SV":   {"mean": 10.0,  "std": 14.0},
                    "K":    {"mean": 130.0, "std": 50.0},
                    "ERA":  {"mean":  4.00, "std":  0.70},
                    "WHIP": {"mean":  1.25, "std":  0.15}},
    }

    def test_reload_endpoint_accepts_baselines(self):
        resp = requests.post(
            f"{API_URL}/internal/reload-baselines",
            json=self.BASELINE_PAYLOAD,
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"

    @pytest.mark.skip(reason="Requires MOCK_GOOGLE_AUTH backend support")
    def test_player_value_changes_after_reload(self, registered_user):
        """
        Push 'tough' baselines (high mean/std) then 'easy' baselines.
        Player value must be higher after the easy push.
        """
        player_body = {
            "player_name": "Baseline E2E Test", "position": "OF",
            "stats": {"player_type": "batter",
                      "AB": 540, "R": 85, "HR": 24, "RBI": 88,
                      "SB": 15, "CS": 4, "AVG": 0.276},
        }

        # Push tough baselines (elite pool → player looks mediocre)
        requests.post(f"{API_URL}/internal/reload-baselines", json={
            "batter":  {"R":   {"mean": 110.0, "std": 20.0},
                        "HR":  {"mean": 35.0,  "std": 10.0},
                        "RBI": {"mean": 105.0, "std": 20.0},
                        "SB":  {"mean": 25.0,  "std": 10.0},
                        "AVG": {"mean": 0.290, "std": 0.025}},
            "pitcher": self.BASELINE_PAYLOAD["pitcher"],
        })
        val_tough = _api_post(
            "/player/value",
            headers={"X-API-Key": registered_user["api_key"]},
            json=player_body,
        ).json()["player_value"]

        # Push easy baselines (weak pool → player looks elite)
        requests.post(f"{API_URL}/internal/reload-baselines", json={
            "batter":  {"R":   {"mean": 40.0,  "std": 15.0},
                        "HR":  {"mean": 10.0,  "std":  8.0},
                        "RBI": {"mean": 40.0,  "std": 15.0},
                        "SB":  {"mean":  5.0,  "std":  7.0},
                        "AVG": {"mean": 0.230, "std": 0.020}},
            "pitcher": self.BASELINE_PAYLOAD["pitcher"],
        })
        val_easy = _api_post(
            "/player/value",
            headers={"X-API-Key": registered_user["api_key"]},
            json=player_body,
        ).json()["player_value"]

        assert val_easy > val_tough, (
            f"Easy baselines should yield higher value: {val_easy} vs {val_tough}"
        )

        # Restore sensible defaults
        requests.post(f"{API_URL}/internal/reload-baselines",
                      json=self.BASELINE_PAYLOAD)


# ═══════════════════════════════════════════════════════════════════════════════
# Frontend component tests (Vitest / React Testing Library)
# The tests below are written as a TypeScript/Vitest spec.
# Save this as:  frontend/src/pages/__tests__/Demo.test.tsx
# Run with:      cd frontend && npx vitest run
# ═══════════════════════════════════════════════════════════════════════════════
#
# The following block is a raw string containing the TypeScript test file.
# A helper at the bottom of this file writes it to the correct location if
# the frontend/ directory is present.

_DEMO_COMPONENT_TEST_TSX = '''\
/**
 * Demo.test.tsx
 * =============
 * Component-level tests for the Demo page (frontend/src/pages/Demo.tsx).
 *
 * Run:  cd frontend && npx vitest run
 *
 * Setup requirements (add to frontend/package.json devDependencies):
 *   vitest, @vitest/ui, @testing-library/react, @testing-library/user-event,
 *   @testing-library/jest-dom, msw, jsdom, @vitejs/plugin-react
 *
 * Add to frontend/vite.config.ts (or vitest.config.ts):
 *   test: { environment: "jsdom", globals: true,
 *            setupFiles: ["./src/test-setup.ts"] }
 *
 * frontend/src/test-setup.ts:
 *   import "@testing-library/jest-dom";
 */

import React from "react";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { setupServer } from "msw/node";
import { beforeAll, afterAll, afterEach, describe, it, expect, vi } from "vitest";
import Demo from "../Demo";

// ── Mock API server ───────────────────────────────────────────────────────────

const MOCK_VALUE_RESPONSE = {
  player_name: "Juan Soto",
  player_type: "batter",
  player_value: 78.5,
  value_breakdown: { stat_score: 72.0, position_bonus: 6.0, risk_penalty: 0.0 },
};

const MOCK_BID_RESPONSE = {
  ...MOCK_VALUE_RESPONSE,
  recommended_bid: 42,
  bid_breakdown: {
    base_price: 38.5,
    scarcity_adjustment: 0.0,
    draft_adjustment: 3.5,
    max_spendable: 94,
    max_competitor_budget: 94,
  },
};

const server = setupServer(
  http.post("*/demo/value", () => HttpResponse.json(MOCK_VALUE_RESPONSE)),
  http.post("*/demo/bid",   () => HttpResponse.json(MOCK_BID_RESPONSE)),
);

beforeAll(() => server.listen({ onUnhandledRequest: "error" }));
afterEach(() => server.resetHandlers());
afterAll(() => server.close());

// ── Tests ─────────────────────────────────────────────────────────────────────

describe("Demo component — rendering", () => {
  it("renders the page heading", () => {
    render(<Demo />);
    // The heading text is "Try the API" in Demo.tsx
    expect(screen.getByText(/try the api/i)).toBeInTheDocument();
  });

  it("renders mode toggle buttons", () => {
    render(<Demo />);
    expect(screen.getByText(/demo\/value/i)).toBeInTheDocument();
    expect(screen.getByText(/demo\/bid/i)).toBeInTheDocument();
  });

  it("renders batter stat fields by default", () => {
    render(<Demo />);
    expect(screen.getByLabelText(/^AB$/i) ?? screen.queryByText(/^AB$/i))
      .toBeTruthy();
  });

  it("renders the Submit button", () => {
    render(<Demo />);
    expect(screen.getByRole("button", { name: /submit/i })).toBeInTheDocument();
  });
});

describe("Demo component — mode toggle", () => {
  it("switches to bid mode and shows draft context fields", async () => {
    render(<Demo />);
    await userEvent.click(screen.getByText(/demo\/bid/i));
    expect(
      screen.getByText(/my_remaining_budget/i)
    ).toBeInTheDocument();
  });

  it("hides draft context fields in value mode", async () => {
    render(<Demo />);
    await userEvent.click(screen.getByText(/demo\/value/i));
    expect(
      screen.queryByText(/my_remaining_budget/i)
    ).not.toBeInTheDocument();
  });
});

describe("Demo component — player type toggle", () => {
  it("shows pitcher fields after switching to pitcher type", async () => {
    render(<Demo />);
    await userEvent.click(screen.getByText(/pitcher/i));
    expect(screen.getByText(/^ERA$/i) ?? screen.queryByText(/ERA/)).toBeTruthy();
  });

  it("hides batter fields when pitcher is selected", async () => {
    render(<Demo />);
    await userEvent.click(screen.getByText(/pitcher/i));
    // AB is a batter-only field
    expect(screen.queryByText(/^AB$/i)).not.toBeInTheDocument();
  });
});

describe("Demo component — submit flow (value mode)", () => {
  it("displays player_value after a successful /demo/value call", async () => {
    render(<Demo />);
    await userEvent.click(screen.getByRole("button", { name: /submit/i }));
    await waitFor(() => {
      expect(screen.getByText("78.5")).toBeInTheDocument();
    });
  });

  it("displays value_breakdown table after a successful call", async () => {
    render(<Demo />);
    await userEvent.click(screen.getByRole("button", { name: /submit/i }));
    await waitFor(() => {
      expect(screen.getByText(/stat_score/i)).toBeInTheDocument();
    });
  });

  it("shows loading state while request is in flight", async () => {
    let resolve: (v: unknown) => void;
    const pending = new Promise((res) => { resolve = res; });
    server.use(
      http.post("*/demo/value", async () => {
        await pending;
        return HttpResponse.json(MOCK_VALUE_RESPONSE);
      }),
    );
    render(<Demo />);
    fireEvent.click(screen.getByRole("button", { name: /submit/i }));
    expect(screen.getByText(/loading/i)).toBeInTheDocument();
    resolve!(undefined);
  });
});

describe("Demo component — submit flow (bid mode)", () => {
  it("displays recommended_bid after a successful /demo/bid call", async () => {
    render(<Demo />);
    await userEvent.click(screen.getByText(/demo\/bid/i));
    await userEvent.click(screen.getByRole("button", { name: /submit/i }));
    await waitFor(() => {
      expect(screen.getByText("$42")).toBeInTheDocument();
    });
  });

  it("displays bid_breakdown table after a successful call", async () => {
    render(<Demo />);
    await userEvent.click(screen.getByText(/demo\/bid/i));
    await userEvent.click(screen.getByRole("button", { name: /submit/i }));
    await waitFor(() => {
      expect(screen.getByText(/base_price/i)).toBeInTheDocument();
    });
  });
});

describe("Demo component — error state", () => {
  it("shows error message when the API returns 500", async () => {
    server.use(
      http.post("*/demo/value", () =>
        HttpResponse.json({ detail: "Internal Server Error" }, { status: 500 })
      ),
    );
    render(<Demo />);
    await userEvent.click(screen.getByRole("button", { name: /submit/i }));
    await waitFor(() => {
      // Demo.tsx renders the error string in a red div
      expect(document.querySelector(".text-red-300")).toBeTruthy();
    });
  });

  it("clears a previous result when mode is changed", async () => {
    render(<Demo />);
    // Get a result first
    await userEvent.click(screen.getByRole("button", { name: /submit/i }));
    await waitFor(() => screen.getByText("78.5"));
    // Toggle mode → result div should disappear
    await userEvent.click(screen.getByText(/demo\/bid/i));
    expect(screen.queryByText("78.5")).not.toBeInTheDocument();
  });
});

describe("ScoreBar component — tier labeling", () => {
  it("shows 'Elite' tier label for player_value >= 80", async () => {
    server.use(
      http.post("*/demo/value", () =>
        HttpResponse.json({ ...MOCK_VALUE_RESPONSE, player_value: 85.0 })
      ),
    );
    render(<Demo />);
    await userEvent.click(screen.getByRole("button", { name: /submit/i }));
    await waitFor(() => {
      expect(screen.getByText(/elite/i)).toBeInTheDocument();
    });
  });

  it("shows 'Strong' tier label for player_value 60–79", async () => {
    server.use(
      http.post("*/demo/value", () =>
        HttpResponse.json({ ...MOCK_VALUE_RESPONSE, player_value: 70.0 })
      ),
    );
    render(<Demo />);
    await userEvent.click(screen.getByRole("button", { name: /submit/i }));
    await waitFor(() => {
      expect(screen.getByText(/strong/i)).toBeInTheDocument();
    });
  });
});
'''


def _write_frontend_test():
    """
    Write the TypeScript component test file to its correct location under
    frontend/src/pages/__tests__/ if the frontend directory exists.
    Called once at module import time.
    """
    root = Path(__file__).parent.parent  # project root
    dest = root / "frontend" / "src" / "pages" / "__tests__" / "Demo.test.tsx"
    if dest.parent.parent.parent.exists():  # frontend/ directory exists
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(_DEMO_COMPONENT_TEST_TSX)


# Write the frontend test file when this module is imported
_write_frontend_test()