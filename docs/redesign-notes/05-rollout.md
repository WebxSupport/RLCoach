# M3 rolls the visual system across SPA tabs and standalone reports, with every detail page returning the player to the daily training loop.

- Series, History, and Stats now use raised mission-hero panels with one dominant action, live status chips, and the same depth/motion language as Today.
- Match cards, stat cards, empty states, progress cards, charts, and filters were restyled to the elevated cyan/navy system rather than flat dashboard panels.
- Standalone coaching, series, and match report templates now share the same background lighting, raised cards, hover/press motion, reduced-motion handling, and mobile-safe layout.
- Standalone coaching and series pages now expose constructive primary CTAs back to Today/apply-fixes flow; destructive delete actions are visually demoted.
- Mobile standalone tab rails are chip grids so labels do not visually clip at 390px.
- Stats MMR chart switches to a compact mobile SVG coordinate system so labels and the trend line stay readable.
- Verified screenshot set for this milestone is in `docs/redesign-notes/shots/m3/`; affected standalone captures were refreshed from a new dev server on port 8805 so API-rendered templates picked up the latest CSS.
