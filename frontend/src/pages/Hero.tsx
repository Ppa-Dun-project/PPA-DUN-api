function Hero() {
  return (
    <div className="relative flex flex-col items-center px-6 pb-24">
      {/* Background Gradient */}
      <div className="absolute inset-0 bg-gradient-to-b from-white/5 to-black pointer-events-none" />

      {/* Hero section */}
      <div className="relative z-10 max-w-2xl text-center pt-32 pb-24">
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

      {/* Algorithm section */}
      <div className="relative z-10 max-w-2xl w-full space-y-6">

        <div>
          <h2 className="text-2xl font-extrabold tracking-tight text-white mb-2">
            How it works
          </h2>
          <p className="text-white/50 text-sm">
            All valuations use <span className="text-white/70">Rotisserie 5x5 (Roto 5x5)</span> scoring —
            the most widely adopted fantasy baseball format. Every number the API returns
            is traceable back to a concrete formula.
          </p>
        </div>

        {/* ── player_value ── */}
        <div className="rounded-3xl border border-white/10 bg-white/5 p-6 space-y-6">

          <div>
            <p className="text-xs font-bold text-white/40 uppercase mb-1">Output field</p>
            <p className="text-white text-lg font-extrabold">player_value <span className="text-white/40 font-normal text-sm">float · 0.0 ~ 100.0</span></p>
          </div>

          <p className="text-sm text-white/60 leading-relaxed">
            Measures how valuable a player is relative to a league-average player pool,
            normalized to a 0–100 scale. A value of <span className="text-white/80">50</span> means perfectly average.
            A value of <span className="text-white/80">80+</span> means elite — top tier across multiple categories.
          </p>

          {/* Step 1 */}
          <div className="space-y-3">
            <p className="text-xs font-bold text-white/40 uppercase">Step 1 — Z-Score per category</p>
            <p className="text-sm text-white/60 leading-relaxed">
              For each of the 5 Roto categories, we compute how far the player deviates
              from the league-average baseline in units of standard deviation.
              A z-score of <span className="text-white/80">+1.0</span> means one standard deviation above average —
              roughly top 16% of the player pool.
            </p>
            <pre className="rounded-2xl border border-white/10 bg-black/40 p-4 text-sm text-white/80 overflow-auto">
{`z(stat) = (player_stat - league_mean) / league_std

Batter categories:   R, HR, RBI, SB, AVG
Pitcher categories:  W, SV, K, ERA, WHIP

// ERA and WHIP are inverted — lower is better
z(ERA)  = -(player_ERA  - mean_ERA)  / std_ERA
z(WHIP) = -(player_WHIP - mean_WHIP) / std_WHIP`}
            </pre>
          </div>

          {/* Step 2 */}
          <div className="space-y-3">
            <p className="text-xs font-bold text-white/40 uppercase">Step 2 — Sum z-scores</p>
            <p className="text-sm text-white/60 leading-relaxed">
              The five z-scores are summed into a single number representing
              the player's total contribution across all Roto categories.
              A player who excels in multiple categories scores higher than
              a specialist who dominates only one.
            </p>
            <pre className="rounded-2xl border border-white/10 bg-black/40 p-4 text-sm text-white/80 overflow-auto">
{`z_total = z(R) + z(HR) + z(RBI) + z(SB) + z(AVG)
        // or for pitchers:
z_total = z(W) + z(SV) + z(K) + z(ERA) + z(WHIP)`}
            </pre>
          </div>

          {/* Step 3 */}
          <div className="space-y-3">
            <p className="text-xs font-bold text-white/40 uppercase">Step 3 — Position bonus & risk penalty</p>
            <p className="text-sm text-white/60 leading-relaxed">
              Positional scarcity is factored in as a bonus: catchers and shortstops
              are harder to replace, so they receive a higher bonus.
              Risk penalties are subtracted for players with low playing time
              or poor efficiency (e.g. caught stealing rate, high ERA).
            </p>
            <pre className="rounded-2xl border border-white/10 bg-black/40 p-4 text-sm text-white/80 overflow-auto">
{`raw_score = z_total + position_bonus - risk_penalty

Position bonus (z units):
  C   +1.5    SS  +0.8    2B  +0.5
  SP  +0.4    3B  +0.3    RP  +0.6
  1B   0.0    OF   0.0    DH   0.0

Risk penalty (z units):
  Batter  AB < 300              → -0.5
  Batter  CS / (SB+CS) > 35%   → -0.2
  Pitcher IP < 100              → -0.5
  Pitcher ERA > 4.50            → -0.3`}
            </pre>
          </div>

          {/* Step 4 */}
          <div className="space-y-3">
            <p className="text-xs font-bold text-white/40 uppercase">Step 4 — Normalize to 0–100</p>
            <p className="text-sm text-white/60 leading-relaxed">
              The raw score is scaled against a theoretical maximum (elite all-around player)
              and clipped to the 0–100 range. This makes the output intuitive:
              any two players can be compared on the same scale regardless of position or type.
            </p>
            <pre className="rounded-2xl border border-white/10 bg-black/40 p-4 text-sm text-white/80 overflow-auto">
{`player_value = clip((raw_score / RAW_MAX) * 100, 0, 100)`}
            </pre>
          </div>

          {/* Tier table */}
          <div className="space-y-3">
            <p className="text-xs font-bold text-white/40 uppercase">Value tiers</p>
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
                    { label: "Elite", range: "80 – 100", color: "text-yellow-400", meaning: "Top-tier player, draft early" },
                    { label: "Strong", range: "60 – 79", color: "text-green-400", meaning: "Reliable starter, solid value" },
                    { label: "Average", range: "40 – 59", color: "text-blue-400", meaning: "League-average contributor" },
                    { label: "Below Average", range: "20 – 39", color: "text-orange-400", meaning: "Situational or streaky value" },
                    { label: "Replacement", range: "0 – 19", color: "text-red-400", meaning: "Waiver wire / bench depth only" },
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

        {/* ── recommended_bid ── */}
        <div className="rounded-3xl border border-white/10 bg-white/5 p-6 space-y-6">

          <div>
            <p className="text-xs font-bold text-white/40 uppercase mb-1">Output field</p>
            <p className="text-white text-lg font-extrabold">recommended_bid <span className="text-white/40 font-normal text-sm">integer · dollar amount ($)</span></p>
          </div>

          <p className="text-sm text-white/60 leading-relaxed">
            Translates <span className="text-white/80">player_value</span> into a concrete dollar bid
            for auction drafts. The bid accounts for your remaining budget, how far
            into the draft you are, and the positional scarcity of the player.
            It is always at least <span className="text-white/80">$1</span> and never exceeds what you can safely spend.
          </p>

          {/* Step 1 */}
          <div className="space-y-3">
            <p className="text-xs font-bold text-white/40 uppercase">Step 1 — Base price from player_value</p>
            <p className="text-sm text-white/60 leading-relaxed">
              The total auction budget is split 67% to hitters and 33% to pitchers
              (standard Roto 5x5 convention). The player's share of that pool
              is proportional to their player_value.
            </p>
            <pre className="rounded-2xl border border-white/10 bg-black/40 p-4 text-sm text-white/80 overflow-auto">
{`HIT_PITCH_RATIO = 0.67  // for batters
                  0.33  // for pitchers

base_price = (player_value / 100) * total_budget * HIT_PITCH_RATIO`}
            </pre>
          </div>

          {/* Step 2 */}
          <div className="space-y-3">
            <p className="text-xs font-bold text-white/40 uppercase">Step 2 — Positional scarcity multiplier</p>
            <p className="text-sm text-white/60 leading-relaxed">
              Scarce positions command a premium in auction drafts because
              fewer quality options exist. A catcher worth 80 should cost
              more than an outfielder worth 80 — because replacing that
              catcher with the next best option is much harder.
            </p>
            <pre className="rounded-2xl border border-white/10 bg-black/40 p-4 text-sm text-white/80 overflow-auto">
{`adjusted_price = base_price * scarcity_multiplier

Scarcity multipliers:
  C    ×1.15    SS   ×1.08    2B   ×1.05
  SP   ×1.05    RP   ×1.05    3B   ×1.02
  1B   ×1.00    OF   ×1.00    DH   ×1.00`}
            </pre>
          </div>

          {/* Step 3 */}
          <div className="space-y-3">
            <p className="text-xs font-bold text-white/40 uppercase">Step 3 — Draft progress adjustment</p>
            <p className="text-sm text-white/60 leading-relaxed">
              As the draft progresses, your spending behavior should shift.
              Early on, you have budget to be aggressive. Late in the draft,
              you need to preserve enough for remaining roster spots.
              This step adjusts the bid based on how much of your budget
              is left and how far into the draft the league is.
            </p>
            <pre className="rounded-2xl border border-white/10 bg-black/40 p-4 text-sm text-white/80 overflow-auto">
{`draft_progress = drafted_players_count / (league_size * roster_size)
budget_ratio   = spendable / my_remaining_budget

// If budget_ratio > 0.5 → you have room to spend more
// If budget_ratio < 0.5 → tighten up
draft_multiplier = 1.0 + (budget_ratio - 0.5) * 0.2 * draft_progress

recommended_bid = clip(
  round(adjusted_price * draft_multiplier),
  min = 1,
  max = spendable           // never exceed what you can safely spend
)`}
            </pre>
          </div>

          {/* Step 4 */}
          <div className="space-y-3">
            <p className="text-xs font-bold text-white/40 uppercase">Step 4 — Budget ceiling (max_spendable)</p>
            <p className="text-sm text-white/60 leading-relaxed">
              You must always keep at least $1 per remaining roster spot
              so you can fill out your team. The maximum you can safely
              bid on any single player is your remaining budget minus
              the number of empty roster spots still to fill.
            </p>
            <pre className="rounded-2xl border border-white/10 bg-black/40 p-4 text-sm text-white/80 overflow-auto">
{`min_reserve  = my_remaining_roster_spots - 1
spendable    = my_remaining_budget - min_reserve

// recommended_bid is always capped at spendable`}
            </pre>
          </div>

        </div>

      </div>
    </div>
  );
}

export default Hero;