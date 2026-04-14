import { useState, useEffect } from "react";
import { GoogleLogin } from "@react-oauth/google";
import type { CredentialResponse } from "@react-oauth/google";

// BACKEND_URL points to the backend server that handles auth and API key management.
// Falls back to the production domain if VITE_BACKEND_URL is not set.
const BACKEND_URL = import.meta.env.VITE_BACKEND_URL || "https://api.ppa-dun.site";

// ── Types ─────────────────────────────────────────────────────────────────────

interface APIKey {
  key:        string;
  created_at: string;
}

interface User {
  id:    number;
  email: string;
  name:  string;
}

// ── Authentication (main component) ──────────────────────────────────────────
// Handles the full Google OAuth + API key lifecycle:
//   1. Google login  → POST /api/auth/google    → stores user + token
//   2. Fetch keys    → GET  /api/auth/api-keys  → lists existing keys
//   3. Generate key  → POST /api/auth/api-key   → issues a new key
//   4. Delete key    → DELETE /api/auth/api-key/{key}
//
// Auth state (user + token) is persisted in sessionStorage so it survives
// page refreshes within the same browser tab, but is cleared when the tab closes.

function Authentication() {

  // Initialize user from sessionStorage so the logged-in state persists on refresh.
  // The lazy initializer function runs only once on mount.
  const [user, setUser] = useState<User | null>(() => {
    const saved = sessionStorage.getItem("user");
    return saved ? JSON.parse(saved) : null;
  });

  // token is the raw Google ID token (JWT) returned by Google OAuth.
  // It is used as the auth credential for all backend API calls.
  // Persisted in sessionStorage alongside user.
  const [token, setToken] = useState<string>(() => {
    return sessionStorage.getItem("token") || "";
  });

  const [apiKeys, setApiKeys] = useState<APIKey[]>([]);
  const [error,   setError]   = useState("");

  // copied tracks which key was just copied to clipboard for the 2-second
  // "Copied!" feedback state. Stores the key string, or null if none.
  const [copied, setCopied]   = useState<string | null>(null);

  // ── Sync auth state to sessionStorage ────────────────────────────────────
  // Runs whenever user or token changes.
  // If both are set → persist to sessionStorage and fetch the key list.
  // If either is cleared (logout) → remove both from sessionStorage.

  useEffect(() => {
    if (user && token) {
      sessionStorage.setItem("user",  JSON.stringify(user));
      sessionStorage.setItem("token", token);
      fetchApiKeys(token);
    } else {
      sessionStorage.removeItem("user");
      sessionStorage.removeItem("token");
    }
  }, [user, token]);

  // ── handleLogin ───────────────────────────────────────────────────────────
  // Called by <GoogleLogin> on successful OAuth.
  // response.credential is the Google ID token (JWT).
  // Flow:
  //   1. Store the token in state (triggers useEffect → sessionStorage persist)
  //   2. POST to backend /api/auth/google to create/fetch the user record
  //   3. Fetch the user's existing API keys

  const handleLogin = async (response: CredentialResponse) => {
    if (!response.credential) return;  // Guard: credential should always be present on success
    setToken(response.credential);
    setError("");

    try {
      const res = await fetch(`${BACKEND_URL}/api/auth/google`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ token: response.credential }),
      });

      if (!res.ok) {
        setError("Login failed");
        return;
      }

      const userData = await res.json();
      setUser(userData);
      await fetchApiKeys(response.credential);
    } catch {
      setError("Failed to connect to server");
    }
  };

  // ── fetchApiKeys ──────────────────────────────────────────────────────────
  // Fetches all API keys for the currently logged-in user.
  // googleToken is passed as a query parameter — the backend verifies it
  // to identify which user's keys to return.
  // NOTE: passing tokens as query parameters exposes them in server logs
  // and browser history. This is a known security concern (see code review).

  const fetchApiKeys = async (googleToken: string) => {
    try {
      const res = await fetch(
        `${BACKEND_URL}/api/auth/api-keys?google_token=${googleToken}`
      );
      if (res.ok) {
        const keys = await res.json();
        setApiKeys(keys);
      }
    } catch {
      // Silently ignore fetch errors here — the key list will just remain empty.
      // Non-critical: user can refresh the page to retry.
    }
  };

  // ── createApiKey ──────────────────────────────────────────────────────────
  // Issues a new API key for the logged-in user.
  // The backend enforces a one-key-per-user limit — if a key already exists,
  // the backend returns 400 and the error detail is shown to the user.
  // The "Generate New Key" button is also disabled client-side when apiKeys.length >= 1.

  const createApiKey = async () => {
    try {
      const res = await fetch(`${BACKEND_URL}/api/auth/api-key`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ token }),
      });

      if (!res.ok) {
        const err = await res.json();
        setError(err.detail || "Failed to create API key");
        return;
      }

      // Refresh the key list to show the newly created key
      await fetchApiKeys(token);
    } catch {
      setError("Failed to create API key");
    }
  };

  // ── deleteApiKey ──────────────────────────────────────────────────────────
  // Deletes a specific API key belonging to the logged-in user.
  // Both the key (path param) and google_token (query param) are sent so the
  // backend can verify ownership before deleting.
  // NOTE: same query-parameter token exposure concern as fetchApiKeys.

  const deleteApiKey = async (key: string) => {
    try {
      const res = await fetch(
        `${BACKEND_URL}/api/auth/api-key/${key}?google_token=${token}`,
        { method: "DELETE" }
      );

      if (res.ok) {
        // Refresh the key list to reflect the deletion
        await fetchApiKeys(token);
      }
    } catch {
      setError("Failed to delete API key");
    }
  };

  // ── copyToClipboard ───────────────────────────────────────────────────────
  // Copies the key string to the system clipboard and shows a "Copied!" label
  // for 2 seconds before reverting back to "Copy".

  const copyToClipboard = (key: string) => {
    navigator.clipboard.writeText(key);
    setCopied(key);
    setTimeout(() => setCopied(null), 2000);
  };

  // ── Render ────────────────────────────────────────────────────────────────

  return (
    <div className="relative min-h-screen flex flex-col items-center justify-center px-6 pt-24 pb-16">
      <div className="absolute inset-0 bg-gradient-to-b from-white/5 to-black pointer-events-none" />

      <div className="relative z-10 max-w-2xl w-full">
        <h1 className="text-4xl font-extrabold tracking-tight text-white mb-2">
          Authentication
        </h1>
        <p className="text-white/50 text-sm mb-10">
          Sign in with Google to get your API key.
        </p>

        {/* Conditional render: show login card if not signed in, dashboard if signed in */}
        {!user ? (

          /* ── Login state ─────────────────────────────────────────────── */
          <div className="rounded-3xl border border-white/10 bg-white/5 p-8 flex flex-col items-center gap-6">
            <p className="text-sm text-white/60">Sign in to generate and manage your API keys.</p>
            {/* GoogleLogin renders Google's OAuth button.
                onSuccess fires with a CredentialResponse containing the ID token.
                onError fires if the OAuth flow fails or is cancelled. */}
            <GoogleLogin
              onSuccess={handleLogin}
              onError={() => setError("Google login failed")}
            />
            {error && <p className="text-sm text-red-400">{error}</p>}
          </div>

        ) : (

          /* ── Logged-in state ─────────────────────────────────────────── */
          <div className="space-y-6">

            {/* User info card */}
            <div className="rounded-3xl border border-white/10 bg-white/5 p-6">
              <p className="text-xs font-bold text-white/40 uppercase mb-2">Signed in as</p>
              <p className="text-white font-bold">{user.name}</p>
              <p className="text-sm text-white/50">{user.email}</p>
            </div>

            {/* API key management card */}
            <div className="rounded-3xl border border-white/10 bg-white/5 p-6 space-y-4">
              <div className="flex items-center justify-between">
                <p className="text-xs font-bold text-white/40 uppercase">Your API Keys</p>
                {/* Disabled when the user already has a key — enforces 1-key-per-user
                    client-side. The backend also enforces this with a 400 error. */}
                <button
                  onClick={createApiKey}
                  disabled={apiKeys.length >= 1}
                  className="rounded-lg bg-white px-4 py-1.5 text-xs font-bold text-black hover:bg-white/90 transition"
                >
                  Generate New Key
                </button>
              </div>

              {error && <p className="text-sm text-red-400">{error}</p>}

              {apiKeys.length === 0 ? (
                <p className="text-sm text-white/40">No API keys yet. Generate one to get started.</p>
              ) : (
                <div className="space-y-3">
                  {apiKeys.map((k) => (
                    <div
                      key={k.key}
                      className="rounded-2xl border border-white/10 bg-black/40 p-4 flex items-center justify-between gap-4"
                    >
                      {/* Key value — truncated with CSS if too long for the container */}
                      <code className="text-sm text-white/80 truncate">{k.key}</code>
                      <div className="flex gap-2 shrink-0">
                        {/* Copy button: shows "Copied!" for 2s after click */}
                        <button
                          onClick={() => copyToClipboard(k.key)}
                          className="rounded-lg bg-white/10 px-3 py-1 text-xs text-white/60 hover:bg-white/20 transition"
                        >
                          {copied === k.key ? "Copied!" : "Copy"}
                        </button>
                        {/* Delete button: calls backend and refreshes key list on success */}
                        <button
                          onClick={() => deleteApiKey(k.key)}
                          className="rounded-lg bg-red-500/20 px-3 py-1 text-xs text-red-400 hover:bg-red-500/30 transition"
                        >
                          Delete
                        </button>
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>

            {/* Usage example card — static code snippets showing how to use the key */}
            <div className="rounded-3xl border border-white/10 bg-white/5 p-6 space-y-4">
              <p className="text-xs font-bold text-white/40 uppercase mb-2">How to use</p>
              {/* Header format */}
              <pre className="rounded-2xl border border-white/10 bg-black/40 p-4 text-sm text-white/80 whitespace-pre-wrap break-all">
                X-API-Key: your_api_key_here
              </pre>
              {/* Full curl example for POST /player/value */}
              <pre className="rounded-2xl border border-white/10 bg-black/40 p-4 text-sm text-white/80 whitespace-pre-wrap break-all">
{`curl -X POST https://api.ppa-dun.site/player/value \\
  -H "Content-Type: application/json" \\
  -H "X-API-Key: your_api_key_here" \\
  -d '{
    "player_name": "Shohei Ohtani",
    "player_type": "batter",
    "position": "DH",
    "stats": {"AB": 536, "R": 102, "HR": 44, "RBI": 96, "SB": 20, "CS": 6, "AVG": 0.310},
    "league_context": {"league_size": 12, "roster_size": 23, "total_budget": 260}
  }'`}
              </pre>
            </div>

          </div>
        )}
      </div>
    </div>
  );
}

export default Authentication;