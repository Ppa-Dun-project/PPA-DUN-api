import { useState } from "react";
import { GoogleLogin } from "@react-oauth/google";
import type { CredentialResponse } from "@react-oauth/google";

const API_URL = import.meta.env.VITE_API_URL || "";

interface APIKey {
  key: string;
  created_at: string;
}

interface User {
  id: number;
  email: string;
  name: string;
}

function Authentication() {
  const [user, setUser] = useState<User | null>(null);
  const [token, setToken] = useState<string>("");
  const [apiKeys, setApiKeys] = useState<APIKey[]>([]);
  const [error, setError] = useState("");
  const [copied, setCopied] = useState<string | null>(null);

  const handleLogin = async (response: CredentialResponse) => {
    if (!response.credential) return;
    setToken(response.credential);
    setError("");

    try {
      const res = await fetch(`${API_URL}/api/auth/google`, {
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

  const fetchApiKeys = async (googleToken: string) => {
    try {
      const res = await fetch(`${API_URL}/api/auth/api-keys?google_token=${googleToken}`);
      if (res.ok) {
        const keys = await res.json();
        setApiKeys(keys);
      }
    } catch {
      // ignore
    }
  };

  const createApiKey = async () => {
    try {
      const res = await fetch(`${API_URL}/api/auth/api-key`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ token }),
      });

      if (res.ok) {
        await fetchApiKeys(token);
      }
    } catch {
      setError("Failed to create API key");
    }
  };

  const copyToClipboard = (key: string) => {
    navigator.clipboard.writeText(key);
    setCopied(key);
    setTimeout(() => setCopied(null), 2000);
  };

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

        {!user ? (
          <div className="rounded-3xl border border-white/10 bg-white/5 p-8 flex flex-col items-center gap-6">
            <p className="text-sm text-white/60">Sign in to generate and manage your API keys.</p>
            <GoogleLogin
              onSuccess={handleLogin}
              onError={() => setError("Google login failed")}
            />
            {error && (
              <p className="text-sm text-red-400">{error}</p>
            )}
          </div>
        ) : (
          <div className="space-y-6">
            {/* User info */}
            <div className="rounded-3xl border border-white/10 bg-white/5 p-6">
              <p className="text-xs font-bold text-white/40 uppercase mb-2">Signed in as</p>
              <p className="text-white font-bold">{user.name}</p>
              <p className="text-sm text-white/50">{user.email}</p>
            </div>

            {/* API Keys */}
            <div className="rounded-3xl border border-white/10 bg-white/5 p-6 space-y-4">
              <div className="flex items-center justify-between">
                <p className="text-xs font-bold text-white/40 uppercase">Your API Keys</p>
                <button
                  onClick={createApiKey}
                  className="rounded-lg bg-white px-4 py-1.5 text-xs font-bold text-black hover:bg-white/90 transition"
                >
                  Generate New Key
                </button>
              </div>

              {apiKeys.length === 0 ? (
                <p className="text-sm text-white/40">No API keys yet. Generate one to get started.</p>
              ) : (
                <div className="space-y-3">
                  {apiKeys.map((k) => (
                    <div
                      key={k.key}
                      className="rounded-2xl border border-white/10 bg-black/40 p-4 flex items-center justify-between gap-4"
                    >
                      <code className="text-sm text-white/80 truncate">{k.key}</code>
                      <button
                        onClick={() => copyToClipboard(k.key)}
                        className="shrink-0 rounded-lg bg-white/10 px-3 py-1 text-xs text-white/60 hover:bg-white/20 transition"
                      >
                        {copied === k.key ? "Copied!" : "Copy"}
                      </button>
                    </div>
                  ))}
                </div>
              )}
            </div>

            {/* Usage */}
            <div className="rounded-3xl border border-white/10 bg-white/5 p-6 space-y-4">
              <p className="text-xs font-bold text-white/40 uppercase mb-2">How to use</p>
              <pre className="rounded-2xl border border-white/10 bg-black/40 p-4 text-sm text-white/80 whitespace-pre-wrap break-all">
                X-API-Key: your_api_key_here
              </pre>
              <pre className="rounded-2xl border border-white/10 bg-black/40 p-4 text-sm text-white/80 whitespace-pre-wrap break-all">
                {`curl -X POST https://api.ppa-dun.site/api/player \\
  -H "Content-Type: application/json" \\
  -H "X-API-Key: your_api_key_here" \\
  -d '{"player_name": "Shohei Ohtani"}'`}
              </pre>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

export default Authentication;
