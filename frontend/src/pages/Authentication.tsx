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
//   5. IP whitelist  → POST/GET/DELETE /api/auth/allowed-ip
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
  const [copied, setCopied] = useState<string | null>(null);

  // showRegenerateModal controls the visibility of the confirmation modal
  // that appears before executing a one-click key regeneration.
  const [showRegenerateModal, setShowRegenerateModal] = useState(false);

  // pendingDeleteKey stores the key string targeted for deletion.
  // null means the delete modal is closed; a key string opens it.
  const [pendingDeleteKey, setPendingDeleteKey] = useState<string | null>(null);

  // revealedKeys tracks which keys are currently unmasked.
  // By default all keys are masked; clicking "Show" adds the key to this set.
  const [revealedKeys, setRevealedKeys] = useState<Set<string>>(new Set());

  // toggleReveal shows or hides the actual key value for a given key string.
  const toggleReveal = (key: string) => {
    setRevealedKeys((prev) => {
      const next = new Set(prev);
      next.has(key) ? next.delete(key) : next.add(key);
      return next;
    });
  };

  // allowedIp: the IP address currently registered for this user (null = none registered).
  // ipInput: the value of the IP input field (controlled).
  // justGeneratedKey: true immediately after a key is generated to show the IP registration prompt.
  const [allowedIp,        setAllowedIp]        = useState<string | null>(null);
  const [ipInput,          setIpInput]          = useState("");
  const [ipError,          setIpError]          = useState("");
  const [ipSuccess,        setIpSuccess]        = useState("");
  const [justGeneratedKey, setJustGeneratedKey] = useState(false);

  // ── Sync auth state to sessionStorage ────────────────────────────────────
  // Runs whenever user or token changes.
  // If both are set → persist to sessionStorage and fetch the key list.
  // If either is cleared (logout) → remove both from sessionStorage.

  useEffect(() => {
    if (user && token) {
      sessionStorage.setItem("user",  JSON.stringify(user));
      sessionStorage.setItem("token", token);
      fetchApiKeys(token);
      fetchAllowedIp(token);
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
      // Show the "please register your IP" prompt after key generation
      setJustGeneratedKey(true);
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

  // ── regenerateApiKey ──────────────────────────────────────────────────────
  // Deletes the existing API key and immediately issues a new one.
  // Called only after the user confirms the action in the confirmation modal.
  // Sequence: delete existing key → create new key → close modal.

  const regenerateApiKey = async () => {
    if (apiKeys.length === 0) return;  // Guard: nothing to regenerate
    setError("");
    try {
      await deleteApiKey(apiKeys[0].key);
      await createApiKey();
      // Show IP registration prompt only if no IP is registered yet.
      // Users who already have an IP registered do not need the reminder.
      if (allowedIp !== null) {
        setJustGeneratedKey(false);
      }
    } catch {
      setError("Failed to regenerate API key");
    } finally {
      setShowRegenerateModal(false);
    }
  };

  // ── fetchAllowedIp ────────────────────────────────────────────────────────
  // Fetches the currently registered allowed IP for the logged-in user.
  // Sets allowedIp to null if none is registered (404 is expected, not an error).

  const fetchAllowedIp = async (googleToken: string) => {
    try {
      const res = await fetch(
        `${BACKEND_URL}/api/auth/allowed-ip?google_token=${googleToken}`
      );
      if (res.ok) {
        const data = await res.json();
        setAllowedIp(data.ip_address);
        setIpInput(data.ip_address);
      } else {
        // 404 means no IP registered yet — this is the normal initial state
        setAllowedIp(null);
        setIpInput("");
      }
    } catch {
      setAllowedIp(null);
    }
  };

  // ── saveAllowedIp ─────────────────────────────────────────────────────────
  // Registers or updates the allowed IP address via POST /api/auth/allowed-ip.
  // The backend performs an upsert — calling this multiple times is safe.

  const saveAllowedIp = async () => {
    setIpError("");
    setIpSuccess("");
    if (!ipInput.trim()) {
      setIpError("Please enter an IP address.");
      return;
    }
    try {
      const res = await fetch(`${BACKEND_URL}/api/auth/allowed-ip`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ token, ip_address: ipInput.trim() }),
      });
      if (!res.ok) {
        const err = await res.json();
        setIpError(err.detail || "Failed to save IP address.");
        return;
      }
      const data = await res.json();
      setAllowedIp(data.ip_address);
      setIpSuccess("Allowed IP saved successfully.");
      setJustGeneratedKey(false);
    } catch {
      setIpError("Failed to connect to server.");
    }
  };

  // ── deleteAllowedIp ───────────────────────────────────────────────────────
  // Removes the registered allowed IP, restoring access from any IP.

  const deleteAllowedIp = async () => {
    setIpError("");
    setIpSuccess("");
    try {
      const res = await fetch(
        `${BACKEND_URL}/api/auth/allowed-ip?google_token=${token}`,
        { method: "DELETE" }
      );
      if (res.ok) {
        setAllowedIp(null);
        setIpInput("");
        setIpSuccess("Allowed IP removed. Requests from any IP are now accepted.");
      }
    } catch {
      setIpError("Failed to remove IP address.");
    }
  };

  // ── handleLogout ──────────────────────────────────────────────────────────
  // Clears all auth state and sessionStorage, returning the page to the login view.
  // No backend call is needed — Google OAuth tokens are stateless on the client side.

  const handleLogout = () => {
    setUser(null);
    setToken("");
    setApiKeys([]);
    setAllowedIp(null);
    setIpInput("");
    setIpError("");
    setIpSuccess("");
    setError("");
    setJustGeneratedKey(false);
    sessionStorage.removeItem("user");
    sessionStorage.removeItem("token");
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

            {/* Account information card */}
            <div className="rounded-3xl border border-white/10 bg-white/5 p-6 space-y-3">
              <div className="flex items-center justify-between mb-2">
                <p className="text-xs font-bold text-white/40 uppercase">Account</p>
                {/* Sign Out: clears all local auth state and returns to the login view */}
                <button
                  onClick={handleLogout}
                  className="rounded-lg bg-white/10 px-3 py-1 text-xs text-white/60 hover:bg-white/20 transition"
                >
                  Sign Out
                </button>
              </div>
              <div className="flex items-center gap-3">
                <span className="text-xs text-white/40 w-12">Name</span>
                <span className="text-sm text-white font-semibold">{user.name}</span>
              </div>
              <div className="flex items-center gap-3">
                <span className="text-xs text-white/40 w-12">Email</span>
                <span className="text-sm text-white/70">{user.email}</span>
              </div>
            </div>

            {/* IP registration prompt banner — shown immediately after key generation */}
            {justGeneratedKey && (
              <div className="rounded-2xl border border-yellow-400/30 bg-yellow-400/10 p-4 flex items-start gap-3">
                <span className="text-yellow-400 text-lg mt-0.5">⚠</span>
                <div>
                  <p className="text-sm font-bold text-yellow-300">Register your allowed IP address</p>
                  <p className="text-xs text-yellow-200/70 mt-1">
                    Your API key has been generated. For security, scroll down to register
                    the IP address from which you will make API requests.
                  </p>
                </div>
              </div>
            )}

            {/* API key management card */}
            <div className="rounded-3xl border border-white/10 bg-white/5 p-6 space-y-4">
              <div className="flex items-center justify-between">
                <p className="text-xs font-bold text-white/40 uppercase">Your API Keys</p>
                <div className="flex gap-2">
                  {/* Disabled when the user already has a key — enforces 1-key-per-user
                      client-side. The backend also enforces this with a 400 error. */}
                  <button
                    onClick={createApiKey}
                    disabled={apiKeys.length >= 1}
                    className="rounded-lg bg-white px-4 py-1.5 text-xs font-bold text-black hover:bg-white/90 disabled:opacity-30 disabled:cursor-not-allowed transition"
                  >
                    Generate New Key
                  </button>
                  {/* Regenerate button: only active when a key already exists.
                      Opens a confirmation modal before executing delete + create. */}
                  <button
                    onClick={() => setShowRegenerateModal(true)}
                    disabled={apiKeys.length === 0}
                    className="rounded-lg bg-yellow-500/20 px-4 py-1.5 text-xs font-bold text-yellow-400 hover:bg-yellow-500/30 disabled:opacity-30 disabled:cursor-not-allowed transition"
                  >
                    Regenerate
                  </button>
                </div>
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
                      {/* Key value — masked by default, revealed on toggle.
                          break-all ensures long keys wrap instead of overflow. */}
                      <code className="text-sm text-white/80 break-all">
                        {revealedKeys.has(k.key) ? k.key : "•".repeat(32)}
                      </code>
                      <div className="flex flex-col gap-2 shrink-0">
                        {/* Show/Hide button: toggles key visibility */}
                        <button
                          onClick={() => toggleReveal(k.key)}
                          className="rounded-lg bg-white/10 px-3 py-1 text-xs text-white/60 hover:bg-white/20 transition"
                        >
                          {revealedKeys.has(k.key) ? "Hide" : "Show"}
                        </button>
                        {/* Copy button: shows "Copied!" for 2s after click */}
                        <button
                          onClick={() => copyToClipboard(k.key)}
                          className="rounded-lg bg-white/10 px-3 py-1 text-xs text-white/60 hover:bg-white/20 transition"
                        >
                          {copied === k.key ? "Copied!" : "Copy"}
                        </button>
                        {/* Delete button: opens confirmation modal before deleting */}
                        <button
                          onClick={() => setPendingDeleteKey(k.key)}
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

            {/* IP Whitelist card */}
            <div className="rounded-3xl border border-white/10 bg-white/5 p-6 space-y-4">
              <p className="text-xs font-bold text-white/40 uppercase">IP Whitelist</p>
              <p className="text-sm text-white/50">
                Restrict API access to a single trusted IP address. If no IP is registered,
                requests from any IP are accepted.
              </p>

              {/* Current registered IP display */}
              {allowedIp && (
                <div className="rounded-2xl border border-white/10 bg-black/40 p-4 flex items-center justify-between gap-4">
                  <div>
                    <p className="text-xs text-white/40 mb-1">Registered IP</p>
                    <code className="text-sm text-white/80">{allowedIp}</code>
                  </div>
                  <button
                    onClick={deleteAllowedIp}
                    className="rounded-lg bg-red-500/20 px-3 py-1 text-xs text-red-400 hover:bg-red-500/30 transition shrink-0"
                  >
                    Remove
                  </button>
                </div>
              )}

              {/* IP input + save */}
              <div className="flex gap-2">
                <input
                  type="text"
                  value={ipInput}
                  onChange={(e) => setIpInput(e.target.value)}
                  placeholder={allowedIp ? "Enter new IP to update" : "e.g. 203.0.113.42"}
                  className="flex-1 rounded-lg bg-black/40 border border-white/10 px-3 py-2 text-sm text-white placeholder-white/30 focus:outline-none focus:border-white/30"
                />
                <button
                  onClick={saveAllowedIp}
                  className="rounded-lg bg-white px-4 py-2 text-xs font-bold text-black hover:bg-white/90 transition shrink-0"
                >
                  {allowedIp ? "Update" : "Register"}
                </button>
              </div>

              {ipError   && <p className="text-sm text-red-400">{ipError}</p>}
              {ipSuccess && <p className="text-sm text-green-400">{ipSuccess}</p>}
            </div>

          </div>
        )}
      </div>

      {/* ── Delete confirmation modal ─────────────────────────────────────── */}
      {pendingDeleteKey && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm">
          <div className="rounded-3xl border border-white/10 bg-[#111] p-8 max-w-sm w-full mx-4 space-y-4">
            <p className="text-white font-bold text-lg">Delete API Key?</p>
            <p className="text-sm text-white/50">
              This API key will be permanently deleted.
              Any services using this key will stop working immediately.
            </p>
            <div className="flex gap-3 pt-2">
              {/* Cancel: close the modal without any changes */}
              <button
                onClick={() => setPendingDeleteKey(null)}
                className="flex-1 rounded-lg border border-white/10 bg-white/5 px-4 py-2 text-sm text-white/60 hover:bg-white/10 transition"
              >
                Cancel
              </button>
              {/* Confirm: execute delete */}
              <button
                onClick={() => { deleteApiKey(pendingDeleteKey); setPendingDeleteKey(null); }}
                className="flex-1 rounded-lg bg-red-500 px-4 py-2 text-sm font-bold text-white hover:bg-red-400 transition"
              >
                Delete
              </button>
            </div>
          </div>
        </div>
      )}

      {/* ── Regenerate confirmation modal ──────────────────────────────────── */}
      {/* Rendered outside the main card flow so it overlays the entire page.  */}
      {/* Visible only when showRegenerateModal is true.                        */}
      {showRegenerateModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm">
          <div className="rounded-3xl border border-white/10 bg-[#111] p-8 max-w-sm w-full mx-4 space-y-4">
            <p className="text-white font-bold text-lg">Regenerate API Key?</p>
            <p className="text-sm text-white/50">
              Your current API key will be permanently deleted and a new one will be issued.
              Any services using the old key will stop working immediately.
            </p>
            <div className="flex gap-3 pt-2">
              {/* Cancel: close the modal without any changes */}
              <button
                onClick={() => setShowRegenerateModal(false)}
                className="flex-1 rounded-lg border border-white/10 bg-white/5 px-4 py-2 text-sm text-white/60 hover:bg-white/10 transition"
              >
                Cancel
              </button>
              {/* Confirm: execute delete → create sequence */}
              <button
                onClick={regenerateApiKey}
                className="flex-1 rounded-lg bg-yellow-500 px-4 py-2 text-sm font-bold text-black hover:bg-yellow-400 transition"
              >
                Confirm
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

export default Authentication;