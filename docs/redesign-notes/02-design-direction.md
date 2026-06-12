# Design direction — "Mission control for your rank-up"

One line: keep the cyan-on-navy RL identity, add depth + motion + a guided daily loop so a new player always knows the one next action and a returning player gets an instant dopamine read of momentum.

## Current-state audit (verified on screenshots, 2026-06-12)
- Landing: competent but flat — centered card, no motion, no product story. Mobile fine.
- Main app: 4 tabs (Coaching/Series/History/Stats); everything is the same gradient panel → no hierarchy; the "next action" is whatever button you find first.
- Coaching home has accountability tracker (7-day checklist) but it's a flat checkbox grid; no streaks, no rings, no celebration.
- Motion today: spinner, indeterminate bar, toast fade, drill flash (templates). No tab transitions, no count-ups, no stagger.
- Empty states: dashed-border boxes with an emoji — teach nothing about the product.
- Templates (plan/series/match dashboards) are separate full pages w/ own CSS — must be restyled to match.
- Pack-code copy exists in coaching_template only; codes appear nowhere else.

## The bar (what every screen must satisfy)
1. **One obvious next action** — visually dominant CTA per screen; everything else recedes.
2. **Momentum visible in <1s** — streak, today's progress ring, plan focus on the home screen.
3. **Motion guides, never decorates** — transitions ≤250ms, stagger ≤40ms/card; every async wait has an alive loading state; `prefers-reduced-motion` honored everywhere.
4. **Scannable** — no paragraph >3 lines in the SPA; mono microlabels (10-11px uppercase) + Oxanium display numbers; chunked cards.
5. **Mobile = first-class** — verified at 390px in the loop, swipeable tabs, thumb-size targets.

## System tokens (extends existing palette, no replacement)
- Elevation: `--bg` page → `--panel` card → `--panel2` raised; add inset top-highlight `1px rgba(255,255,255,.04)` on raised cards + layered shadow `0 8px 24px #0008`.
- Accent discipline: cyan = interactive/primary; green = win/success/done; amber = attention; red = loss/danger only. Gradient (cyan→blue) reserved for hero numbers + primary CTA.
- Radii 12/16; 8px spacing grid; section gaps 32-40px.
- Type scale: 11 mono label / 13 body / 15 card title / 22 screen title / 34-44 hero number (Oxanium 800).

## Motion language (reusable patterns, names used in code)
- `.anim-rise` — screen/tab enter: fade + translateY(10px), 220ms ease-out, children stagger 40ms.
- `.btn` press: scale(.97); primary hover: lift + glow.
- `countUp(el)` — stat numbers tween 700ms ease-out on first reveal.
- `<progress ring>` — SVG stroke-dashoffset animates 800ms; used for daily games + weekly progress.
- `celebrate(el)` — radial "boost burst" glow + check pop on drill/day/series completion (no confetti libs).
- Skeleton shimmer for loading lists; job waits keep indeterminate bar + rotating status copy.

## Flow arc (first-run → daily loop)
signup → connect Epic → player ID → wizard → first plan: each gate screen shows a 4-step journey rail ("1 Connect · 2 Identify · 3 Profile · 4 Plan") so progress is legible.
Daily loop (M4): plan defines daily games target → Today card shows ring (0/N games) → target met ⇒ Series Check CTA takes over the home screen → series report shows "applied from plan / still leaking" vs the active plan's focus areas → one-tap "Tune my plan" adjusts emphasis → tomorrow repeats.

## Decisions
- Keep vanilla JS + inline styles architecture (no framework, no build step) — redesign lives in the same files.
- Keep Oxanium/IBM Plex Mono + palette as foundation (brand continuity with logo).
- Home tab becomes **Today** (mission control); coaching plan detail stays a full-page view.
