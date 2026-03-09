import { useState } from "react";

type Tab = "batter" | "pitcher";

interface SchemaRow {
  field: string;
  type: string;
  description: string;
}

interface EndpointCardProps {
  method: string;
  path: string;
  description: string;
  batterRequest: object;
  pitcherRequest: object;
  batterResponse: object;
  pitcherResponse: object;
  schema: SchemaRow[];
}

function EndpointCard({
  method,
  path,
  description,
  batterRequest,
  pitcherRequest,
  batterResponse,
  pitcherResponse,
  schema,
}: EndpointCardProps) {
  const [tab, setTab] = useState<Tab>("batter");

  return (
    <div className="rounded-3xl border border-white/10 bg-white/5 p-6 space-y-6">
      {/* Title */}
      <div className="flex items-center gap-3">
        <span className="rounded-lg bg-white/10 px-3 py-1 text-xs font-bold text-white">
          {method}
        </span>
        <span className="text-white font-bold">{path}</span>
      </div>
      <p className="text-sm text-white/50">{description}</p>

      {/* Batter / Pitcher toggle */}
      <div className="flex gap-2">
        {(["batter", "pitcher"] as Tab[]).map((t) => (
          <button
            key={t}
            onClick={() => setTab(t)}
            className={`rounded-lg px-4 py-1.5 text-xs font-bold transition ${
              tab === t
                ? "bg-white text-black"
                : "bg-white/10 text-white/50 hover:bg-white/20"
            }`}
          >
            {t.charAt(0).toUpperCase() + t.slice(1)}
          </button>
        ))}
      </div>

      {/* Request */}
      <div>
        <p className="text-xs font-bold text-white/40 uppercase mb-2">Request</p>
        <pre className="rounded-2xl border border-white/10 bg-black/40 p-4 text-sm text-white/80 whitespace-pre-wrap break-all overflow-auto">
          {JSON.stringify(tab === "batter" ? batterRequest : pitcherRequest, null, 2)}
        </pre>
      </div>

      {/* Response */}
      <div>
        <p className="text-xs font-bold text-white/40 uppercase mb-2">Response</p>
        <pre className="rounded-2xl border border-white/10 bg-black/40 p-4 text-sm text-white/80 whitespace-pre-wrap break-all overflow-auto">
          {JSON.stringify(tab === "batter" ? batterResponse : pitcherResponse, null, 2)}
        </pre>
      </div>

      {/* Schema table */}
      <div>
        <p className="text-xs font-bold text-white/40 uppercase mb-3">Request Fields</p>
        <div className="rounded-2xl border border-white/10 overflow-hidden">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-white/10 bg-white/5">
                <th className="text-left px-4 py-2 text-xs font-bold text-white/40 uppercase">Field</th>
                <th className="text-left px-4 py-2 text-xs font-bold text-white/40 uppercase">Type</th>
                <th className="text-left px-4 py-2 text-xs font-bold text-white/40 uppercase">Description</th>
              </tr>
            </thead>
            <tbody>
              {schema.map((row, i) => (
                <tr key={row.field} className={i !== schema.length - 1 ? "border-b border-white/5" : ""}>
                  <td className="px-4 py-2 font-mono text-white/80 text-xs">{row.field}</td>
                  <td className="px-4 py-2 text-white/40 text-xs">{row.type}</td>
                  <td className="px-4 py-2 text-white/50 text-xs">{row.description}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      {/* Required header */}
      <div>
        <p className="text-xs font-bold text-white/40 uppercase mb-2">Required Header</p>
        <pre className="rounded-2xl border border-white/10 bg-black/40 p-4 text-sm text-white/80">
          X-API-Key: your_api_key_here
        </pre>
      </div>
    </div>
  );
}

// ── Data ─────────────────────────────────────────────────────────────────────

const VALUE_BATTER_REQUEST = {
  player_name: "Juan Soto",
  player_type: "batter",
  position: "OF",
  stats: { AB: 534, R: 113, HR: 37, RBI: 97, SB: 23, CS: 4, AVG: 0.281 },
  league_context: { league_size: 12, roster_size: 23, total_budget: 260 },
};

const VALUE_PITCHER_REQUEST = {
  player_name: "Zack Wheeler",
  player_type: "pitcher",
  position: "SP",
  stats: { IP: 200.0, W: 15, SV: 0, K: 220, ERA: 2.95, WHIP: 1.05 },
  league_context: { league_size: 12, roster_size: 23, total_budget: 260 },
};

const VALUE_BATTER_RESPONSE = {
  player_name: "Juan Soto",
  player_type: "batter",
  player_value: 87.4,
  value_breakdown: { stat_score: 82.6, position_bonus: 0.0, risk_penalty: 0.0 },
};

const VALUE_PITCHER_RESPONSE = {
  player_name: "Zack Wheeler",
  player_type: "pitcher",
  player_value: 79.2,
  value_breakdown: { stat_score: 74.1, position_bonus: 3.3, risk_penalty: 0.0 },
};

const BID_BATTER_REQUEST = {
  player_name: "Juan Soto",
  player_type: "batter",
  position: "OF",
  stats: { AB: 534, R: 113, HR: 37, RBI: 97, SB: 23, CS: 4, AVG: 0.281 },
  league_context: { league_size: 12, roster_size: 23, total_budget: 260 },
  draft_context: {
    my_remaining_budget: 198,
    my_remaining_roster_spots: 17,
    my_positions_filled: ["C", "SP"],
    drafted_players_count: 87,
  },
};

const BID_PITCHER_REQUEST = {
  player_name: "Zack Wheeler",
  player_type: "pitcher",
  position: "SP",
  stats: { IP: 200.0, W: 15, SV: 0, K: 220, ERA: 2.95, WHIP: 1.05 },
  league_context: { league_size: 12, roster_size: 23, total_budget: 260 },
  draft_context: {
    my_remaining_budget: 198,
    my_remaining_roster_spots: 17,
    my_positions_filled: ["OF", "1B"],
    drafted_players_count: 87,
  },
};

const BID_BATTER_RESPONSE = {
  player_name: "Juan Soto",
  player_type: "batter",
  player_value: 87.4,
  recommended_bid: 42,
  bid_breakdown: {
    base_price: 40.4,
    scarcity_adjustment: 0.0,
    draft_adjustment: 1.6,
    max_spendable: 181,
  },
};

const BID_PITCHER_RESPONSE = {
  player_name: "Zack Wheeler",
  player_type: "pitcher",
  player_value: 79.2,
  recommended_bid: 29,
  bid_breakdown: {
    base_price: 27.1,
    scarcity_adjustment: 1.4,
    draft_adjustment: 0.5,
    max_spendable: 181,
  },
};

const VALUE_SCHEMA: SchemaRow[] = [
  { field: "player_name", type: "string", description: "Player full name" },
  { field: "player_type", type: '"batter" | "pitcher"', description: "Player type" },
  { field: "position", type: "string", description: 'Position (e.g. "OF", "SP", "C")' },
  { field: "stats.AB", type: "int", description: "At bats (batter only)" },
  { field: "stats.R", type: "int", description: "Runs (batter only)" },
  { field: "stats.HR", type: "int", description: "Home runs (batter only)" },
  { field: "stats.RBI", type: "int", description: "Runs batted in (batter only)" },
  { field: "stats.SB", type: "int", description: "Stolen bases (batter only)" },
  { field: "stats.CS", type: "int", description: "Caught stealing (batter only)" },
  { field: "stats.AVG", type: "float", description: "Batting average (batter only)" },
  { field: "stats.IP", type: "float", description: "Innings pitched (pitcher only)" },
  { field: "stats.W", type: "int", description: "Wins (pitcher only)" },
  { field: "stats.SV", type: "int", description: "Saves (pitcher only)" },
  { field: "stats.K", type: "int", description: "Strikeouts (pitcher only)" },
  { field: "stats.ERA", type: "float", description: "Earned run average (pitcher only)" },
  { field: "stats.WHIP", type: "float", description: "Walks + hits per inning (pitcher only)" },
  { field: "league_context.league_size", type: "int", description: "Number of teams in the league" },
  { field: "league_context.roster_size", type: "int", description: "Roster spots per team" },
  { field: "league_context.total_budget", type: "int", description: "Auction budget per team ($)" },
];

const BID_SCHEMA: SchemaRow[] = [
  ...VALUE_SCHEMA,
  { field: "draft_context.my_remaining_budget", type: "int", description: "Your remaining auction budget ($)" },
  { field: "draft_context.my_remaining_roster_spots", type: "int", description: "Roster spots you still need to fill" },
  { field: "draft_context.my_positions_filled", type: "string[]", description: "Positions you have already filled" },
  { field: "draft_context.drafted_players_count", type: "int", description: "Total players drafted across all teams so far" },
];

const TIERS = [
  { label: "Elite", range: "80 – 100", color: "text-yellow-400", bg: "bg-yellow-400/10 border-yellow-400/20" },
  { label: "Strong", range: "60 – 79", color: "text-green-400", bg: "bg-green-400/10 border-green-400/20" },
  { label: "Average", range: "40 – 59", color: "text-blue-400", bg: "bg-blue-400/10 border-blue-400/20" },
  { label: "Below Average", range: "20 – 39", color: "text-orange-400", bg: "bg-orange-400/10 border-orange-400/20" },
  { label: "Replacement Level", range: "0 – 19", color: "text-red-400", bg: "bg-red-400/10 border-red-400/20" },
];

// ── Page ──────────────────────────────────────────────────────────────────────

function Endpoints() {
  return (
    <div className="relative min-h-screen flex flex-col items-center px-6 pt-24 pb-16">
      <div className="absolute inset-0 bg-gradient-to-b from-white/5 to-black pointer-events-none" />

      <div className="relative z-10 max-w-2xl w-full space-y-16">

        {/* Header */}
        <div>
          <h1 className="text-4xl font-extrabold tracking-tight text-white mb-2">
            Endpoints
          </h1>
          <p className="text-white/50 text-sm">
            All endpoints except <code className="text-white/70">/health</code> and{" "}
            <code className="text-white/70">/demo</code> require an API Key.
            Scoring format: <span className="text-white/70">Rotisserie 5x5 (Roto 5x5)</span>.
          </p>
        </div>

        {/* /player/value */}
        <EndpointCard
          method="POST"
          path="/player/value"
          description="Returns player_value (0.0 ~ 100.0) based on Roto 5x5 z-score valuation. Supports both batters and pitchers."
          batterRequest={VALUE_BATTER_REQUEST}
          pitcherRequest={VALUE_PITCHER_REQUEST}
          batterResponse={VALUE_BATTER_RESPONSE}
          pitcherResponse={VALUE_PITCHER_RESPONSE}
          schema={VALUE_SCHEMA}
        />

        {/* /player/bid */}
        <EndpointCard
          method="POST"
          path="/player/bid"
          description="Returns player_value and recommended_bid (integer $) adjusted for positional scarcity and real-time draft context."
          batterRequest={BID_BATTER_REQUEST}
          pitcherRequest={BID_PITCHER_REQUEST}
          batterResponse={BID_BATTER_RESPONSE}
          pitcherResponse={BID_PITCHER_RESPONSE}
          schema={BID_SCHEMA}
        />

      </div>
    </div>
  );
}

export default Endpoints;