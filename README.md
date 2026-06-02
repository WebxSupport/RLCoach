# RLCoach

AI-powered Rocket League coaching web app. Connect your Epic Games account, fetch your
replays, and get per-match AI breakdowns plus a personalised, rank-scaled training plan.

Built with FastAPI + SQLite + Claude Sonnet 4.6, parsing replays with rrrocket + carball.

---

## Quick start (local)

```bash
cp .env.example .env          # add your ANTHROPIC_API_KEY and ENCRYPTION_KEY
docker compose up --build
# open http://localhost:8000
```

Generate an encryption key:
```bash
python -c "import secrets; print(secrets.token_hex(32))"
```

## Production deployment

Full step-by-step for AWS Lightsail → a custom domain (HTTPS via Let's Encrypt) is in
**[DEPLOYMENT.md](DEPLOYMENT.md)**. Architecture and internals are in
**[handover.md](handover.md)**.

```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build
```

---

## What's in here

| Path | Purpose |
|------|---------|
| `web_app.py` | FastAPI app — all endpoints |
| `web_database.py` | Async SQLite layer (users, sessions, profiles, coaching, matches) |
| `rlcoach/` | Replay parse pipeline + metrics + Claude integration + coaching engine |
| `rlapi/` | Vendored PsyNet client (Epic auth, match history, rank lookup) |
| `static/` | Frontend SPA, dashboard template, rank-icon SVGs |
| `Dockerfile` | Container build (downloads the rrrocket Linux binary) |
| `nginx.conf` | Reverse-proxy config for HTTPS + SSE |

## Configuration

All config is via environment variables — see [`.env.example`](.env.example). Required:
`ANTHROPIC_API_KEY` and `ENCRYPTION_KEY`. In production also set `SECURE_COOKIES=true` and
`ALLOWED_ORIGINS=https://yourdomain`.

## Security

- Passwords hashed with scrypt; Epic OAuth tokens Fernet-encrypted at rest.
- Login/registration rate-limited; security headers + CSP applied.
- No secrets in the repo — everything sensitive is gitignored and injected at runtime.

> **Note:** `rlcoach/` also contains a few desktop-only modules (`ui.py`, `poller.py`,
> `watcher.py`) used by the original Windows tray app. They are not imported by the web app
> and are harmless in the container. The Windows `rrrocket.exe` is intentionally excluded —
> the Docker image downloads the Linux build at build time.
