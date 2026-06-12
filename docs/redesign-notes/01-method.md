# Visual loop: how to run, seed, and screenshot every screen

- Dev server: `.claude/launch.json` → uvicorn on port **8801** with `DEV_SEED=true` (preview_start name `rlcoach`). Or manually: `$env:DEV_SEED='true'; .venv\Scripts\python.exe -m uvicorn web_app:app --port 8801`.
- **DEV_SEED** (`rlcoach/dev_seed.py`, startup-gated in web_app.py): seeds user `dev@rlcoach.local` / `devseed`, fixed session cookie `devseed-session` (Epic marked connected, player id set, profile, 8 matches incl. 1 analyzed, active plan, series report, tracker, metric history). Refuses to run if `SECURE_COOKIES=true`. Off by default → impossible in prod.
- Screenshots: `devtools/shoot.py` (Playwright; `pip install playwright` + `playwright install chromium` already done in .venv).
  `& .\.venv\Scripts\python.exe devtools\shoot.py --url http://localhost:8801/ --cookie devseed-session --out shots\x.png --full [--width 390 --height 844] [--js "switchTab('stats')"] [--wait 1500]`
  Exit code 2 + PAGE ERRORS on stderr when the page throws — treat as failure.
  - Standalone views: `/api/coaching/view`, `/api/series/view`, `/api/matches/<id>/dashboard` (same cookie).
- The Claude_Preview MCP screenshot tool times out on this machine (page healthy, capture stuck) — verified 4x. Use shoot.py, don't retry the MCP path.
- Verify each milestone with a fresh-context subagent that Reads the PNGs against the design bar in 02-design-direction.md.
