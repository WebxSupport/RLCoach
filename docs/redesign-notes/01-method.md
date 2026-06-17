# Visual loop: how to run, seed, and screenshot every screen

- Dev server: `.claude/launch.json` → uvicorn on port **8801** with `DEV_SEED=true` (preview_start name `rlcoach`). Or manually: `$env:DEV_SEED='true'; .venv\Scripts\python.exe -m uvicorn web_app:app --port 8801`.
- **DEV_SEED** (`rlcoach/dev_seed.py`, startup-gated in web_app.py): seeds user `dev@rlcoach.local` / `devseed`, fixed session cookie `devseed-session` (Epic marked connected, player id set, profile, 8 matches incl. 1 analyzed, active plan, series report, tracker, metric history). Refuses to run if `SECURE_COOKIES=true`. Off by default → impossible in prod.
- Screenshots: `devtools/shoot.py` (Playwright; `pip install playwright` + `playwright install chromium` already done in .venv).
  `& .\.venv\Scripts\python.exe devtools\shoot.py --url http://localhost:8801/ --cookie devseed-session --out shots\x.png --full [--width 390 --height 844] [--js "switchTab('stats')"] [--wait 1500]`
  Exit code 2 + PAGE ERRORS on stderr when the page throws — treat as failure.
  - For data-loading SPA tabs, use async JS so screenshots do not race the authenticated app boot:
    `--js "(async()=>{switchTab('history'); await loadMatches();})()"` or
    `--js "(async()=>{switchTab('stats'); await loadStats(true);})()"`.
  - Standalone views: `/api/coaching/view`, `/api/series/view`, `/api/matches/<id>/dashboard` (same cookie).
- The Claude_Preview MCP screenshot tool times out on this machine (page healthy, capture stuck) — verified 4x. Use shoot.py, don't retry the MCP path.
- Verify each milestone with a fresh-context subagent that Reads the PNGs against the design bar in 02-design-direction.md.

## M1 verification facts (2026-06-17)
- Fixed seed-cookie reliability: `rlcoach/dev_seed.py` now replaces any stale devseed session with `session_id=devseed-session` and resets `dev@rlcoach.local` to password `devseed`.
- Verified with `curl.exe -H "Cookie: session_id=devseed-session" http://localhost:8804/api/me`: logged in as `DevStriker`, Epic connected, player id `epic:DevStriker`.
- API smoke checks passed on port 8804: `/api/coaching`, `/api/series`, `/api/matches`, `/api/metrics/history`.
- Seed screenshots captured in `docs/redesign-notes/shots/audit/`: home/series/history/stats SPA tabs, mobile home, `/api/coaching/view`, `/api/series/view`, `/api/matches/devseed-m1/dashboard`. History and Stats were recaptured with async tab loaders and show seeded matches/metrics.
- Visual blockers confirmed for later milestones: home is still a flat Coaching Plan dashboard rather than Today mission control; mobile nav horizontally clips; standalone templates render but do not yet share the elevated redesign.
