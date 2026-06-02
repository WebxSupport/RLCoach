# RLCoach — Handover Document

## What this is

Two products in one repo:

1. **Desktop app** (`main.py` / `dist\RLCoach\RLCoach.exe`) — Windows tray app that polls PsyNet, parses replays, produces per-match bundles, and shows a tkinter dashboard.
2. **Web app** (`web_app.py` / Docker) — Multi-user FastAPI service at **whatasave.xyz** that does the same pipeline plus: multi-user accounts, Claude Sonnet 4.6 AI coaching, personalized training plans, and rank detection.

**Tracked player (desktop):** `steam:76561198335346016` — Diamond/Champ, 2s, overcommitting focus.  
**Project root:** `C:\Users\lukeb\Desktop\RL_ANALYIS\`  
**Run (desktop dev):** `python main.py`  
**Run (web dev):** `uvicorn web_app:app --reload`  
**Run (Docker):** `docker compose up`

**Related docs:** `DEPLOYMENT.md` (full AWS Lightsail → whatasave.xyz guide), `.env.example` (env vars), `nginx.conf` (reverse proxy).

---

## Current status: FULLY OPERATIONAL

Both modes working. Web app includes multi-user auth, coaching engine, rank detection, and AWS Lightsail deployment configuration.

---

## Repository layout

```
main.py                      Desktop pipeline entry point
web_app.py                   FastAPI web app entry point
web_database.py              Async SQLite layer (aiosqlite)
config.yaml                  Desktop config (player_id, output_dir, poll_interval)
requirements.txt             Desktop deps (includes pystray, pyinstaller)
requirements_web.txt         Web deps (fastapi, aiosqlite, anthropic, slowapi, cryptography)
Dockerfile                   Linux container (downloads rrrocket Linux binary)
docker-compose.yml           Base compose (dev + prod base)
docker-compose.prod.yml      Production overrides (resource limits, restart policy)
nginx.conf                   nginx reverse proxy config (HTTPS, SSE support, security headers)
.env.example                 Environment variable template
build.bat / RLCoach.spec     Desktop EXE build (PyInstaller)
app_icon.png / rlcoach.ico   App icons

rlcoach/                     Core pipeline package (shared by desktop + web)
  parser.py                  rrrocket + carball parse pipeline + compat patches
  metrics.py                 Frame-level coaching metrics (positioning, boost, double-commits)
  events.py                  Key moment extraction for PNG diagrams
  renderer.py                matplotlib top-down field diagrams (headless-safe)
  digest.py                  Writes match.json + match.md per replay
  ledger.py                  processed.json dedup (file-hash + GUID)
  extended_metrics.py        Additional frame metrics for Claude (ballchase, net coverage, etc.)
  claude_analyst.py          Per-match Claude Sonnet 4.6 HTML dashboard generation
  coaching_engine.py         Personalised coaching.md plan generation (win+loss pair)
  replay_selector.py         Finds 1 full WIN + 1 full LOSS in chosen playlist
  stats_api.py               PsyNet Skills API rank fetch + RANK_ICON mapping
  training_resources.py      Curated training packs, workshop maps, rank tier focus areas
  web_pipeline.py            Async pipeline runner for web (replaces desktop poller)
  psynet_auth.py             EOS token storage (desktop file-based)
  poller.py                  Desktop background poll loop
  ui.py                      tkinter Dashboard + UIReporter event bus
  config.py                  Pydantic config loader
  ledger.py                  Replay dedup ledger
  _build_icon.py             PNG→ICO conversion for PyInstaller build

rlapi/                       Vendored PsyNet WebSocket RPC client
  client.py                  RocketLeagueClient (combines all API mixins)
  api_all.py                 MatchesAPI (get_match_history), SkillsAPI (get_player_skills)
  egs.py                     Epic Games device auth flow + EOS token exchange
  psynet.py                  PsyNet HTTP auth + constants
  psynetrpc.py               WebSocket RPC base class

static/
  index.html                 SPA frontend (login/register, wizard, coaching, match history)
  dashboard_template.html    AI report HTML template (MATCH object injected by Claude)
  rank-icons/                20 SVG rank emblems (b1-b3, s1-s3, g1-g3, p1-p3, d1-d3, c1-c3, gc, Unranked)

rrrocket_bin/                rrrocket 0.11.1 Windows binary (Linux binary downloaded by Dockerfile)
dist/RLCoach/                Compiled Windows EXE
data/                        Runtime data dir (Docker volume-mounted)
  rlcoach.db                 SQLite database
  output/{session_id}/       Per-user replay output folders
```

---

## Architecture: Auth & key constants

### Epic Games / EOS (update per RL patch ~6 weeks)
```python
# rlapi/psynet.py — update these each RL patch
GAME_VERSION = "260506.26700.517210"
FEATURE_SET  = "PrimeUpdate58_1"
PSY_BUILD_ID = "-1652286008"   # CRC32 of GAME_VERSION

# rlapi/egs.py — loaded from env vars with these fallbacks
EGS_CLIENT_ID     = "34a02cf8f4414e29b15921876da36f9a"
EOS_CLIENT_ID     = "xyza7891p5D7s9R6Gm6moTHWGloerp7B"
EOS_AUTH_HEADER   = "eHl6YTc4OT..."  # base64(EOS_CLIENT_ID:EOS_CLIENT_SECRET)
EOS_DEPLOYMENT_ID = "da32ae9c12ae40e8a112c52e1f17f3ba"
# Scope MUST be "basic_profile" only — more scopes → SCOPE_CONSENT error
```

### rrrocket binary
- **Windows:** `rrrocket_bin/rrrocket-0.11.1-x86_64-pc-windows-msvc/rrrocket.exe`
- **Linux/Docker:** downloaded at build time, path set via `RRROCKET_PATH=/app/rrrocket_bin/rrrocket`
- Always run with `-n` (--network-parse) for full frame data
- `_find_rrrocket()` in parser.py checks `RRROCKET_PATH` env var first

---

## Architecture: Parse pipeline

**Two-stage with automatic fallback (`rlcoach/parser.py`):**

1. `carball.analyze_replay_file()` — fast path, works on older builds
2. `rrrocket -n replay.replay` → JSON → `carball.json_parser.Game.initialize(loaded_json=...)` — active path for 2026 RL

**`_patch_carball_compat()` monkey-patches applied at runtime:**

| Patch | Why |
|-------|-----|
| `EventsCreator.create_boostpad_events` → no-op | pandas 3.x removed `fillna(method=)` |
| `numpy_manager` np.save/load strip fix_imports | numpy 2.x removed `fix_imports` kwarg |
| `CarHandler.update` → catch KeyError | Non-Soccar PRI actors (`PRI_Breakout_TA`) |
| `BoostHandler.update` → copy ReplicatedBoost struct | RL 2026: boost changed from `Byte` → struct |
| `Game.parse_all_data` → catch KeyError(N) | Demo events reference unregistered player IDs |

**Canonical clock:** Uses `('game', 'seconds_remaining')` which freezes during celebrations. Boost column named `'boost'` (not `'boost_amount'`).

---

## Architecture: Web app

### Multi-user auth flow
1. User registers at `/api/register` (email + password, hashed with `hashlib.scrypt`)
2. Logs in at `/api/login` → session cookie set (httponly, samesite=strict, secure in prod)
3. Connects Epic Games via device auth flow at `/api/epic/start` + `/api/epic/poll/{code}`
4. EOS auth tokens are Fernet-encrypted before storage in SQLite (`ENCRYPTION_KEY` env var)
5. Can disconnect Epic independently of logging out

### Database (SQLite at `data/rlcoach.db`)

| Table | Key fields |
|-------|-----------|
| `users` | user_id, email, password_hash |
| `sessions` | session_id, user_id (UNIQUE), eos_account_id, auth_tokens (encrypted), is_active |
| `profiles` | session_id, platform, gamemode, current_rank, target_rank, mins_per_day, days_per_week |
| `analysis_usage` | eos_account_id, usage_date, count (max 5/day for per-match dashboards) |
| `jobs` | job_id, session_id, status, progress (JSON) |
| `matches` | match_id, session_id, folder_path, summary (JSON), has_analysis |
| `coaching_plans` | plan_id, session_id, content_md, replay_guids, generated_at |

### Key web endpoints

| Endpoint | Purpose |
|----------|---------|
| POST /api/register | Create RLCoach account |
| POST /api/login | Log in (rate-limited: 10/min) |
| POST /api/logout | Deactivates session (data kept) |
| GET /api/me | Auth state + Epic connection status |
| POST /api/epic/start | Start Epic device auth |
| GET /api/epic/poll/{code} | Poll for Epic auth completion |
| POST /api/epic/disconnect | Unlink Epic (keep RLCoach account) |
| GET /api/rank | Fetch all playlist ranks from PsyNet Skills API |
| GET/POST /api/profile | Player profile (platform, gamemode, ranks, time budget) |
| POST /api/coaching/generate | Trigger coaching plan (find 1W+1L → Claude → coaching.md) |
| GET /api/coaching/view | Render coaching.md as styled HTML |
| POST /api/fetch | Fetch latest replays + parse + optional AI dashboard |
| GET /api/fetch/stream/{id} | SSE stream of job progress |
| GET /api/matches | All processed matches for this user |
| GET /api/matches/{id}/dashboard | Serve AI HTML dashboard |
| GET /api/resources | Rank ladder, playlist options, platform options |

### Daily limits
- **Per-match AI dashboards:** 5 per user per day (tracked in `analysis_usage` table)
- **Coaching plans:** No daily limit (separate from per-match dashboards)

### Output folder structure (per session)
```
data/output/{session_id}/
  {date}_{map}_{mode}_{result}/
    match.json          Structured match data
    match.md            LLM-ready markdown summary
    frames.parquet      Raw frame DataFrame (~6000-9000 rows × ~151 cols)
    dashboard.html      AI-generated coaching dashboard (if analysis ran)
    moments/            PNG diagrams of key moments
  processed.json        GUID dedup ledger
```

---

## Architecture: Coaching engine

**Flow:** Profile wizard → `replay_selector.find_win_and_loss()` → `stats_api.fetch_all_ranks()` → `coaching_engine.generate_coaching_plan()` → `coaching.md`

**Rank detection:** `GET /api/rank` tries PsyNet Skills API (`Skills/GetSkills v2` or `1/skill/2`). Returns all playlists with rank label + icon filename (e.g. `d2.svg`). Rank emblems served from `static/rank-icons/`.

**Replay selection:** Scans up to 20 recent PsyNet replays, filters by: correct playlist, duration > 180s (full game), correct team size. Picks the most recent full WIN and full LOSS.

**Training resources:** `rlcoach/training_resources.py` — rank-tier focus areas, training pack codes, workshop maps (PC), BakkesMod plugins (PC). Included in Claude prompt.

**Platform-aware:** PC (steam/epic) gets BakkesMod + workshop map recommendations. Console gets training pack codes only.

---

## Security measures

| Measure | Implementation |
|---------|---------------|
| Rate limiting | `slowapi` — 10/min on login, 5/min on register |
| Security headers | Custom ASGI middleware (X-Frame-Options, CSP, HSTS, etc.) |
| Secure cookies | httponly, samesite=strict, secure=True in prod |
| Token encryption | Fernet (cryptography library) — EOS tokens encrypted at rest |
| Password hashing | `hashlib.scrypt` (built-in, no extra deps) |
| Timing attack prevention | `verify_password` always called (even on missing user) |
| CORS | Restricted to `ALLOWED_ORIGINS` env var in production |
| EOS credentials | Env vars with community-public fallback values |
| Input validation | Length limits, email regex, player_id format check |

---

## Environment variables

| Variable | Required | Purpose |
|----------|----------|---------|
| `ANTHROPIC_API_KEY` | Yes | Claude Sonnet 4.6 calls |
| `ENCRYPTION_KEY` | Yes (prod) | Fernet key for token encryption at rest |
| `SECURE_COOKIES` | Prod: `true` | Enables Secure + HSTS headers |
| `ALLOWED_ORIGINS` | Prod | CORS whitelist (e.g. `https://whatasave.xyz`) |
| `DAILY_ANALYSIS_LIMIT` | No | Per-match AI dashboards per user/day (default: 5) |
| `RRROCKET_PATH` | Docker: set | Override rrrocket binary path |
| `EGS_CLIENT_ID` etc. | No | Override Epic credentials (use defaults) |

---

## AWS Lightsail deployment (whatasave.xyz)

**Full step-by-step is in `DEPLOYMENT.md`.** Summary:

- **Instance:** General purpose, Dual-stack, **$12/mo (2 GB RAM)** — minimum viable; parsing spikes 400–600 MB/replay so 1 GB OOM-kills mid-parse. Ubuntu 24.04.
- **NOT AWS Amplify** — Amplify is static/serverless only; cannot run Docker, Python, background jobs, SQLite, or the rrrocket binary. Lightsail runs the existing container unchanged.
- **Architecture:** `whatasave.xyz → Lightsail static IP → nginx (443, SSL) → uvicorn:8000 → Docker container → data/ volume`
- **Domain:** A records `@` and `www` → static IP. **SSL:** `certbot --nginx -d whatasave.xyz -d www.whatasave.xyz`.
- **Secrets:** `/home/ubuntu/rlcoach/.env`, `chmod 600`.
- **Deploy:** `rsync` project up → `docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build`.
- **Auto-start:** systemd unit `rlcoach.service`.

---

## Known gaps / open items

1. **Recovery metric = 0** — `parsed.hits` always empty in rrrocket path. Fix: call `manager.get_proto()` after `create_analysis()` and extract from `proto.game_stats.hit`.
2. **PsyNet Skills API endpoint** — tries two method names best-effort; falls back to self-reported rank if both fail.
3. **Goal scoring_team in extended_metrics** — `_run_claude_analysis_sync` reconstructs goals from moments data; `scoring_team` defaults to "blue". Improve by storing parsed goals in match.json.
4. **rrrocket version** — Docker uses `0.11.1`. Update per RL patch. Also update `GAME_VERSION`, `FEATURE_SET`, `PSY_BUILD_ID` in `rlapi/psynet.py` each patch (~6 weeks).
5. **No production backup** — SQLite backup cron job + EBS snapshots should be configured post-deployment.
6. **Session rotation** — Each user has one stable session_id (data keyed by it). Proper rotation would require migrating all tables to `user_id` keys.
