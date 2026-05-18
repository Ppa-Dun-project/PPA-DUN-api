# PPA-DUN actual draft fixtures generated from the uploaded workbook

This folder contains JSON derived from `2026Draft (1).xlsx` for the checkpoints your professor listed:
- pre-draft
- after 10 players taken
- after 50 players taken
- after 100 players taken
- after 130 players taken

## What is included
- `league_state_*.json`: full league snapshots with every team's active roster, remaining budget, minors, taxi, and applied draft picks.
- `team_request_contexts/*.json`: one file per checkpoint per team in the exact nested shape your current `PlayerBidRequest` expects (`league_context` + `draft_context`).
- `sample_full_requests/*.json`: ready-to-send example requests for Team A using a sample batter or pitcher.

## Important assumptions
1. Your current API computes `my_remaining_roster_spots` from `len(my_roster)` when `my_roster` is present.
2. Because the workbook separates Pre-Draft Roster, Draft, Final Roster, Minors, and Taxi, the JSON active rosters were built as:
   - keepers from `Pre-Draft Roster`, plus
   - drafted players that end up on the `Final Roster` for that team, added in draft order.
3. Remaining budgets were computed from the pre-draft budget minus salaries from the `Draft` sheet through each checkpoint.
4. Minors and Taxi are preserved in the league-state snapshots for reference, but they are not injected into `draft_context.my_roster` because your current bid algorithm only inspects active rosters.

## Quick usage
For a real `/player/bid` call, start from one of the files under `team_request_contexts/` and merge in a real player payload (`player_name`, `position`, `stats`).