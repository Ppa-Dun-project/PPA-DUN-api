import { useState } from "react";

// API_URL falls back to the production domain if VITE_API_URL is not set.
// This ensures the demo works correctly in the GitHub Actions build environment,
// where Vite environment variables are not injected.
const API_URL = import.meta.env.VITE_API_URL || "https://api.ppa-dun.site";

type PlayerType = "batter" | "pitcher";
type DemoMode   = "value" | "bid";   // corresponds to /demo/value or /demo/bid

// ── Default form values ───────────────────────────────────────────────────────
// Pre-filled with Juan Soto (batter) and Zack Wheeler (pitcher) as examples.
// These match the sample values used in Endpoints.tsx documentation.

const DEFAULT_BATTER_STATS  = { AB: 534, R: 113, HR: 37, RBI: 97, SB: 23, CS: 4, AVG: 0.281 };
const DEFAULT_PITCHER_STATS = { IP: 200.0, W: 15, SV: 0, K: 220, ERA: 2.95, WHIP: 1.05 };
const DEFAULT_LEAGUE        = { league_size: 12, roster_size: 23, total_budget: 260 };
const DEFAULT_DRAFT         = {
  my_remaining_budget: 198,
  my_remaining_roster_spots: 17,
  my_positions_filled: "C, SP",   // stored as comma-separated string; parsed into string[] on submit
  drafted_players_count: 87,
};

// ── ScoreBar ──────────────────────────────────────────────────────────────────
// Displays player_value (0~100) as an animated progress bar with a tier label.
// Color and label are derived from the same tier thresholds used in Hero.tsx.

function ScoreBar({ value }: { value: number }) {
  const pct = Math.max(0, Math.min(100, value));  // clamp to [0, 100] for bar width

  // Map value to a Tailwind color class based on tier thresholds
  const color =
    pct >= 80 ? "bg-yellow-400" :
    pct >= 60 ? "bg-green-400"  :
    pct >= 40 ? "bg-blue-400"   :
    pct >= 20 ? "bg-orange-400" : "bg-red-400";

  const label =
    pct >= 80 ? "Elite"          :
    pct >= 60 ? "Strong"         :
    pct >= 40 ? "Average"        :
    pct >= 20 ? "Below Average"  : "Replacement Level";

  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between">
        <span className="text-xs font-bold text-white/40 uppercase">player_value</span>
        {/* Replace "bg-" prefix with "text-" to derive text color from the same ramp */}
        <span className={`text-xs font-bold ${color.replace("bg-", "text-")}`}>{label}</span>
      </div>
      {/* Track bar */}
      <div className="relative h-3 w-full rounded-full bg-white/10 overflow-hidden">
        {/* Fill bar: width animates from 0 to pct% over 700ms on mount */}
        <div
          className={`h-full rounded-full transition-all duration-700 ${color}`}
          style={{ width: `${pct}%` }}
        />
      </div>
      <div className="text-right text-2xl font-extrabold text-white">{value.toFixed(1)}</div>
    </div>
  );
}

// ── BreakdownTable ────────────────────────────────────────────────────────────
// Renders a key-value table for value_breakdown or bid_breakdown response fields.
// Accepts a plain object (Record<string, number>) and renders one row per entry.

function BreakdownTable({ data }: { data: Record<string, number> }) {
  return (
    <div className="rounded-2xl border border-white/10 overflow-hidden">
      <table className="w-full text-sm">
        <tbody>
          {Object.entries(data).map(([key, val], i, arr) => (
            <tr key={key} className={i !== arr.length - 1 ? "border-b border-white/5" : ""}>
              <td className="px-4 py-2 font-mono text-white/50 text-xs">{key}</td>
              <td className="px-4 py-2 text-white/80 text-xs text-right font-bold">{val}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

// ── InputField ────────────────────────────────────────────────────────────────
// Controlled text input with a label. All stat/context form fields use this.
// All values are stored as strings in state and converted to numbers on submit.

function InputField({
  label,
  value,
  onChange,
  placeholder,
}: {
  label:        string;
  value:        string;
  onChange:     (v: string) => void;
  placeholder?: string;
}) {
  return (
    <div>
      <p className="text-xs font-bold text-white/40 uppercase mb-1">{label}</p>
      <input
        type="text"
        value={value}
        placeholder={placeholder}
        onChange={(e) => onChange(e.target.value)}
        className="w-full rounded-2xl border border-white/10 bg-black/40 px-4 py-2.5 text-sm text-white outline-none placeholder:text-white/20 focus:border-white/30 transition"
      />
    </div>
  );
}

// ── Demo (main component) ─────────────────────────────────────────────────────
// Interactive API demo page. Calls POST /demo/value or /demo/bid (no API key
// required) and displays the response as a visual score bar + breakdown table.
//
// Form state is split by section (batter, pitcher, league, draft) to keep
// updates isolated. All numeric fields are stored as strings and converted with
// Number() on submit — this avoids controlled-input issues with partial numbers
// (e.g., "0." while the user is typing "0.281").

function Demo() {
  // Controls which endpoint is called and which form sections are shown
  const [mode,       setMode]       = useState<DemoMode>("value");
  const [playerType, setPlayerType] = useState<PlayerType>("batter");

  // Shared fields
  const [playerName, setPlayerName] = useState("Juan Soto");
  const [position,   setPosition]   = useState("OF");

  // Each stats section is a string-valued copy of the default constants.
  // Object.fromEntries converts { AB: 534, ... } → { AB: "534", ... }
  const [batter,  setBatter]  = useState(
    Object.fromEntries(Object.entries(DEFAULT_BATTER_STATS).map(([k, v]) => [k, String(v)]))
  );
  const [pitcher, setPitcher] = useState(
    Object.fromEntries(Object.entries(DEFAULT_PITCHER_STATS).map(([k, v]) => [k, String(v)]))
  );
  const [league,  setLeague]  = useState(
    Object.fromEntries(Object.entries(DEFAULT_LEAGUE).map(([k, v]) => [k, String(v)]))
  );
  // Draft context is only sent when mode === "bid"
  const [draft,   setDraft]   = useState(
    Object.fromEntries(Object.entries(DEFAULT_DRAFT).map(([k, v]) => [k, String(v)]))
  );

  // API call state
  const [result,  setResult]  = useState<Record<string, unknown> | null>(null);
  const [error,   setError]   = useState("");
  const [loading, setLoading] = useState(false);

  // ── handleSubmit ──────────────────────────────────────────────────────────
  // Builds the request body from form state, calls the appropriate /demo/*
  // endpoint, and stores the response in `result`. No API key is required —
  // /demo/* endpoints are auth-exempt (see api/main.py).

  const handleSubmit = async () => {
    setLoading(true);
    setError("");
    setResult(null);

    try {
      // Convert string form values to their correct numeric types
      const stats =
        playerType === "batter"
          ? {
              AB:  Number(batter.AB),  R:   Number(batter.R),   HR:  Number(batter.HR),
              RBI: Number(batter.RBI), SB:  Number(batter.SB),  CS:  Number(batter.CS),
              AVG: Number(batter.AVG),
            }
          : {
              IP:   Number(pitcher.IP),  W:    Number(pitcher.W),  SV: Number(pitcher.SV),
              K:    Number(pitcher.K),   ERA:  Number(pitcher.ERA), WHIP: Number(pitcher.WHIP),
            };

      const league_context = {
        league_size:  Number(league.league_size),
        roster_size:  Number(league.roster_size),
        total_budget: Number(league.total_budget),
      };

      const body: Record<string, unknown> = {
        player_name:    playerName,
        player_type:    playerType,
        position,
        stats,
        league_context,
      };

      // Append draft_context only for /demo/bid
      if (mode === "bid") {
        body.draft_context = {
          my_remaining_budget:       Number(draft.my_remaining_budget),
          my_remaining_roster_spots: Number(draft.my_remaining_roster_spots),
          // Parse comma-separated string into a string array, ignoring empty entries
          my_positions_filled:       draft.my_positions_filled
                                       .split(",")
                                       .map((s) => s.trim())
                                       .filter(Boolean),
          drafted_players_count:     Number(draft.drafted_players_count),
        };
      }

      const endpoint = mode === "value" ? "/demo/value" : "/demo/bid";
      const res = await fetch(`${API_URL}${endpoint}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });

      if (!res.ok) {
        // Surface the API's error detail (e.g., validation errors, 429 rate limit)
        const err = await res.json();
        setError(err.detail || "Something went wrong.");
        return;
      }

      setResult(await res.json());
    } catch {
      // Network-level failure (e.g., server unreachable, CORS blocked)
      setError("Failed to connect to the API.");
    } finally {
      setLoading(false);
    }
  };

  // Stat field keys for each player type — used to render InputField grids
  const batterFields  = ["AB", "R", "HR", "RBI", "SB", "CS", "AVG"] as const;
  const pitcherFields = ["IP", "W", "SV", "K", "ERA", "WHIP"] as const;

  return (
    <div className="relative min-h-screen flex flex-col items-center px-6 pt-24 pb-16">
      <div className="absolute inset-0 bg-gradient-to-b from-white/5 to-black pointer-events-none" />

      <div className="relative z-10 max-w-2xl w-full space-y-8">

        {/* Page header */}
        <div>
          <h1 className="text-4xl font-extrabold tracking-tight text-white mb-2">Try it out</h1>
          <p className="text-white/50 text-sm">
            Enter player stats and see the API response in real time.
          </p>
        </div>

        {/* Mode toggle: switches between /demo/value and /demo/bid.
            Resets result and error when switching to avoid showing stale data. */}
        <div className="flex gap-2">
          {(["value", "bid"] as DemoMode[]).map((m) => (
            <button
              key={m}
              onClick={() => { setMode(m); setResult(null); setError(""); }}
              className={`rounded-lg px-4 py-1.5 text-xs font-bold transition ${
                mode === m ? "bg-white text-black" : "bg-white/10 text-white/50 hover:bg-white/20"
              }`}
            >
              {m === "value" ? "POST /demo/value" : "POST /demo/bid"}
            </button>
          ))}
        </div>

        <div className="rounded-3xl border border-white/10 bg-white/5 p-6 space-y-5">

          {/* Player name + position */}
          <div className="grid grid-cols-2 gap-4">
            <InputField label="Player Name" value={playerName} onChange={setPlayerName} placeholder="e.g. Juan Soto" />
            <InputField label="Position"    value={position}   onChange={setPosition}   placeholder="e.g. OF" />
          </div>

          {/* Player type toggle: switches stat input fields between batter and pitcher sets */}
          <div>
            <p className="text-xs font-bold text-white/40 uppercase mb-2">Player Type</p>
            <div className="flex gap-2">
              {(["batter", "pitcher"] as PlayerType[]).map((t) => (
                <button
                  key={t}
                  onClick={() => setPlayerType(t)}
                  className={`rounded-lg px-4 py-1.5 text-xs font-bold transition ${
                    playerType === t ? "bg-white text-black" : "bg-white/10 text-white/50 hover:bg-white/20"
                  }`}
                >
                  {t.charAt(0).toUpperCase() + t.slice(1)}
                </button>
              ))}
            </div>
          </div>

          {/* Stats grid — renders batter or pitcher fields based on playerType */}
          <div>
            <p className="text-xs font-bold text-white/40 uppercase mb-3">Stats</p>
            <div className="grid grid-cols-3 gap-3">
              {playerType === "batter"
                ? batterFields.map((f) => (
                    <InputField
                      key={f} label={f} value={batter[f]}
                      onChange={(v) => setBatter((p) => ({ ...p, [f]: v }))}
                    />
                  ))
                : pitcherFields.map((f) => (
                    <InputField
                      key={f} label={f} value={pitcher[f]}
                      onChange={(v) => setPitcher((p) => ({ ...p, [f]: v }))}
                    />
                  ))}
            </div>
          </div>

          {/* League context — always shown for both modes */}
          <div>
            <p className="text-xs font-bold text-white/40 uppercase mb-3">League Context</p>
            <div className="grid grid-cols-3 gap-3">
              {(["league_size", "roster_size", "total_budget"] as const).map((f) => (
                <InputField
                  key={f} label={f} value={league[f]}
                  onChange={(v) => setLeague((p) => ({ ...p, [f]: v }))}
                />
              ))}
            </div>
          </div>

          {/* Draft context — conditionally rendered only when mode === "bid" */}
          {mode === "bid" && (
            <div>
              <p className="text-xs font-bold text-white/40 uppercase mb-3">Draft Context</p>
              <div className="grid grid-cols-2 gap-3">
                <InputField
                  label="my_remaining_budget"
                  value={draft.my_remaining_budget}
                  onChange={(v) => setDraft((p) => ({ ...p, my_remaining_budget: v }))}
                />
                <InputField
                  label="my_remaining_roster_spots"
                  value={draft.my_remaining_roster_spots}
                  onChange={(v) => setDraft((p) => ({ ...p, my_remaining_roster_spots: v }))}
                />
                <InputField
                  label="my_positions_filled (comma separated)"
                  value={draft.my_positions_filled}
                  onChange={(v) => setDraft((p) => ({ ...p, my_positions_filled: v }))}
                  placeholder="e.g. C, SP, OF"
                />
                <InputField
                  label="drafted_players_count"
                  value={draft.drafted_players_count}
                  onChange={(v) => setDraft((p) => ({ ...p, drafted_players_count: v }))}
                />
              </div>
            </div>
          )}

          {/* Submit button — disabled while a request is in flight */}
          <button
            onClick={handleSubmit}
            disabled={loading}
            className="w-full rounded-xl bg-white py-3 text-sm font-extrabold text-black transition hover:bg-white/90 active:scale-95 disabled:opacity-40"
          >
            {loading ? "Loading..." : "Submit"}
          </button>

          {/* Error message — shown when the API returns an error or fetch fails */}
          {error && (
            <div className="rounded-2xl border border-red-500/30 bg-red-500/10 p-4 text-sm text-red-300">
              {error}
            </div>
          )}

          {/* Result panel — rendered only after a successful API response.
              Uses an IIFE to extract typed fields from the raw result object,
              then renders each section conditionally based on whether the field exists.
              /demo/value returns player_value + value_breakdown (no recommended_bid).
              /demo/bid   returns both + recommended_bid + bid_breakdown. */}
          {result && (() => {
            const playerValue    = typeof result.player_value    === "number" ? result.player_value    : null;
            const recommendedBid = typeof result.recommended_bid === "number" ? result.recommended_bid : null;
            const valueBreakdown = result.value_breakdown !== null && typeof result.value_breakdown === "object"
                                    ? result.value_breakdown as Record<string, number> : null;
            const bidBreakdown   = result.bid_breakdown   !== null && typeof result.bid_breakdown   === "object"
                                    ? result.bid_breakdown   as Record<string, number> : null;

            return (
              <div className="space-y-4">
                <p className="text-xs font-bold text-white/40 uppercase">Response</p>

                {/* Animated score bar for player_value */}
                {playerValue    !== null && <ScoreBar value={playerValue} />}

                {/* Bid amount display — only present in /demo/bid responses */}
                {recommendedBid !== null && (
                  <div className="rounded-2xl border border-white/10 bg-white/5 p-4 flex items-center justify-between">
                    <span className="text-xs font-bold text-white/40 uppercase">recommended_bid</span>
                    <span className="text-2xl font-extrabold text-white">${recommendedBid}</span>
                  </div>
                )}

                {/* Breakdown tables */}
                {valueBreakdown !== null && (
                  <div>
                    <p className="text-xs font-bold text-white/40 uppercase mb-2">value_breakdown</p>
                    <BreakdownTable data={valueBreakdown} />
                  </div>
                )}
                {bidBreakdown !== null && (
                  <div>
                    <p className="text-xs font-bold text-white/40 uppercase mb-2">bid_breakdown</p>
                    <BreakdownTable data={bidBreakdown} />
                  </div>
                )}

                {/* Raw JSON — always shown as a fallback reference */}
                <div>
                  <p className="text-xs font-bold text-white/40 uppercase mb-2">Raw JSON</p>
                  <pre className="rounded-2xl border border-white/10 bg-black/40 p-4 text-xs text-white/60 whitespace-pre-wrap break-all overflow-auto">
                    {JSON.stringify(result, null, 2)}
                  </pre>
                </div>
              </div>
            );
          })()}
        </div>
      </div>
    </div>
  );
}

export default Demo;