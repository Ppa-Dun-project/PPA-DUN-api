<div align="center">

<img src="logo.png" alt="PPA-DUN" width="180"/>

# PPA-DUN API

**Player value & bid recommendations for Fantasy Baseball auction drafts.**

[![API status](https://img.shields.io/badge/dynamic/json?url=https%3A%2F%2Fapi.ppa-dun.site%2Fhealth&label=api&query=%24.status&color=brightgreen)](https://api.ppa-dun.site/health)
[![Get a key](https://img.shields.io/badge/get%20a%20key-api.ppa--dun.site-2563eb)](https://api.ppa-dun.site)

</div>

---

## What is this?

PPA-DUN API exposes our **Roto 5×5 FVARz** algorithm as a simple REST service. Send a player's stats; get back a normalized 0–100 value score and a recommended auction bid that accounts for league context, position scarcity, depth-chart status, and injury risk.

Built for fantasy-baseball platforms, draft tools, and analysts who want a turnkey valuation backbone instead of rolling their own.

---

## Quickstart

**1. Get a key** — sign in at [api.ppa-dun.site](https://api.ppa-dun.site) with Google, click **Generate Key**.

**2. Try it**
```bash
curl -X POST https://api.ppa-dun.site/player/value \
  -H "X-API-Key: $YOUR_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "player_name": "Aaron Judge",
    "position": "OF",
    "stats": {
      "player_type": "batter",
      "age": 32, "depth_order": 1,
      "R": 122, "HR": 58, "RBI": 144, "SB": 10, "AVG": 0.322,
      "AB": 559, "CS": 2,
      "injury_status": null
    }
  }'
```

**3. Response**
```json
{
  "player_name": "Aaron Judge",
  "player_type": "batter",
  "player_value": 87.4,
  "value_breakdown": {
    "stat_score": 75.2,
    "position_bonus": 0.0,
    "risk_penalty": 0.0
  }
}
```

---

## Authentication

All `/player/*` and `/players/*` endpoints require an `X-API-Key` header.

```
X-API-Key: <your-64-char-hex-key>
```

The `/demo/*` endpoints are open with a 10-req/min/IP cap so anyone can evaluate the service without signing up.

---

## Endpoints

| Method | Path | Description | Auth |
|--------|------|-------------|------|
| `POST` | `/player/value`        | Compute player value (0–100)              | 🔒 |
| `POST` | `/player/bid`          | Recommend auction bid in `$`              | 🔒 |
| `POST` | `/player/bid/name`     | Bid by player name (auto-fetch stats)     | 🔒 |
| `GET`  | `/players`             | List players (filterable)                 | 🔒 |
| `GET`  | `/players/{id}`        | Single player details                     | 🔒 |
| `POST` | `/demo/value`          | Same as `/player/value`, no key           | 10/min |
| `POST` | `/demo/bid`            | Same as `/player/bid`, no key             | 10/min |
| `GET`  | `/health`              | Service health                            | open |

Full request/response schemas → **[OpenAPI docs](https://api.ppa-dun.site/docs)**

---

## How player_value is computed

The pipeline blends recent stats with 3-year history, adjusts for context, then maps to a clean 0–100 score.

```
   ┌──────────────────────────────────────────────────────────┐
   │   STEP A   Blend stats   ─  60% current + 40% 3-yr avg   │
   ├──────────────────────────────────────────────────────────┤
   │   STEP B   Age factor          ←  career trajectory      │
   │   STEP C   Depth factor        ←  expected playing time  │
   ├──────────────────────────────────────────────────────────┤
   │   STEP E   Z-score sum across 5 Roto categories          │
   ├──────────────────────────────────────────────────────────┤
   │   STEP F   Position scarcity bonus  (+)                  │
   │   STEP G   Risk penalty             (−)                  │
   ├──────────────────────────────────────────────────────────┤
   │   STEP H   Normalize to [0, 100]                         │
   └──────────────────────────────────────────────────────────┘
```

#### 5 Roto categories
| Type    | Categories used                                      |
|---------|------------------------------------------------------|
| Batter  | `R + HR + RBI + SB + AVG`     (all higher = better)  |
| Pitcher | `W + SV + K − ERA − WHIP`     (last two flipped)     |

#### Age factor (Step B)
| Age      | ≤ 25 | 26–30 | 31–33 | ≥ 34 | unknown |
|----------|------|-------|-------|------|---------|
| Factor   | 1.05 | 1.00  | 0.95  | 0.90 | 1.00    |

#### Depth factor (Step C)
| Depth chart | 1st  | 2nd  | 3rd  | ≥ 4th | unknown |
|-------------|------|------|------|-------|---------|
| Factor      | 1.00 | 0.90 | 0.75 | 0.60  | 1.00    |

> ⚠ Depth factor is **not** applied to rate stats (`AVG`, `ERA`, `WHIP`) — playing-time has no effect on per-PA performance.

#### Position scarcity bonus (Step F, in z-score units)
| Pos | C   | SS  | 2B  | 3B  | 1B / OF / DH | SP  | RP / CL |
|-----|-----|-----|-----|-----|--------------|-----|---------|
| +   | 1.5 | 0.8 | 0.5 | 0.3 | 0.0          | 0.4 | 0.6     |

#### Risk penalty (Step G)
| Condition                                   | Penalty |
|---------------------------------------------|--------|
| AB &lt; 300 (batter)                        | −0.5 |
| CS / (SB + CS) &gt; 0.35 (batter)           | −0.2 |
| IP &lt; 100 (pitcher)                       | −0.5 |
| ERA &gt; 4.50 (pitcher)                     | −0.3 |
| Day-To-Day · 10/15/60-day IL · Out          | −0.1 to −1.0 |

#### Final
```
raw_score    = z_total + position_bonus − risk_penalty
player_value = clip( raw_score / 12.0 × 100 , 0 , 100 )
```

> 🕒 **Daily refresh.** Baselines (mean & std per category) are recomputed every day at **3 AM ET** from the live MLB player pool, so values stay accurate as the season progresses.

---

## How recommended_bid is computed

```
   ┌──────────────────────────────────────────────────────────┐
   │   STEP 1   player_value   ←  pipeline above              │
   ├──────────────────────────────────────────────────────────┤
   │   STEP 2   base_price = value × budget × hit/pitch split │
   ├──────────────────────────────────────────────────────────┤
   │   STEP 3   early-exit  ←  no competitors at this pos     │
   │            ↳ recommended_bid = $1                        │
   ├──────────────────────────────────────────────────────────┤
   │   STEP 4   × position scarcity multiplier  (+)           │
   │   STEP 5   compute spendable  (reserve $1 / open slot)   │
   │   STEP 6   competitor_cap                                │
   │            = max budget of opponents who still need pos  │
   ├──────────────────────────────────────────────────────────┤
   │   STEP 7   draft-progress adjustment                     │
   │   STEP 8   clip to [1, min(spendable, competitor_cap)]   │
   └──────────────────────────────────────────────────────────┘
```

#### Hitter / pitcher budget split (Step 2)
| Player type | Share of total budget |
|-------------|-----------------------|
| Batter      | **67 %**              |
| Pitcher     | **33 %**              |

> Standard Roto 5×5 auction convention.

#### Position scarcity multiplier (Step 4)
| Pos        | C    | SS   | 2B / SP / RP / CL | 3B   | 1B / OF / DH |
|------------|------|------|-------------------|------|--------------|
| Multiplier | 1.15 | 1.08 | 1.05              | 1.02 | 1.00         |

#### Draft-progress multiplier (Step 7)
```
budget_ratio   = spendable / my_remaining_budget
draft_progress = drafted_count / (league_size × roster_size)
multiplier     = 1 + (budget_ratio − 0.5) × 0.2 × draft_progress
```
> 📈 Pushes you slightly **higher** when you're flush early, slightly **lower** when you're stretched late — without ever crossing the spendable / competitor caps.

#### Final
```
recommended_bid = clip( round(adjusted_price × multiplier),
                        1,
                        min(spendable, competitor_cap) )
```

> 💡 The **competitor cap** is the key insight — we never recommend overpaying when no one else is positioned to bid you up.

---

## Example — full bid request (Python)

```python
import requests, os

resp = requests.post(
    "https://api.ppa-dun.site/player/bid",
    headers={"X-API-Key": os.environ["PPA_DUN_KEY"]},
    json={
        "player_name": "Shohei Ohtani",
        "position": "DH",
        "stats": {
            "player_type": "batter", "age": 31, "depth_order": 1,
            "R": 134, "HR": 54, "RBI": 130, "SB": 59, "AVG": 0.310,
            "AB": 540, "CS": 4, "injury_status": None,
        },
        "league_context": {"total_budget": 260, "league_size": 12, "roster_size": 23},
        "draft_context":  {
            "drafted_players_count": 80,
            "my_remaining_budget": 180,
            "my_remaining_roster_spots": 18,
            "opponent_budgets": {"team_b": 200, "team_c": 150},
            "opponent_rosters": {"team_b": [], "team_c": []},
        },
    },
).json()
print(resp["recommended_bid"])
```

---

## Pricing & Plans

> 💬 Pricing below is illustrative — replace with final numbers before going live.

| Tier            | Monthly quota   | Per-min cap     | Price        |
|-----------------|-----------------|-----------------|--------------|
| **Free / Demo** | 300 req         | 10 req / min    | **$0**       |
| **Pro**         | 50,000 req      | 60 req / min    | **$29 / mo** |
| **Enterprise**  | Unlimited       | Negotiated      | Contact us   |

- One API key per account.
- Soft block kicks in above the per-min cap (HTTP 429); sustained abuse may suspend the key.
- All authenticated tiers share the same algorithm and SLA — only volume differs.

---

## Reliability

Hosted on **Google Cloud (GKE)** behind a load balancer with HTTPS via Let's Encrypt. The player-value baselines refresh every day at **3 AM ET** from the live MLB player pool, so the algorithm tracks the season in real time.

See [`PPA-DUN-cloud`](https://github.com/Ppa-Dun-project/PPA-DUN-cloud) for full infrastructure details.

---

## Repo layout

This repo is a **monorepo** for the API service:

```
api/        — public algorithm service (FastAPI)         → api.ppa-dun.site/{player,players}/*
backend/    — auth & API-key management (FastAPI + MySQL) → api.ppa-dun.site/auth/*
frontend/   — landing page (React + Vite)                → api.ppa-dun.site
```

---

<div align="center">
<sub>Part of the <a href="https://github.com/Ppa-Dun-project">PPA-DUN</a> project · Stony Brook University CSE 416</sub>
</div>
