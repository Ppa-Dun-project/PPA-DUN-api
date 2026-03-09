import { useState } from "react";

const API_URL = import.meta.env.VITE_API_URL || "http://localhost:8000";

type PlayerType = "batter" | "pitcher";
type DemoMode = "value" | "bid";

// ── Default form values ───────────────────────────────────────────────────────

const DEFAULT_BATTER_STATS = { AB: 534, R: 113, HR: 37, RBI: 97, SB: 23, CS: 4, AVG: 0.281 };
const DEFAULT_PITCHER_STATS = { IP: 200.0, W: 15, SV: 0, K: 220, ERA: 2.95, WHIP: 1.05 };
const DEFAULT_LEAGUE = { league_size: 12, roster_size: 23, total_budget: 260 };
const DEFAULT_DRAFT = { my_remaining_budget: 198, my_remaining_roster_spots: 17, my_positions_filled: "C, SP", drafted_players_count: 87 };

// ── Score bar ─────────────────────────────────────────────────────────────────

function ScoreBar({ value }: { value: number }) {
  const pct = Math.max(0, Math.min(100, value));
  const color =
    pct >= 80 ? "bg-yellow-400" :
    pct >= 60 ? "bg-green-400" :
    pct >= 40 ? "bg-blue-400" :
    pct >= 20 ? "bg-orange-400" : "bg-red-400";
  const label =
    pct >= 80 ? "Elite" :
    pct >= 60 ? "Strong" :
    pct >= 40 ? "Average" :
    pct >= 20 ? "Below Average" : "Replacement Level";

  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between">
        <span className="text-xs font-bold text-white/40 uppercase">player_value</span>
        <span className={`text-xs font-bold ${color.replace("bg-", "text-")}`}>{label}</span>
      </div>
      <div className="relative h-3 w-full rounded-full bg-white/10 overflow-hidden">
        <div
          className={`h-full rounded-full transition-all duration-700 ${color}`}
          style={{ width: `${pct}%` }}
        />
      </div>
      <div className="text-right text-2xl font-extrabold text-white">{value.toFixed(1)}</div>
    </div>
  );
}

// ── Breakdown table ───────────────────────────────────────────────────────────

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

// ── Input field ───────────────────────────────────────────────────────────────

function InputField({
  label,
  value,
  onChange,
  placeholder,
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
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

// ── Main component ────────────────────────────────────────────────────────────

function Demo() {
  const [mode, setMode] = useState<DemoMode>("value");
  const [playerType, setPlayerType] = useState<PlayerType>("batter");

  // Shared fields
  const [playerName, setPlayerName] = useState("Juan Soto");
  const [position, setPosition] = useState("OF");

  // Batter stats
  const [batter, setBatter] = useState(
    Object.fromEntries(Object.entries(DEFAULT_BATTER_STATS).map(([k, v]) => [k, String(v)]))
  );
  // Pitcher stats
  const [pitcher, setPitcher] = useState(
    Object.fromEntries(Object.entries(DEFAULT_PITCHER_STATS).map(([k, v]) => [k, String(v)]))
  );
  // League context
  const [league, setLeague] = useState(
    Object.fromEntries(Object.entries(DEFAULT_LEAGUE).map(([k, v]) => [k, String(v)]))
  );
  // Draft context (bid only)
  const [draft, setDraft] = useState(
    Object.fromEntries(Object.entries(DEFAULT_DRAFT).map(([k, v]) => [k, String(v)]))
  );

  const [result, setResult] = useState<Record<string, unknown> | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  const handleSubmit = async () => {
    setLoading(true);
    setError("");
    setResult(null);

    try {
      const stats =
        playerType === "batter"
          ? {
              AB: Number(batter.AB), R: Number(batter.R), HR: Number(batter.HR),
              RBI: Number(batter.RBI), SB: Number(batter.SB), CS: Number(batter.CS),
              AVG: Number(batter.AVG),
            }
          : {
              IP: Number(pitcher.IP), W: Number(pitcher.W), SV: Number(pitcher.SV),
              K: Number(pitcher.K), ERA: Number(pitcher.ERA), WHIP: Number(pitcher.WHIP),
            };

      const league_context = {
        league_size: Number(league.league_size),
        roster_size: Number(league.roster_size),
        total_budget: Number(league.total_budget),
      };

      const body: Record<string, unknown> = {
        player_name: playerName,
        player_type: playerType,
        position,
        stats,
        league_context,
      };

      if (mode === "bid") {
        body.draft_context = {
          my_remaining_budget: Number(draft.my_remaining_budget),
          my_remaining_roster_spots: Number(draft.my_remaining_roster_spots),
          my_positions_filled: draft.my_positions_filled.split(",").map((s) => s.trim()).filter(Boolean),
          drafted_players_count: Number(draft.drafted_players_count),
        };
      }

      const endpoint = mode === "value" ? "/demo/value" : "/demo/bid";
      const res = await fetch(`${API_URL}${endpoint}`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify(body),
      });

      if (!res.ok) {
        const err = await res.json();
        setError(err.detail || "Something went wrong.");
        return;
      }

      setResult(await res.json());
    } catch {
      setError("Failed to connect to the API.");
    } finally {
      setLoading(false);
    }
  };

  const batterFields = ["AB", "R", "HR", "RBI", "SB", "CS", "AVG"] as const;
  const pitcherFields = ["IP", "W", "SV", "K", "ERA", "WHIP"] as const;

  return (
    <div className="relative min-h-screen flex flex-col items-center px-6 pt-24 pb-16">
      <div className="absolute inset-0 bg-gradient-to-b from-white/5 to-black pointer-events-none" />

      <div className="relative z-10 max-w-2xl w-full space-y-8">

        {/* Header */}
        <div>
          <h1 className="text-4xl font-extrabold tracking-tight text-white mb-2">Try it out</h1>
          <p className="text-white/50 text-sm">
            Enter player stats and see the API response in real time.
          </p>
        </div>

        {/* Mode toggle */}
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

          {/* Player info */}
          <div className="grid grid-cols-2 gap-4">
            <InputField label="Player Name" value={playerName} onChange={setPlayerName} placeholder="e.g. Juan Soto" />
            <InputField label="Position" value={position} onChange={setPosition} placeholder="e.g. OF" />
          </div>

          {/* Player type toggle */}
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

          {/* Stats */}
          <div>
            <p className="text-xs font-bold text-white/40 uppercase mb-3">Stats</p>
            <div className="grid grid-cols-3 gap-3">
              {playerType === "batter"
                ? batterFields.map((f) => (
                    <InputField key={f} label={f} value={batter[f]} onChange={(v) => setBatter((p) => ({ ...p, [f]: v }))} />
                  ))
                : pitcherFields.map((f) => (
                    <InputField key={f} label={f} value={pitcher[f]} onChange={(v) => setPitcher((p) => ({ ...p, [f]: v }))} />
                  ))}
            </div>
          </div>

          {/* League context */}
          <div>
            <p className="text-xs font-bold text-white/40 uppercase mb-3">League Context</p>
            <div className="grid grid-cols-3 gap-3">
              {(["league_size", "roster_size", "total_budget"] as const).map((f) => (
                <InputField key={f} label={f} value={league[f]} onChange={(v) => setLeague((p) => ({ ...p, [f]: v }))} />
              ))}
            </div>
          </div>

          {/* Draft context (bid only) */}
          {mode === "bid" && (
            <div>
              <p className="text-xs font-bold text-white/40 uppercase mb-3">Draft Context</p>
              <div className="grid grid-cols-2 gap-3">
                <InputField label="my_remaining_budget" value={draft.my_remaining_budget} onChange={(v) => setDraft((p) => ({ ...p, my_remaining_budget: v }))} />
                <InputField label="my_remaining_roster_spots" value={draft.my_remaining_roster_spots} onChange={(v) => setDraft((p) => ({ ...p, my_remaining_roster_spots: v }))} />
                <InputField label="my_positions_filled (comma separated)" value={draft.my_positions_filled} onChange={(v) => setDraft((p) => ({ ...p, my_positions_filled: v }))} placeholder="e.g. C, SP, OF" />
                <InputField label="drafted_players_count" value={draft.drafted_players_count} onChange={(v) => setDraft((p) => ({ ...p, drafted_players_count: v }))} />
              </div>
            </div>
          )}

          {/* Submit */}
          <button
            onClick={handleSubmit}
            disabled={loading}
            className="w-full rounded-xl bg-white py-3 text-sm font-extrabold text-black transition hover:bg-white/90 active:scale-95 disabled:opacity-40"
          >
            {loading ? "Loading..." : "Submit"}
          </button>

          {/* Error */}
          {error && (
            <div className="rounded-2xl border border-red-500/30 bg-red-500/10 p-4 text-sm text-red-300">
              {error}
            </div>
          )}

          {/* Result */}
          {result && (() => {
            const playerValue = typeof result.player_value === "number" ? result.player_value : null;
            const recommendedBid = typeof result.recommended_bid === "number" ? result.recommended_bid : null;
            const valueBreakdown = result.value_breakdown !== null && typeof result.value_breakdown === "object" ? result.value_breakdown as Record<string, number> : null;
            const bidBreakdown = result.bid_breakdown !== null && typeof result.bid_breakdown === "object" ? result.bid_breakdown as Record<string, number> : null;

            return (
              <div className="space-y-4">
                <p className="text-xs font-bold text-white/40 uppercase">Response</p>

                {playerValue !== null && <ScoreBar value={playerValue} />}

                {recommendedBid !== null && (
                  <div className="rounded-2xl border border-white/10 bg-white/5 p-4 flex items-center justify-between">
                    <span className="text-xs font-bold text-white/40 uppercase">recommended_bid</span>
                    <span className="text-2xl font-extrabold text-white">${recommendedBid}</span>
                  </div>
                )}

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