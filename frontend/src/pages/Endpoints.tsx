import { useState } from "react";

// ── Types ─────────────────────────────────────────────────────────────────────

type Method = "GET" | "POST";

interface ParamRow {
  name:        string;
  type:        string;
  required:    boolean;
  description: string;
}

interface EndpointCardProps {
  method:         Method;
  path:           string;
  description:    string;
  authRequired:   boolean;
  requestUrl:     string;           // example request URL shown in the card
  params?:        ParamRow[];       // query or path params
  requestBody?:   object;           // POST body example (optional)
  requestFields?: ParamRow[];       // POST body field table (optional)
  response:       object;           // response example
  notes?:         string[];         // extra notes shown below response
  allowedColumns?: string[];        // full set of requestable columns for ?columns= param
  basicColumns?:   string[];        // columns returned by default (no detail=full / no columns param)
  fullColumns?:    string[];        // columns added when detail=full (for /{player_id} endpoints)
}

// ── Badge helpers ─────────────────────────────────────────────────────────────

function MethodBadge({ method }: { method: Method }) {
  const color =
    method === "GET"
      ? "bg-emerald-500/20 text-emerald-300 border border-emerald-500/30"
      : "bg-blue-500/20 text-blue-300 border border-blue-500/30";
  return (
    <span className={`rounded-md px-2.5 py-1 text-xs font-bold tracking-widest ${color}`}>
      {method}
    </span>
  );
}

function AuthBadge({ required }: { required: boolean }) {
  return required ? (
    <span className="rounded-md px-2.5 py-1 text-xs font-semibold bg-amber-500/15 text-amber-300 border border-amber-500/25">
      AUTH REQUIRED
    </span>
  ) : (
    <span className="rounded-md px-2.5 py-1 text-xs font-semibold bg-white/5 text-white/30 border border-white/10">
      NO AUTH
    </span>
  );
}

// ── ParamTable ────────────────────────────────────────────────────────────────

function ParamTable({ rows, title }: { rows: ParamRow[]; title: string }) {
  return (
    <div>
      <p className="text-xs font-bold text-white/40 uppercase tracking-widest mb-2">
        {title}
      </p>
      <div className="rounded-xl border border-white/10 overflow-hidden">
        <table className="w-full text-xs">
          <thead>
            <tr className="border-b border-white/10 bg-white/5">
              <th className="text-left px-4 py-2 text-white/40 font-bold uppercase tracking-wider">Name</th>
              <th className="text-left px-4 py-2 text-white/40 font-bold uppercase tracking-wider">Type</th>
              <th className="text-left px-4 py-2 text-white/40 font-bold uppercase tracking-wider">Required</th>
              <th className="text-left px-4 py-2 text-white/40 font-bold uppercase tracking-wider">Description</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row, i) => (
              <tr key={row.name} className={i !== rows.length - 1 ? "border-b border-white/5" : ""}>
                <td className="px-4 py-2.5 font-mono text-white/80">{row.name}</td>
                <td className="px-4 py-2.5 text-white/40">{row.type}</td>
                <td className="px-4 py-2.5">
                  {row.required ? (
                    <span className="text-amber-400 font-semibold">Yes</span>
                  ) : (
                    <span className="text-white/25">No</span>
                  )}
                </td>
                <td className="px-4 py-2.5 text-white/50">{row.description}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

// ── DefaultAndAllowedColumns ──────────────────────────────────────────────────
// Shows default columns (returned when columns param is omitted) and
// the full set of allowed column values for the ?columns= param.

function DefaultAndAllowedColumns({
  basicColumns,
  allowedColumns,
}: {
  basicColumns:   string[];
  allowedColumns: string[];
}) {
  // Columns available via ?columns= but not in the default set
  const extraColumns = allowedColumns.filter((c) => !basicColumns.includes(c));

  return (
    <div className="space-y-4">
      <div>
        <p className="text-xs font-bold text-white/40 uppercase tracking-widest mb-2">
          Default Columns <span className="text-white/20 normal-case font-normal">(columns param omitted)</span>
        </p>
        <div className="flex flex-wrap gap-1.5">
          {basicColumns.map((col) => (
            <span
              key={col}
              className="rounded-md px-2 py-0.5 text-xs font-mono bg-white/5 text-white/60 border border-white/10"
            >
              {col}
            </span>
          ))}
        </div>
      </div>
      {extraColumns.length > 0 && (
        <div>
          <p className="text-xs font-bold text-white/40 uppercase tracking-widest mb-2">
            Additional Requestable Columns <span className="text-white/20 normal-case font-normal">(via ?columns=)</span>
          </p>
          <div className="flex flex-wrap gap-1.5">
            {extraColumns.map((col) => (
              <span
                key={col}
                className="rounded-md px-2 py-0.5 text-xs font-mono bg-blue-500/10 text-blue-300/70 border border-blue-500/20"
              >
                {col}
              </span>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

// ── DetailColumns ─────────────────────────────────────────────────────────────
// Shows basic vs full column split for /{player_id} endpoints.

function DetailColumns({
  basicColumns,
  fullColumns,
}: {
  basicColumns: string[];
  fullColumns:  string[];
}) {
  // Columns added exclusively when detail=full
  const extraColumns = fullColumns.filter((c) => !basicColumns.includes(c));

  return (
    <div className="space-y-4">
      {/* Basic (default) */}
      <div>
        <p className="text-xs font-bold text-white/40 uppercase tracking-widest mb-2">
          Default Columns <span className="text-white/20 normal-case font-normal">(detail omitted)</span>
        </p>
        <div className="flex flex-wrap gap-1.5">
          {basicColumns.map((col) => (
            <span
              key={col}
              className="rounded-md px-2 py-0.5 text-xs font-mono bg-white/5 text-white/60 border border-white/10"
            >
              {col}
            </span>
          ))}
        </div>
      </div>

      {/* Extra columns added by detail=full */}
      {extraColumns.length > 0 && (
        <div>
          <p className="text-xs font-bold text-white/40 uppercase tracking-widest mb-2">
            Additional Columns <span className="text-white/20 normal-case font-normal">(detail=full only)</span>
          </p>
          <div className="flex flex-wrap gap-1.5">
            {extraColumns.map((col) => (
              <span
                key={col}
                className="rounded-md px-2 py-0.5 text-xs font-mono bg-emerald-500/10 text-emerald-300/70 border border-emerald-500/20"
              >
                {col}
              </span>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}


function EndpointCard({
  method,
  path,
  description,
  authRequired,
  requestUrl,
  params,
  requestBody,
  requestFields,
  response,
  notes,
  allowedColumns,
  basicColumns,
  fullColumns,
}: EndpointCardProps) {
  const [showRequest, setShowRequest] = useState(true);

  return (
    <div className="rounded-2xl border border-white/10 bg-white/[0.03] overflow-hidden">

      {/* Header */}
      <div className="px-6 py-5 border-b border-white/10 bg-white/[0.02]">
        <div className="flex flex-wrap items-center gap-2 mb-3">
          <MethodBadge method={method} />
          <code className="text-white font-bold text-sm tracking-tight">{path}</code>
          <div className="ml-auto">
            <AuthBadge required={authRequired} />
          </div>
        </div>
        <p className="text-sm text-white/50 leading-relaxed">{description}</p>
      </div>

      {/* Body */}
      <div className="px-6 py-5 space-y-6">

        {/* Request URL example */}
        <div>
          <p className="text-xs font-bold text-white/40 uppercase tracking-widest mb-2">
            Request Example
          </p>
          <pre className="rounded-xl border border-white/10 bg-black/40 p-4 text-xs text-white/75 overflow-auto leading-relaxed">
            {requestUrl}
          </pre>
        </div>
        {params && params.length > 0 && (
          <ParamTable rows={params} title="Parameters" />
        )}

        {/* Allowed columns for ?columns= param — shows default + extra requestable */}
        {allowedColumns && basicColumns && !fullColumns && (
          <DefaultAndAllowedColumns
            basicColumns={basicColumns}
            allowedColumns={allowedColumns}
          />
        )}

        {/* Basic vs full column split for /{player_id} endpoints */}
        {basicColumns && fullColumns && (
          <DetailColumns basicColumns={basicColumns} fullColumns={fullColumns} />
        )}

        {/* Request body — POST only */}
        {requestBody && (
          <div>
            {requestFields && requestFields.length > 0 && (
              <div className="mb-4">
                <ParamTable rows={requestFields} title="Request Body Fields" />
              </div>
            )}
            <p className="text-xs font-bold text-white/40 uppercase tracking-widest mb-2">
              Request Body Example
            </p>
            <pre className="rounded-xl border border-white/10 bg-black/40 p-4 text-xs text-white/75 overflow-auto leading-relaxed">
              {JSON.stringify(requestBody, null, 2)}
            </pre>
          </div>
        )}

        {/* Response */}
        <div>
          {requestBody && (
            <div className="flex gap-2 mb-3">
              <button
                onClick={() => setShowRequest(false)}
                className={`rounded-lg px-3 py-1 text-xs font-bold transition ${
                  !showRequest ? "bg-white text-black" : "bg-white/10 text-white/50 hover:bg-white/15"
                }`}
              >
                Response
              </button>
            </div>
          )}
          <p className="text-xs font-bold text-white/40 uppercase tracking-widest mb-2">
            Response Example
          </p>
          <pre className="rounded-xl border border-white/10 bg-black/40 p-4 text-xs text-white/75 overflow-auto leading-relaxed">
            {JSON.stringify(response, null, 2)}
          </pre>
        </div>

        {/* Notes */}
        {notes && notes.length > 0 && (
          <div className="space-y-1.5">
            {notes.map((note, i) => (
              <p key={i} className="text-xs text-white/35 leading-relaxed">
                • {note}
              </p>
            ))}
          </div>
        )}

        {/* Auth header reminder */}
        {authRequired && (
          <div>
            <p className="text-xs font-bold text-white/40 uppercase tracking-widest mb-2">
              Required Header
            </p>
            <pre className="rounded-xl border border-white/10 bg-black/40 p-4 text-xs text-amber-300/70">
              X-API-Key: your_api_key_here
            </pre>
          </div>
        )}

      </div>
    </div>
  );
}

// ── Static Data ───────────────────────────────────────────────────────────────

// GET /health
const HEALTH_RESPONSE = { status: "ok" };

// POST /player/bid/id
const BID_ID_REQUEST = {
  player_id: 592450,
  league_context: {
    league_size: 12,
    roster_size: 23,
    total_budget: 260,
  },
  draft_context: {
    my_remaining_budget: 198,
    my_remaining_roster_spots: 17,
    drafted_players_count: 87,
    my_roster: [
      { player_name: "Freddie Freeman", position: "1B" },
      { player_name: "Manny Machado",   position: "3B" },
    ],
    opponent_rosters: null,
    opponent_budgets: null,
  },
};

const BID_ID_RESPONSE = {
  player_name:     "Aaron Judge",
  player_type:     "batter",
  position:        "OF",
  team:            "NYY",
  stats: {
    ab: 466, r: 96, hr: 58, rbi: 144, sb: 10, cs: 3, avg: 0.267,
  },
  injury_status:   null,
  depth_order:     1,
  player_value:    93.2,
  recommended_bid: 51,
  bid_breakdown: {
    base_price:           47.8,
    scarcity_adjustment:  2.1,
    draft_adjustment:     1.3,
    max_spendable:        181,
    max_competitor_budget: 181,
  },
};

const BID_ID_REQUEST_FIELDS: ParamRow[] = [
  { name: "player_id",                              type: "int",                 required: true,  description: "MLB stable integer player ID" },
  { name: "league_context.league_size",             type: "int",                 required: true,  description: "Number of teams in the league" },
  { name: "league_context.roster_size",             type: "int",                 required: true,  description: "Roster spots per team" },
  { name: "league_context.total_budget",            type: "int",                 required: true,  description: "Auction budget per team ($)" },
  { name: "draft_context.my_remaining_budget",      type: "int",                 required: true,  description: "Your remaining auction budget ($)" },
  { name: "draft_context.my_remaining_roster_spots",type: "int",                 required: true,  description: "Roster spots you still need to fill" },
  { name: "draft_context.drafted_players_count",    type: "int",                 required: true,  description: "Total players drafted across all teams so far" },
  { name: "draft_context.my_roster",                type: "RosterEntry[] | null",required: false, description: "Your current roster [{player_name, position}]; overrides my_remaining_roster_spots if provided" },
  { name: "draft_context.opponent_rosters",         type: "object | null",       required: false, description: "Opponent roster map for dynamic scarcity bonus (ALG-03)" },
  { name: "draft_context.opponent_budgets",         type: "object | null",       required: false, description: "Remaining budget per opponent for bid cap (ALG-04)" },
];

// GET /players/batters
const BATTERS_RESPONSE = {
  league: "AL",
  count:  2,
  batters: [
    { name: "Aaron Judge",   position: "OF", team: "NYY", player_id: 592450, ab: 466, r: 96,  hr: 58, rbi: 144, sb: 10, cs: 3, avg: 0.267, player_value: 93.2 },
    { name: "Gunnar Henderson", position: "SS", team: "BAL", player_id: 683002, ab: 491, r: 96, hr: 37, rbi: 100, sb: 26, cs: 3, avg: 0.281, player_value: 84.5 },
  ],
};

const BATTERS_PARAMS: ParamRow[] = [
  { name: "league",  type: "string", required: true,  description: '"AL" or "NL"' },
  { name: "columns", type: "string", required: false, description: "Comma-separated column names. Omit for default set. Example: hr,rbi,avg,player_value" },
];

// GET /players/batters/{player_id}
const BATTER_DETAIL_RESPONSE = {
  league: "AL",
  detail: "basic",
  batter: {
    name: "Aaron Judge", position: "OF", team: "NYY", player_id: 592450,
    ab: 466, r: 96, h: 125, single: 55, double: 10, triple: 2,
    hr: 58, rbi: 144, bb: 133, k: 143, sb: 10, cs: 3,
    avg: 0.267, obp: 0.458, slg: 0.686,
    injury_status: null, depth_order: 1, player_value: 93.2,
  },
};

const BATTER_DETAIL_PARAMS: ParamRow[] = [
  { name: "player_id", type: "int (path)",    required: true,  description: "MLB integer player ID" },
  { name: "detail",    type: "string (query)", required: false, description: 'Pass "full" to include biographical columns (birth_date, height, weight, etc.)' },
];

// GET /players/pitchers
const PITCHERS_RESPONSE = {
  league: "AL",
  count:  2,
  pitchers: [
    { name: "Gerrit Cole", position: "SP", team: "NYY", player_id: 543037, w: 15, l: 4, sv: 0, so: 222, era: 2.63, whip: 0.98, ip: 209.0, player_value: 88.1 },
    { name: "Emmanuel Clase", position: "RP", team: "CLE", player_id: 669373, w: 3, l: 4, sv: 44, so: 78, era: 1.37, whip: 0.87, ip: 72.1, player_value: 76.4 },
  ],
};

const PITCHERS_PARAMS: ParamRow[] = [
  { name: "league",  type: "string", required: true,  description: '"AL" or "NL"' },
  { name: "columns", type: "string", required: false, description: "Comma-separated column names. Omit for default set. Example: w,sv,era,whip,player_value" },
];

// GET /players/pitchers/{player_id}
const PITCHER_DETAIL_RESPONSE = {
  league: "AL",
  detail: "basic",
  pitcher: {
    name: "Gerrit Cole", position: "SP", team: "NYY", player_id: 543037,
    w: 15, l: 4, sv: 0, so: 222, era: 2.63, whip: 0.98, ip: 209.0,
    g: 33, gs: 33, war: 6.1, fip: 2.71,
    h: 148, r: 65, er: 61, hr: 19, bb: 57, hbp: 5, bf: 817,
    era_plus: 166, h9: 6.4, hr9: 0.8, bb9: 2.5, so9: 9.6, so_bb: 3.89,
    injury_status: null, depth_order: 1, player_value: 88.1,
  },
};

const PITCHER_DETAIL_PARAMS: ParamRow[] = [
  { name: "player_id", type: "int (path)",    required: true,  description: "MLB integer player ID" },
  { name: "detail",    type: "string (query)", required: false, description: 'Pass "full" to include biographical columns (birth_date, height, weight, etc.)' },
];

// ── Column Constants (mirrored from api/routers/players_data.py) ──────────────

const BATTER_ALLOWED_COLUMNS = [
  "name", "position", "team", "player_id",
  "primary_number", "birth_date", "birth_city", "birth_country",
  "height", "weight", "current_age", "mlb_debut_date", "bat_side", "pitch_hand",
  "ab", "r", "h", "single", "double", "triple",
  "hr", "rbi", "bb", "k", "sb", "cs", "avg", "obp", "slg",
  "injury_status", "depth_order", "player_value",
];

const BATTER_BASIC_COLUMNS = [
  "name", "position", "team", "player_id",
  "ab", "r", "h", "single", "double", "triple",
  "hr", "rbi", "bb", "k", "sb", "cs", "avg", "obp", "slg",
  "injury_status", "depth_order", "player_value",
];

const BATTER_FULL_DETAIL_COLUMNS = [
  "name", "position", "team", "player_id",
  "primary_number", "birth_date", "birth_city", "birth_country",
  "height", "weight", "current_age", "mlb_debut_date", "bat_side", "pitch_hand",
  "ab", "r", "h", "single", "double", "triple",
  "hr", "rbi", "bb", "k", "sb", "cs", "avg", "obp", "slg",
  "injury_status", "depth_order", "player_value",
];

const PITCHER_ALLOWED_COLUMNS = [
  "name", "position", "team", "player_id",
  "primary_number", "birth_date", "birth_city", "birth_country",
  "height", "weight", "current_age", "mlb_debut_date", "pitch_hand",
  "w", "l", "sv", "so", "era", "whip", "ip",
  "g", "gs", "war", "fip",
  "h", "r", "er", "hr", "bb", "hbp", "bf",
  "era_plus", "h9", "hr9", "bb9", "so9", "so_bb",
  "injury_status", "depth_order", "player_value",
];

const PITCHER_BASIC_COLUMNS = [
  "name", "position", "team", "player_id",
  "w", "l", "sv", "so", "era", "whip", "ip",
  "g", "gs", "war", "fip",
  "h", "r", "er", "hr", "bb", "hbp", "bf",
  "era_plus", "h9", "hr9", "bb9", "so9", "so_bb",
  "injury_status", "depth_order", "player_value",
];

const PITCHER_FULL_DETAIL_COLUMNS = [
  "name", "position", "team", "player_id",
  "primary_number", "birth_date", "birth_city", "birth_country",
  "height", "weight", "current_age", "mlb_debut_date", "pitch_hand",
  "w", "l", "sv", "so", "era", "whip", "ip",
  "g", "gs", "war", "fip",
  "h", "r", "er", "hr", "bb", "hbp", "bf",
  "era_plus", "h9", "hr9", "bb9", "so9", "so_bb",
  "injury_status", "depth_order", "player_value",
];

// ── Endpoints Page ────────────────────────────────────────────────────────────

function Endpoints() {
  return (
    <div className="relative min-h-screen flex flex-col items-center px-6 pt-24 pb-20">

      {/* Background */}
      <div className="absolute inset-0 bg-gradient-to-b from-white/5 to-black pointer-events-none" />

      <div className="relative z-10 max-w-3xl w-full space-y-12">

        {/* Page header */}
        <div className="space-y-3">
          <h1 className="text-4xl font-extrabold tracking-tight text-white">
            API Reference
          </h1>
          <p className="text-white/50 text-sm leading-relaxed">
            Base URL: <code className="text-white/70 bg-white/5 px-1.5 py-0.5 rounded">https://api.ppa-dun.site</code>
            <br />
            Endpoints marked <span className="text-amber-300 font-semibold">AUTH REQUIRED</span> need an{" "}
            <code className="text-white/70">X-API-Key</code> header.
            Scoring format: <span className="text-white/70">Rotisserie 5×5 (Roto 5×5)</span>.
          </p>
        </div>

        {/* Section: System */}
        <section className="space-y-4">
          <h2 className="text-xs font-bold text-white/30 uppercase tracking-widest border-b border-white/10 pb-2">
            System
          </h2>
          <EndpointCard
            method="GET"
            path="/health"
            description="Returns service health status. Use this to verify the API is reachable before making authenticated requests."
            authRequired={false}
            requestUrl="GET https://api.ppa-dun.site/health"
            response={HEALTH_RESPONSE}
          />
        </section>

        {/* Section: Player Valuation */}
        <section className="space-y-4">
          <h2 className="text-xs font-bold text-white/30 uppercase tracking-widest border-b border-white/10 pb-2">
            Player Valuation
          </h2>
          <EndpointCard
            method="POST"
            path="/player/bid/id"
            description="Given an MLB player_id plus league and draft context, fetches the player's stats from our database and returns a recommended auction bid amount. player_value is read from the stored DB value (not recalculated on the fly)."
            authRequired={true}
            requestUrl="POST https://api.ppa-dun.site/player/bid/id"
            requestBody={BID_ID_REQUEST}
            requestFields={BID_ID_REQUEST_FIELDS}
            response={BID_ID_RESPONSE}
            notes={[
              "Searches batters first (batters_al → batters_nl), then pitchers (pitchers_al → pitchers_nl).",
              "Returns 404 if no player matches the given player_id.",
              "Providing opponent_rosters enables dynamic positional scarcity bonus (ALG-03).",
              "Providing opponent_budgets caps recommended_bid at the max competitor budget (ALG-04).",
            ]}
          />
        </section>

        {/* Section: Player Data */}
        <section className="space-y-4">
          <h2 className="text-xs font-bold text-white/30 uppercase tracking-widest border-b border-white/10 pb-2">
            Player Data
          </h2>

          {/* /players/batters */}
          <EndpointCard
            method="GET"
            path="/players/batters"
            description="Returns all batters in the specified league. Optionally filter to specific stat columns. Useful for building draft boards or populating player lists."
            authRequired={true}
            requestUrl={`GET https://api.ppa-dun.site/players/batters?league=AL\nGET https://api.ppa-dun.site/players/batters?league=AL&columns=hr,rbi,avg,player_value`}
            params={BATTERS_PARAMS}
            response={BATTERS_RESPONSE}
            basicColumns={BATTER_BASIC_COLUMNS}
            allowedColumns={BATTER_ALLOWED_COLUMNS}
            notes={[
              'league is required. Returns 400 if missing or not "AL" / "NL".',
              "columns is optional. If omitted, a default stat set is returned (name, position, team, player_id, core stats, player_value).",
              "name is always included regardless of the columns param.",
            ]}
          />

          {/* /players/batters/{player_id} */}
          <EndpointCard
            method="GET"
            path="/players/batters/{player_id}"
            description="Returns a single batter's record identified by MLB player_id. Searches batters_al first, then batters_nl as fallback."
            authRequired={true}
            requestUrl={`GET https://api.ppa-dun.site/players/batters/592450\nGET https://api.ppa-dun.site/players/batters/592450?detail=full`}
            params={BATTER_DETAIL_PARAMS}
            response={BATTER_DETAIL_RESPONSE}
            basicColumns={BATTER_BASIC_COLUMNS}
            fullColumns={BATTER_FULL_DETAIL_COLUMNS}
            notes={[
              "Returns 400 if detail param is provided but not \"full\".",
              "Returns 404 if player_id is not found in any batter table.",
            ]}
          />

          {/* /players/pitchers */}
          <EndpointCard
            method="GET"
            path="/players/pitchers"
            description="Returns all pitchers in the specified league. Optionally filter to specific stat columns."
            authRequired={true}
            requestUrl={`GET https://api.ppa-dun.site/players/pitchers?league=AL\nGET https://api.ppa-dun.site/players/pitchers?league=NL&columns=w,sv,era,whip,player_value`}
            params={PITCHERS_PARAMS}
            response={PITCHERS_RESPONSE}
            basicColumns={PITCHER_BASIC_COLUMNS}
            allowedColumns={PITCHER_ALLOWED_COLUMNS}
            notes={[
              'league is required. Returns 400 if missing or not "AL" / "NL".',
              "columns is optional. If omitted, a default stat set is returned (name, position, team, player_id, core pitching stats, player_value).",
              "name is always included regardless of the columns param.",
            ]}
          />

          {/* /players/pitchers/{player_id} */}
          <EndpointCard
            method="GET"
            path="/players/pitchers/{player_id}"
            description="Returns a single pitcher's record identified by MLB player_id. Searches pitchers_al first, then pitchers_nl as fallback."
            authRequired={true}
            requestUrl={`GET https://api.ppa-dun.site/players/pitchers/543037\nGET https://api.ppa-dun.site/players/pitchers/543037?detail=full`}
            params={PITCHER_DETAIL_PARAMS}
            response={PITCHER_DETAIL_RESPONSE}
            basicColumns={PITCHER_BASIC_COLUMNS}
            fullColumns={PITCHER_FULL_DETAIL_COLUMNS}
            notes={[
              "Returns 400 if detail param is provided but not \"full\".",
              "Returns 404 if player_id is not found in any pitcher table.",
            ]}
          />
        </section>

      </div>
    </div>
  );
}

export default Endpoints;