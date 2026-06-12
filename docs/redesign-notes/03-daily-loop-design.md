# Daily training loop — architecture (M4)

One line: a deterministic server-side "today" state drives the home screen; series checks read the active plan; plan tweaks are deterministic (no extra AI cost) with motivating copy.

## Data flow
- **Daily games target**: computed in coaching_engine post-processing, `plan["dailyGames"] = clamp(round(application_mins_per_day / 12), 2, 7)` from the plan's own week blocks (application+skill minutes). Stored in plan content — no schema migration.
- **Games played today**: counted server-side from `matches` summaries (`played_at` date == today, local). Updated by the existing fetch job — the Today card's "Sync" button triggers the normal fetch.
- **`GET /api/today`** (new): `{target, played, streak, bestStreak, seriesReady, seriesDoneToday, planFocus, activePlanId}`. seriesReady = played>=target && series not yet run today (usage_daily kind=series). Streak = consecutive days (back from today) with >=1 fetched match; bestStreak cached in tracker.
- **Series ← plan**: series generate passes the active plan's focus/weaknesses/drills into series_analyst; prompt gets a "PLAYER'S ACTIVE PLAN" block + output schema gains `planReview: {applied: [{area, evidence}], stillLeaking: [{area, evidence, drill}]}` where `drill` MUST be one of the plan's own drills (name verbatim) or omitted — enforced by post-reconcile against plan drills.
- **Plan tweak**: `POST /api/coaching/tune` (allowed once per series report; admins exempt) — deterministic: for each stillLeaking area, find matching drills in the plan/catalog and +5 min weekly emphasis (rebalance from applied-well areas, floor 10min); appends to `plan["adjustments"]: [{date, reportId, summary, changes[]}]`. Copy templated from planReview ("Rotation is landing — leveling up: Aerial challenges +10 min"). No LLM call.

## UX (home = Today)
ring(played/target) + streak flame + plan focus card → when seriesReady, the Series Check CTA replaces the ring as the hero. After series view, "Tune my plan" CTA on the report + home. Tomorrow resets.

## Honesty constraints
- Never show a streak/ring from unfetched data as if synced — label "as of last sync HH:MM" + Sync button.
- planReview.drill snapped to plan drills (verified codes) or dropped.
