# M2 established the elevated visual/motion language on landing, guided gates, and Today while keeping vanilla JS and the existing palette.

- Added shared depth tokens, softer page lighting, raised card shadows, stronger button hover/press states, tab/page rise-in motion, ring draw animation, and `prefers-reduced-motion` handling in `static/index.html`.
- Landing now teaches the loop before login: train today, check the series, tune the plan.
- First-run gates now show a four-step journey rail so the next required action is obvious.
- The home tab is labeled Today and has a mission-control proof card with a progress ring, daily games target, plan focus chips, and one dominant action.
- Verified screenshots live in `docs/redesign-notes/shots/m2/`: landing, Epic gate, and seeded Today at desktop `1440x900` and mobile `390x844`.
- Known intentional limitation: the Today card computes progress client-side for M2 from existing APIs; the deterministic `/api/today` contract remains the M4 backend milestone.
