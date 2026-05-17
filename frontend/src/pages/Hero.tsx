// Hero.tsx — Landing page of the PPA-DUN dashboard.
// Divided into two main sections:
//   1. Hero section      : product tagline and short description
//   2. Documentation section : three-tab interactive panel covering
//        Tab 1 — Player Data        (what data is available and how it stays current)
//        Tab 2 — Player Value       (FVARz algorithm, STEP A ~ H)
//        Tab 3 — Recommended Bid    (bid calculation, Step 1 ~ 8)

import { useState } from "react";

// Tab identifiers for the three documentation sections
type DocTab = "data" | "value" | "bid";

// ── TabButton ─────────────────────────────────────────────────────────────────
// Reusable tab button that highlights when active.

function TabButton({
  label,
  active,
  onClick,
}: {
  label: string;
  active: boolean;
  onClick: () => void;
}) {
  return (
    <button
      onClick={onClick}
      className={`rounded-xl px-5 py-2 text-sm font-bold transition ${
        active
          ? "bg-white text-black"
          : "bg-white/10 text-white/50 hover:bg-white/20"
      }`}
    >
      {label}
    </button>
  );
}

// ── StepCard ──────────────────────────────────────────────────────────────────
// Renders a single numbered step block used across all three tabs.

function StepCard({
  label,
  children,
}: {
  label: string;
  children: React.ReactNode;
}) {
  return (
    <div className="space-y-3">
      <p className="text-xs font-bold text-white/40 uppercase">{label}</p>
      {children}
    </div>
  );
}

// ── Tab 1: Player Data ────────────────────────────────────────────────────────
// Written from the API consumer's perspective:
// what player data is available, what fields it contains, and how current it is.

function PlayerDataTab() {
  return (
    <div className="space-y-6">

      <p className="text-sm text-white/60 leading-relaxed">
        PPA-DUN maintains a database of MLB players for the{" "}
        <span className="text-white/80">2025 season</span>, covering both leagues and all positions.
        Player records are sourced from the{" "}
        <span className="text-white/80">MLB Stats API</span> and{" "}
        <span className="text-white/80">Baseball Reference</span>, and are automatically
        refreshed every day so that injury status, depth chart position, and{" "}
        <code className="text-white/70">player_value</code> always reflect the latest information.
      </p>

      {/* Coverage */}
      <div className="rounded-3xl border border-white/10 bg-white/5 p-6 space-y-6">
        <div>
          <p className="text-xs font-bold text-white/40 uppercase mb-1">Coverage</p>
          <p className="text-white text-lg font-extrabold">What players are available?</p>
        </div>

        <p className="text-sm text-white/60 leading-relaxed">
          All active MLB players are split by league and player type into four separate groups.
          You can query any group via the <code className="text-white/70">GET /players/batters</code> and{" "}
          <code className="text-white/70">GET /players/pitchers</code> endpoints,
          or look up a single player by their stable MLB{" "}
          <code className="text-white/70">player_id</code>.
        </p>

        <div className="rounded-2xl border border-white/10 overflow-hidden">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-white/10 bg-white/5">
                <th className="text-left px-4 py-2 text-xs font-bold text-white/40 uppercase">Group</th>
                <th className="text-left px-4 py-2 text-xs font-bold text-white/40 uppercase">league param</th>
              </tr>
            </thead>
            <tbody>
              {[
                { group: "AL Batters",  param: "league=AL  (batters endpoint)" },
                { group: "NL Batters",  param: "league=NL  (batters endpoint)" },
                { group: "AL Pitchers", param: "league=AL  (pitchers endpoint)" },
                { group: "NL Pitchers", param: "league=NL  (pitchers endpoint)" },
              ].map((row, i, arr) => (
                <tr key={row.group} className={i !== arr.length - 1 ? "border-b border-white/5" : ""}>
                  <td className="px-4 py-2 text-white/80 text-xs font-bold">{row.group}</td>
                  <td className="px-4 py-2 font-mono text-white/50 text-xs">{row.param}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      {/* What fields are included */}
      <div className="rounded-3xl border border-white/10 bg-white/5 p-6 space-y-6">
        <div>
          <p className="text-xs font-bold text-white/40 uppercase mb-1">Fields</p>
          <p className="text-white text-lg font-extrabold">What data does each player record contain?</p>
        </div>

        <p className="text-sm text-white/60 leading-relaxed">
          Each player record includes identity info, season stats, real-time status fields,
          and a pre-computed <code className="text-white/70">player_value</code>.
          By default, endpoints return a standard set of fields.
          Pass a <code className="text-white/70">columns</code> query parameter to request only the fields you need,
          or <code className="text-white/70">?detail=full</code> on single-player endpoints for the complete record.
        </p>

        {/* Batter fields */}
        <div className="space-y-2">
          <p className="text-xs font-bold text-white/40 uppercase">Batter fields</p>
          <div className="rounded-2xl border border-white/10 overflow-hidden">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-white/10 bg-white/5">
                  <th className="text-left px-4 py-2 text-xs font-bold text-white/40 uppercase">Category</th>
                  <th className="text-left px-4 py-2 text-xs font-bold text-white/40 uppercase">Fields</th>
                </tr>
              </thead>
              <tbody>
                {[
                  { cat: "Identity",     fields: "name, position, team, player_id" },
                  { cat: "Roto 5x5",     fields: "ab, r, hr, rbi, sb, cs, avg" },
                  { cat: "Extended",     fields: "h, single, double, triple, bb, k, obp, slg" },
                  { cat: "Real-time",    fields: "injury_status, depth_order" },
                  { cat: "Valuation",    fields: "player_value  (0.0 ~ 100.0, updated daily)" },
                  { cat: "Profile",      fields: "current_age, birth_date, height, weight, bat_side, mlb_debut_date  (detail=full)" },
                ].map((row, i, arr) => (
                  <tr key={row.cat} className={i !== arr.length - 1 ? "border-b border-white/5" : ""}>
                    <td className="px-4 py-2 text-white/80 text-xs font-bold">{row.cat}</td>
                    <td className="px-4 py-2 font-mono text-white/50 text-xs">{row.fields}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>

        {/* Pitcher fields */}
        <div className="space-y-2">
          <p className="text-xs font-bold text-white/40 uppercase">Pitcher fields</p>
          <div className="rounded-2xl border border-white/10 overflow-hidden">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-white/10 bg-white/5">
                  <th className="text-left px-4 py-2 text-xs font-bold text-white/40 uppercase">Category</th>
                  <th className="text-left px-4 py-2 text-xs font-bold text-white/40 uppercase">Fields</th>
                </tr>
              </thead>
              <tbody>
                {[
                  { cat: "Identity",     fields: "name, position, team, player_id" },
                  { cat: "Roto 5x5",     fields: "w, sv, so, era, whip, ip" },
                  { cat: "Extended",     fields: "g, gs, l, h, r, er, hr, bb, hbp, bf, war, fip, era_plus, h9, hr9, bb9, so9, so_bb" },
                  { cat: "Real-time",    fields: "injury_status, depth_order" },
                  { cat: "Valuation",    fields: "player_value  (0.0 ~ 100.0, updated daily)" },
                  { cat: "Profile",      fields: "current_age, birth_date, height, weight, pitch_hand, mlb_debut_date  (detail=full)" },
                ].map((row, i, arr) => (
                  <tr key={row.cat} className={i !== arr.length - 1 ? "border-b border-white/5" : ""}>
                    <td className="px-4 py-2 text-white/80 text-xs font-bold">{row.cat}</td>
                    <td className="px-4 py-2 font-mono text-white/50 text-xs">{row.fields}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      </div>

      {/* How current is the data */}
      <div className="rounded-3xl border border-white/10 bg-white/5 p-6 space-y-4">
        <div>
          <p className="text-xs font-bold text-white/40 uppercase mb-1">Freshness</p>
          <p className="text-white text-lg font-extrabold">How current is the data?</p>
        </div>

        <p className="text-sm text-white/60 leading-relaxed">
          Three fields are automatically refreshed every day at{" "}
          <span className="text-white/80">3:00 AM ET</span>.
          Season stats (AB, HR, ERA, etc.) reflect the Baseball Reference snapshot
          used at initialization and are not updated mid-season — they represent
          the statistical baseline used for valuation.
        </p>

        <div className="rounded-2xl border border-white/10 overflow-hidden">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-white/10 bg-white/5">
                <th className="text-left px-4 py-2 text-xs font-bold text-white/40 uppercase">Field</th>
                <th className="text-left px-4 py-2 text-xs font-bold text-white/40 uppercase">Update Frequency</th>
                <th className="text-left px-4 py-2 text-xs font-bold text-white/40 uppercase">Source</th>
              </tr>
            </thead>
            <tbody>
              {[
                { field: "injury_status", freq: "Daily (3 AM ET)", source: "ESPN injury feed" },
                { field: "depth_order",   freq: "Daily (3 AM ET)", source: "Depth chart feed" },
                { field: "player_value",  freq: "Daily (3 AM ET)", source: "FVARz algorithm (recomputed after above updates)" },
                { field: "Season stats",  freq: "Static (season snapshot)", source: "Baseball Reference" },
              ].map((row, i, arr) => (
                <tr key={row.field} className={i !== arr.length - 1 ? "border-b border-white/5" : ""}>
                  <td className="px-4 py-2 font-mono text-white/80 text-xs">{row.field}</td>
                  <td className="px-4 py-2 text-white/50 text-xs">{row.freq}</td>
                  <td className="px-4 py-2 text-white/40 text-xs">{row.source}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      {/* Data sources */}
      <div className="space-y-3">
        <p className="text-xs font-bold text-white/40 uppercase">Data Sources</p>
        <div className="rounded-2xl border border-white/10 overflow-hidden">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-white/10 bg-white/5">
                <th className="text-left px-4 py-2 text-xs font-bold text-white/40 uppercase">Source</th>
                <th className="text-left px-4 py-2 text-xs font-bold text-white/40 uppercase">Used for</th>
              </tr>
            </thead>
            <tbody>
              {[
                { src: "MLB Stats API (statsapi.mlb.com)", use: "Player identity, team, league, stable player_id" },
                { src: "Baseball Reference",               use: "Season stats (batting, pitching)" },
                { src: "ESPN injury feed",                 use: "injury_status (Day-To-Day, 10-Day IL, 60-Day IL, etc.)" },
                { src: "Depth chart feed",                 use: "depth_order (1 = starter, 2 = backup, …)" },
              ].map((row, i, arr) => (
                <tr key={row.src} className={i !== arr.length - 1 ? "border-b border-white/5" : ""}>
                  <td className="px-4 py-2 text-white/80 text-xs font-bold">{row.src}</td>
                  <td className="px-4 py-2 text-white/50 text-xs">{row.use}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

    </div>
  );
}

// ── Tab 2: Player Value (FVARz) ───────────────────────────────────────────────

function PlayerValueTab() {
  return (
    <div className="space-y-6">

      <div>
        <p className="text-xs font-bold text-white/40 uppercase mb-1">Output field</p>
        <p className="text-white text-lg font-extrabold">
          player_value{" "}
          <span className="text-white/40 font-normal text-sm">float · 0.0 ~ 100.0</span>
        </p>
      </div>

      <p className="text-sm text-white/60 leading-relaxed">
        Based on <span className="text-white/80">Roto 5x5</span> scoring.
        Measures how valuable a player is relative to the league-average player pool,
        normalized to a 0–100 scale. A value of <span className="text-white/80">50</span> means
        perfectly average; <span className="text-white/80">80+</span> means elite across multiple categories.
        Implementation: <code className="text-white/70">api/services/player.py → compute_player_value()</code>
      </p>

      {/* STEP A */}
      <div className="rounded-3xl border border-white/10 bg-white/5 p-6 space-y-6">

        <StepCard label="STEP A — Stat Blending (current season + 3-year average)">
          <p className="text-sm text-white/60 leading-relaxed">
            Blends current season stats and 3-year average stats at a{" "}
            <span className="text-white/80">6:4 ratio</span>.
            If a 3-year average field is missing, the current season value is used in its place.
          </p>
          <pre className="rounded-2xl border border-white/10 bg-black/40 p-4 text-sm text-white/80 overflow-auto">
{`blended = (0.6 × current) + (0.4 × avg_3yr)

Batter blend targets:   R, HR, RBI, SB, AVG
  AB, CS — pass-through (risk penalty only)

Pitcher blend targets:  W, SV, K, ERA, WHIP
  IP     — pass-through (risk penalty only)`}
          </pre>
        </StepCard>

        <StepCard label="STEP B — Age Adjustment (age_factor)">
          <p className="text-sm text-white/60 leading-relaxed">
            Multiplies blended value by <code className="text-white/70">age_factor</code>.
            Rate stats (AVG, ERA, WHIP) also receive the age factor.
            If age is not provided, factor defaults to 1.00.
          </p>
          <div className="rounded-2xl border border-white/10 overflow-hidden">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-white/10 bg-white/5">
                  <th className="text-left px-4 py-2 text-xs font-bold text-white/40 uppercase">Age</th>
                  <th className="text-left px-4 py-2 text-xs font-bold text-white/40 uppercase">Factor</th>
                  <th className="text-left px-4 py-2 text-xs font-bold text-white/40 uppercase">Reason</th>
                </tr>
              </thead>
              <tbody>
                {[
                  { age: "≤ 25",    factor: "1.05", reason: "Growth potential" },
                  { age: "26 ~ 30", factor: "1.00", reason: "Prime years" },
                  { age: "31 ~ 33", factor: "0.95", reason: "Early decline" },
                  { age: "≥ 34",    factor: "0.90", reason: "Decline phase" },
                  { age: "N/A",     factor: "1.00", reason: "No adjustment" },
                ].map((row, i, arr) => (
                  <tr key={row.age} className={i !== arr.length - 1 ? "border-b border-white/5" : ""}>
                    <td className="px-4 py-2 text-white/80 text-xs">{row.age}</td>
                    <td className="px-4 py-2 font-mono text-white/60 text-xs">{row.factor}</td>
                    <td className="px-4 py-2 text-white/40 text-xs">{row.reason}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </StepCard>

        <StepCard label="STEP C — Depth Chart Adjustment (depth_factor)">
          <p className="text-sm text-white/60 leading-relaxed">
            Multiplies blended value by <code className="text-white/70">depth_factor</code>.
            Rate stats (AVG, ERA, WHIP) and AB/CS/IP are excluded from depth factor.
            If depth_order is not provided, factor defaults to 1.00.
          </p>
          <div className="rounded-2xl border border-white/10 overflow-hidden">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-white/10 bg-white/5">
                  <th className="text-left px-4 py-2 text-xs font-bold text-white/40 uppercase">depth_order</th>
                  <th className="text-left px-4 py-2 text-xs font-bold text-white/40 uppercase">Factor</th>
                </tr>
              </thead>
              <tbody>
                {[
                  { order: "1 — Starter",      factor: "1.00" },
                  { order: "2 — Near-starter",  factor: "0.90" },
                  { order: "3 — Platoon",       factor: "0.75" },
                  { order: "4+ — Deep bench",   factor: "0.60" },
                  { order: "N/A",               factor: "1.00" },
                ].map((row, i, arr) => (
                  <tr key={row.order} className={i !== arr.length - 1 ? "border-b border-white/5" : ""}>
                    <td className="px-4 py-2 text-white/80 text-xs">{row.order}</td>
                    <td className="px-4 py-2 font-mono text-white/60 text-xs">{row.factor}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <pre className="rounded-2xl border border-white/10 bg-black/40 p-4 text-sm text-white/80 overflow-auto">
{`// Rate stats (AVG, ERA, WHIP)
adjusted = blended × age_factor

// Counting stats (R, HR, RBI, SB, W, SV, K, ...)
adjusted = blended × age_factor × depth_factor

// Risk penalty only (AB, CS, IP) — unchanged
adjusted = blended`}
          </pre>
        </StepCard>

        <StepCard label="STEP E — Z-Score Summation (z_total)">
          <p className="text-sm text-white/60 leading-relaxed">
            Sums z-scores across all 5 Roto categories.
            Baseline (mean, std) values are dynamically computed from the{" "}
            <code className="text-white/70">league_baselines</code> table.
            ERA and WHIP are negated because lower values are better.
          </p>
          <pre className="rounded-2xl border border-white/10 bg-black/40 p-4 text-sm text-white/80 overflow-auto">
{`z = (value - mean) / std

// Batters — all higher is better
z_total = z(R) + z(HR) + z(RBI) + z(SB) + z(AVG)

// Pitchers — ERA and WHIP are negated
z_total = z(W) + z(SV) + z(K) - z(ERA) - z(WHIP)`}
          </pre>
        </StepCard>

        <StepCard label="STEP F — Positional Scarcity Bonus (position_bonus)">
          <p className="text-sm text-white/60 leading-relaxed">
            A bonus added to <code className="text-white/70">z_total</code>, expressed in z-score units.
            When calling <code className="text-white/70">/player/value</code>: uses static values.
            When calling <code className="text-white/70">/player/bid</code> with{" "}
            <code className="text-white/70">opponent_rosters</code>: uses dynamic bonus (capped at 2× base).
          </p>
          <div className="rounded-2xl border border-white/10 overflow-hidden">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-white/10 bg-white/5">
                  <th className="text-left px-4 py-2 text-xs font-bold text-white/40 uppercase">Position</th>
                  <th className="text-left px-4 py-2 text-xs font-bold text-white/40 uppercase">base_bonus</th>
                </tr>
              </thead>
              <tbody>
                {[
                  { pos: "C",        bonus: "+1.5" },
                  { pos: "SS",       bonus: "+0.8" },
                  { pos: "RP / CL",  bonus: "+0.6" },
                  { pos: "2B",       bonus: "+0.5" },
                  { pos: "SP",       bonus: "+0.4" },
                  { pos: "3B",       bonus: "+0.3" },
                  { pos: "1B / OF / DH", bonus: "0.0" },
                ].map((row, i, arr) => (
                  <tr key={row.pos} className={i !== arr.length - 1 ? "border-b border-white/5" : ""}>
                    <td className="px-4 py-2 text-white/80 text-xs">{row.pos}</td>
                    <td className="px-4 py-2 font-mono text-white/60 text-xs">{row.bonus}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <pre className="rounded-2xl border border-white/10 bg-black/40 p-4 text-sm text-white/80 overflow-auto">
{`// Dynamic bonus (when opponent_rosters is provided)
remaining_ratio = (total_eligible - total_drafted_at_pos) / total_eligible
dynamic_bonus   = base_bonus / remaining_ratio
dynamic_bonus   = min(dynamic_bonus, base_bonus × 2)   // capped at 2x base`}
          </pre>
        </StepCard>

        <StepCard label="STEP G — Risk Penalty (risk_penalty)">
          <p className="text-sm text-white/60 leading-relaxed">
            All conditions are evaluated independently and summed.
          </p>
          <div className="rounded-2xl border border-white/10 overflow-hidden">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-white/10 bg-white/5">
                  <th className="text-left px-4 py-2 text-xs font-bold text-white/40 uppercase">Condition</th>
                  <th className="text-left px-4 py-2 text-xs font-bold text-white/40 uppercase">Penalty</th>
                </tr>
              </thead>
              <tbody>
                {[
                  { cond: "Batter · AB < 300",                 pen: "−0.5" },
                  { cond: "Batter · CS / (SB + CS) > 35%",     pen: "−0.2" },
                  { cond: "Pitcher · IP < 100",                pen: "−0.5" },
                  { cond: "Pitcher · ERA > 4.50",              pen: "−0.3" },
                  { cond: "Injury · Day-To-Day",               pen: "−0.1" },
                  { cond: "Injury · 10-Day IL",                pen: "−0.3" },
                  { cond: "Injury · 15-Day IL",                pen: "−0.4" },
                  { cond: "Injury · 60-Day IL",                pen: "−0.7" },
                  { cond: "Injury · Out",                      pen: "−1.0" },
                ].map((row, i, arr) => (
                  <tr key={row.cond} className={i !== arr.length - 1 ? "border-b border-white/5" : ""}>
                    <td className="px-4 py-2 text-white/80 text-xs">{row.cond}</td>
                    <td className="px-4 py-2 font-mono text-red-400 text-xs">{row.pen}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </StepCard>

        <StepCard label="STEP H — Normalization (0.0 ~ 100.0)">
          <p className="text-sm text-white/60 leading-relaxed">
            The raw score is scaled symmetrically around zero using a fixed{" "}
            <code className="text-white/70">RAW_MAX</code> of 12.0, then clipped to 0–100.
            An average player (raw_score ≈ 0) maps to{" "}
            <span className="text-white/80">player_value ≈ 50.0</span>.
          </p>
          <pre className="rounded-2xl border border-white/10 bg-black/40 p-4 text-sm text-white/80 overflow-auto">
{`raw_score    = z_total + position_bonus - risk_penalty
z_max        = 10.0
RAW_MAX      = 12.0   // z_max + max position bonus

player_value = clip((raw_score + RAW_MAX) / (RAW_MAX × 2) × 100, 0, 100)`}
          </pre>
        </StepCard>

        {/* Full Formula Summary */}
        <StepCard label="Full Formula Summary">
          <pre className="rounded-2xl border border-white/10 bg-black/40 p-4 text-sm text-white/80 overflow-auto">
{`blended      = 0.6 × current + 0.4 × avg_3yr
adjusted     = blended × age_factor × depth_factor   // rate stats: × age_factor only
z_total      = sum of z(category)                    // ERA, WHIP sign-reversed
raw_score    = z_total + position_bonus - risk_penalty
player_value = clip((raw_score + 12.0) / 24.0 × 100, 0, 100)`}
          </pre>
        </StepCard>

      </div>

      {/* Value Tier Table */}
      <div className="space-y-3">
        <p className="text-xs font-bold text-white/40 uppercase">Value Tiers</p>
        <div className="rounded-2xl border border-white/10 overflow-hidden">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-white/10 bg-white/5">
                <th className="text-left px-4 py-2 text-xs font-bold text-white/40 uppercase">Tier</th>
                <th className="text-left px-4 py-2 text-xs font-bold text-white/40 uppercase">Range</th>
                <th className="text-left px-4 py-2 text-xs font-bold text-white/40 uppercase">Meaning</th>
              </tr>
            </thead>
            <tbody>
              {[
                { label: "Elite",         range: "80 – 100", color: "text-yellow-400", meaning: "Top-tier player, draft early" },
                { label: "Strong",        range: "60 – 79",  color: "text-green-400",  meaning: "Reliable starter, solid value" },
                { label: "Average",       range: "40 – 59",  color: "text-blue-400",   meaning: "League-average contributor" },
                { label: "Below Average", range: "20 – 39",  color: "text-orange-400", meaning: "Situational or streaky value" },
                { label: "Replacement",   range: "0 – 19",   color: "text-red-400",    meaning: "Waiver wire / bench depth only" },
              ].map((tier, i, arr) => (
                <tr key={tier.label} className={i !== arr.length - 1 ? "border-b border-white/5" : ""}>
                  <td className={`px-4 py-2 font-bold text-xs ${tier.color}`}>{tier.label}</td>
                  <td className="px-4 py-2 text-white/50 text-xs">{tier.range}</td>
                  <td className="px-4 py-2 text-white/40 text-xs">{tier.meaning}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

    </div>
  );
}

// ── Tab 3: Recommended Bid ────────────────────────────────────────────────────

function RecommendedBidTab() {
  return (
    <div className="space-y-6">

      <div>
        <p className="text-xs font-bold text-white/40 uppercase mb-1">Output field</p>
        <p className="text-white text-lg font-extrabold">
          recommended_bid{" "}
          <span className="text-white/40 font-normal text-sm">integer · dollar amount ($)</span>
        </p>
      </div>

      <p className="text-sm text-white/60 leading-relaxed">
        Translates <span className="text-white/80">player_value</span> into a concrete dollar bid
        for auction drafts. Accounts for remaining budget, draft progress, positional scarcity,
        and opponent budgets. Always at least <span className="text-white/80">$1</span> and never
        exceeds what you can safely spend.
        Implementation: <code className="text-white/70">api/services/player.py → compute_recommended_bid()</code>
      </p>

      <div className="rounded-3xl border border-white/10 bg-white/5 p-6 space-y-6">

        <StepCard label="Step 1 — Compute player_value">
          <p className="text-sm text-white/60 leading-relaxed">
            Computes <code className="text-white/70">player_value</code> (0.0 ~ 100.0) using the FVARz algorithm.
            Internally reuses <code className="text-white/70">compute_player_value()</code> when called via{" "}
            <code className="text-white/70">/player/bid</code>.
          </p>
        </StepCard>

        <StepCard label="Step 2 — Compute base_price">
          <p className="text-sm text-white/60 leading-relaxed">
            Converts <code className="text-white/70">player_value</code> into a raw dollar amount
            proportional to the total auction budget.
          </p>
          <pre className="rounded-2xl border border-white/10 bg-black/40 p-4 text-sm text-white/80 overflow-auto">
{`base_price = (player_value / 100) × total_budget

// Example: player_value=75, total_budget=260
// → base_price = 195.0`}
          </pre>
        </StepCard>

        <StepCard label="Step 3 — Dynamic scarcity check (early-exit)">
          <p className="text-sm text-white/60 leading-relaxed">
            When <code className="text-white/70">opponent_rosters</code> is provided, counts how many
            opponents have already drafted the target position.
            If <code className="text-white/70">competitors_at_pos == 0</code>, no one needs this position
            and the bid immediately returns <span className="text-white/80">$1</span>.
          </p>
        </StepCard>

        <StepCard label="Step 4 — Apply scarcity multiplier">
          <pre className="rounded-2xl border border-white/10 bg-black/40 p-4 text-sm text-white/80 overflow-auto">
{`adjusted_price = base_price × scarcity_multiplier`}
          </pre>
          <div className="rounded-2xl border border-white/10 overflow-hidden">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-white/10 bg-white/5">
                  <th className="text-left px-4 py-2 text-xs font-bold text-white/40 uppercase">Position</th>
                  <th className="text-left px-4 py-2 text-xs font-bold text-white/40 uppercase">Multiplier</th>
                </tr>
              </thead>
              <tbody>
                {[
                  { pos: "C",               mult: "×1.15" },
                  { pos: "SS",              mult: "×1.08" },
                  { pos: "2B / SP / RP / CL", mult: "×1.05" },
                  { pos: "3B",              mult: "×1.02" },
                  { pos: "1B / OF / DH",   mult: "×1.00" },
                ].map((row, i, arr) => (
                  <tr key={row.pos} className={i !== arr.length - 1 ? "border-b border-white/5" : ""}>
                    <td className="px-4 py-2 text-white/80 text-xs">{row.pos}</td>
                    <td className="px-4 py-2 font-mono text-white/60 text-xs">{row.mult}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </StepCard>

        <StepCard label="Step 5 — Compute spendable">
          <p className="text-sm text-white/60 leading-relaxed">
            Maximum amount you can actually spend. At least $1 must be reserved per remaining roster slot.
          </p>
          <pre className="rounded-2xl border border-white/10 bg-black/40 p-4 text-sm text-white/80 overflow-auto">
{`// When my_roster is provided:
my_remaining_roster_spots = max(0, roster_size - len(my_roster))

min_reserve = max(0, my_remaining_roster_spots - 1)
spendable   = max(1, my_remaining_budget - min_reserve)`}
          </pre>
        </StepCard>

        <StepCard label="Step 6 — Compute max_competitor_budget">
          <p className="text-sm text-white/60 leading-relaxed">
            Maximum remaining budget among opponents who have not yet filled the target position.
            Used as a bid ceiling so you never overbid relative to the competition.
          </p>
          <pre className="rounded-2xl border border-white/10 bg-black/40 p-4 text-sm text-white/80 overflow-auto">
{`// When opponent_budgets is not provided:
max_competitor_budget = spendable   // no cap applied

// When opponent_budgets is provided:
competing_opponents   = opponents who do not yet have target position
  → if none exist: return recommended_bid = 1

max_competitor_budget = max(remaining budgets of competing_opponents)
max_competitor_budget = max(1, max_competitor_budget)`}
          </pre>
        </StepCard>

        <StepCard label="Step 7 — Draft progress adjustment (draft_multiplier)">
          <p className="text-sm text-white/60 leading-relaxed">
            Scales the bid up or down based on how far the draft has progressed
            and how much budget surplus you have relative to your spending needs.
          </p>
          <pre className="rounded-2xl border border-white/10 bg-black/40 p-4 text-sm text-white/80 overflow-auto">
{`draft_progress   = min(1.0, drafted_players_count / (league_size × roster_size))
budget_ratio     = spendable / my_remaining_budget   // 0.5 if budget = 0
draft_multiplier = 1.0 + (budget_ratio - 0.5) × 0.2 × draft_progress

// budget_ratio > 0.5 → surplus → bid more aggressively (multiplier > 1.0)
// budget_ratio < 0.5 → tight   → bid conservatively   (multiplier < 1.0)`}
          </pre>
        </StepCard>

        <StepCard label="Step 8 — Final recommended_bid">
          <pre className="rounded-2xl border border-white/10 bg-black/40 p-4 text-sm text-white/80 overflow-auto">
{`effective_cap   = min(spendable, max_competitor_budget)
raw_bid         = adjusted_price × draft_multiplier
recommended_bid = clip(round(raw_bid), 1, effective_cap)

// Minimum: $1   Maximum: min(spendable, max_competitor_budget)`}
          </pre>
        </StepCard>

        {/* Full Formula Summary */}
        <StepCard label="Full Formula Summary">
          <pre className="rounded-2xl border border-white/10 bg-black/40 p-4 text-sm text-white/80 overflow-auto">
{`base_price       = (player_value / 100) × total_budget
adjusted_price   = base_price × scarcity_multiplier
min_reserve      = my_remaining_roster_spots - 1
spendable        = max(1, my_remaining_budget - min_reserve)
draft_progress   = drafted_players_count / (league_size × roster_size)
budget_ratio     = spendable / my_remaining_budget
draft_multiplier = 1.0 + (budget_ratio - 0.5) × 0.2 × draft_progress
effective_cap    = min(spendable, max_competitor_budget)
recommended_bid  = clip(round(adjusted_price × draft_multiplier), 1, effective_cap)`}
          </pre>
        </StepCard>

      </div>

      {/* Early-Exit Cases */}
      <div className="space-y-3">
        <p className="text-xs font-bold text-white/40 uppercase">Early-Exit Cases</p>
        <div className="rounded-2xl border border-white/10 overflow-hidden">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-white/10 bg-white/5">
                <th className="text-left px-4 py-2 text-xs font-bold text-white/40 uppercase">Condition</th>
                <th className="text-left px-4 py-2 text-xs font-bold text-white/40 uppercase">Return Value</th>
              </tr>
            </thead>
            <tbody>
              {[
                { cond: "competitors_at_pos == 0 (Step 3)", val: "recommended_bid = 1" },
                { cond: "All opponents already have the target position (Step 6)", val: "recommended_bid = 1" },
              ].map((row, i, arr) => (
                <tr key={i} className={i !== arr.length - 1 ? "border-b border-white/5" : ""}>
                  <td className="px-4 py-2 text-white/80 text-xs">{row.cond}</td>
                  <td className="px-4 py-2 font-mono text-white/60 text-xs">{row.val}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

    </div>
  );
}

// ── Hero Page ─────────────────────────────────────────────────────────────────

function Hero() {
  // activeTab controls which documentation section is displayed
  const [activeTab, setActiveTab] = useState<DocTab>("data");

  return (
    <div className="relative flex flex-col items-center px-6 pb-24">

      {/* Decorative background gradient */}
      <div className="absolute inset-0 bg-gradient-to-b from-white/5 to-black pointer-events-none" />

      {/* ── Hero section ──────────────────────────────────────────────────── */}
      <div className="relative z-10 max-w-2xl text-center pt-32 pb-24">

        {/* Pill badge */}
        <div className="inline-flex items-center gap-2 rounded-full border border-white/10 bg-white/5 px-4 py-1.5 text-xs text-white/50 mb-6">
          PPA-DUN Evaluator · Fantasy Baseball
        </div>

        <h1 className="text-5xl font-extrabold tracking-tight text-white md:text-7xl">
          PPA-DUN API
        </h1>

        <p className="mt-6 text-lg text-white/60 leading-relaxed">
          A player valuation API for fantasy baseball draft kits.
          Send player stats, get back a recommended bid and player value — instantly.
        </p>

        <div className="mt-4 text-sm text-white/30">
          Designed to be licensed and integrated into any fantasy baseball platform.
        </div>
      </div>

      {/* ── Documentation section ─────────────────────────────────────────── */}
      <div className="relative z-10 max-w-2xl w-full space-y-6">

        <div>
          <h2 className="text-2xl font-extrabold tracking-tight text-white mb-2">
            How it works
          </h2>
          <p className="text-white/50 text-sm">
            All valuations use{" "}
            <span className="text-white/70">Rotisserie 5x5 (Roto 5x5)</span> scoring.
          Select a section below to explore what player data is available,
            how the FVARz valuation algorithm works,
            or how the bid recommendation is calculated.
          </p>
        </div>

        {/* Tab buttons */}
        <div className="flex flex-wrap gap-2">
          <TabButton
            label="Player Data"
            active={activeTab === "data"}
            onClick={() => setActiveTab("data")}
          />
          <TabButton
            label="Player Value (FVARz)"
            active={activeTab === "value"}
            onClick={() => setActiveTab("value")}
          />
          <TabButton
            label="Recommended Bid"
            active={activeTab === "bid"}
            onClick={() => setActiveTab("bid")}
          />
        </div>

        {/* Tab content */}
        {activeTab === "data"  && <PlayerDataTab />}
        {activeTab === "value" && <PlayerValueTab />}
        {activeTab === "bid"   && <RecommendedBidTab />}

      </div>
    </div>
  );
}

export default Hero;