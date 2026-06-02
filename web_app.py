"""
RLCoach Web App — multi-user FastAPI entry point.

Auth (RLCoach account):
  POST /api/register            Create account (email + password)
  POST /api/login               Log in
  POST /api/logout              Log out (keeps data, clears cookie)
  GET  /api/me                  Current RLCoach account + Epic connection state

Epic Games (connect after RLCoach login):
  POST /api/epic/start          Start Epic device auth
  GET  /api/epic/poll/{code}    Poll for Epic auth completion
  POST /api/epic/disconnect     Remove Epic connection (keeps RLCoach account)
  POST /api/auth/player_id      Set tracked player ID

Rank / stats:
  GET  /api/rank                Fetch all ranked playlist ranks from PsyNet

Profile + coaching:
  GET/POST /api/profile
  POST /api/coaching/generate
  GET  /api/coaching
  GET  /api/coaching/view

Replays:
  POST /api/fetch
  GET  /api/fetch/status/{id}
  GET  /api/fetch/stream/{id}
  GET  /api/matches
  GET  /api/matches/{id}
  GET  /api/matches/{id}/dashboard
  GET  /api/usage

Misc:
  GET  /api/resources
"""
from __future__ import annotations
import asyncio
import json
import logging
import os
import re
import uuid
from datetime import date
from pathlib import Path
from typing import Optional

from fastapi import Cookie, FastAPI, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address
from starlette.middleware.base import BaseHTTPMiddleware

from web_database import Database
from rlcoach.web_pipeline import run_pipeline_job

log = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

# ── Config from environment ───────────────────────────────────────────────────
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
DAILY_LIMIT       = int(os.environ.get("DAILY_ANALYSIS_LIMIT", "5"))
SECURE_COOKIES    = os.environ.get("SECURE_COOKIES", "false").lower() == "true"
ALLOWED_ORIGINS   = [o.strip() for o in os.environ.get("ALLOWED_ORIGINS", "").split(",") if o.strip()]

# ── Rate limiter ──────────────────────────────────────────────────────────────
_limiter = Limiter(key_func=get_remote_address, default_limits=["200/minute"])

# ── App setup ─────────────────────────────────────────────────────────────────
app = FastAPI(title="RLCoach", docs_url=None, redoc_url=None)
app.state.limiter = _limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

db = Database()

# ── Security headers middleware ───────────────────────────────────────────────
class _SecurityHeaders(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        resp = await call_next(request)
        resp.headers["X-Content-Type-Options"] = "nosniff"
        resp.headers["X-Frame-Options"]        = "DENY"
        resp.headers["X-XSS-Protection"]       = "1; mode=block"
        resp.headers["Referrer-Policy"]        = "strict-origin-when-cross-origin"
        resp.headers["Permissions-Policy"]     = "geolocation=(), microphone=(), camera=()"
        if SECURE_COOKIES:
            resp.headers["Strict-Transport-Security"] = "max-age=63072000; includeSubDomains; preload"
        return resp

app.add_middleware(_SecurityHeaders)

# ── CORS (lock down to configured origins in production) ──────────────────────
if ALLOWED_ORIGINS:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=ALLOWED_ORIGINS,
        allow_credentials=True,
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type"],
    )

# ── Helpers ───────────────────────────────────────────────────────────────────
_EMAIL_RE = re.compile(r"^[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}$")
_PLAYER_ID_RE = re.compile(r"^(steam|epic|ps4|ps5|xbl|switch):[a-zA-Z0-9_\-\.]{1,64}$")

def _set_session_cookie(response: Response, session_id: str) -> None:
    response.set_cookie(
        "session_id", session_id,
        httponly=True,
        samesite="strict",
        secure=SECURE_COOKIES,
        max_age=90 * 86400,
    )

def _clear_session_cookie(response: Response) -> None:
    response.delete_cookie("session_id", httponly=True, samesite="strict", secure=SECURE_COOKIES)


@app.on_event("startup")
async def _startup():
    await db.init()
    log.info("RLCoach started. API key=%s  secure_cookies=%s  allowed_origins=%s",
             "set" if ANTHROPIC_API_KEY else "MISSING",
             SECURE_COOKIES, ALLOWED_ORIGINS or "any (dev)")


@app.on_event("shutdown")
async def _shutdown():
    await db.close()


app.mount("/static", StaticFiles(directory="static"), name="static")


# ── session helpers ────────────────────────────────────────────────────────────

async def _require_session(session_id: Optional[str]) -> dict:
    if not session_id:
        raise HTTPException(401, "Not logged in")
    session = await db.get_session(session_id)
    if not session:
        raise HTTPException(401, "Session expired — please log in again")
    return session


async def _require_epic(session: dict) -> None:
    if not session.get("eos_account_id") or not session.get("auth_tokens"):
        raise HTTPException(400, "Connect your Epic Games account first")


# ── frontend ──────────────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def frontend():
    index = Path("static/index.html")
    return HTMLResponse(index.read_text(encoding="utf-8"))


@app.get("/favicon.ico")
async def favicon():
    p = Path("static/favicon.ico")
    if p.exists():
        return FileResponse(str(p), media_type="image/x-icon")
    raise HTTPException(404)


# ── RLCoach account auth ───────────────────────────────────────────────────────

@app.post("/api/register")
@_limiter.limit("5/minute;20/hour")
async def register(request: Request, response: Response):
    body = await request.json()
    email    = (body.get("email") or "").strip()[:254]
    password = (body.get("password") or "")[:128]

    if not _EMAIL_RE.match(email):
        raise HTTPException(400, "Invalid email address")
    if len(password) < 8:
        raise HTTPException(400, "Password must be at least 8 characters")

    existing = await db.get_user_by_email(email)
    if existing:
        raise HTTPException(409, "An account with that email already exists")

    user_id = str(uuid.uuid4())
    session_id = str(uuid.uuid4())
    await db.create_user(user_id, email, password)
    await db.create_session(session_id, user_id)

    _set_session_cookie(response, session_id)
    return {"status": "ok"}


@app.post("/api/login")
@_limiter.limit("10/minute;30/hour")
async def login(request: Request, response: Response):
    body = await request.json()
    email    = (body.get("email") or "").strip()[:254]
    password = (body.get("password") or "")[:128]

    user = await db.get_user_by_email(email)
    # Always run verify_password even on miss to prevent timing attacks
    valid = db.verify_password(password, user) if user else False
    if not user or not valid:
        raise HTTPException(401, "Incorrect email or password")

    session = await db.get_session_by_user_id(user["user_id"])
    if session:
        session_id = session["session_id"]
        await db.activate_session(session_id)
    else:
        session_id = str(uuid.uuid4())
        await db.create_session(session_id, user["user_id"])

    _set_session_cookie(response, session_id)
    return {"status": "ok"}


@app.post("/api/logout")
async def logout(response: Response, session_id: Optional[str] = Cookie(default=None)):
    if session_id:
        await db.deactivate_session(session_id)
    _clear_session_cookie(response)
    return {"status": "logged_out"}


@app.post("/api/account/delete")
async def delete_account(response: Response, session_id: Optional[str] = Cookie(default=None)):
    session = await _require_session(session_id)
    sid = session["session_id"]
    await db.delete_account(sid)
    # Remove this user's replay output / DB-adjacent files
    import shutil
    out = Path("data") / "output" / sid
    if out.exists():
        shutil.rmtree(out, ignore_errors=True)
    _clear_session_cookie(response)
    return {"status": "deleted"}


@app.get("/api/me")
async def me(session_id: Optional[str] = Cookie(default=None)):
    if not session_id:
        return {"logged_in": False}
    session = await db.get_session(session_id)
    if not session:
        return {"logged_in": False}
    return {
        "logged_in": True,
        "session_id": session["session_id"],
        "epic_connected": bool(session.get("eos_account_id")),
        "eos_account_id": session.get("eos_account_id"),
        "display_name": session.get("display_name"),
        "player_id": session.get("player_id"),
    }


# ── Epic Games connect/disconnect ─────────────────────────────────────────────

@app.post("/api/epic/start")
async def epic_start(session_id: Optional[str] = Cookie(default=None)):
    await _require_session(session_id)
    from rlapi.egs import EGS, authenticate_with_device

    def _start():
        egs = EGS()
        try:
            return authenticate_with_device(egs)
        finally:
            egs.close()

    loop = asyncio.get_event_loop()
    try:
        device = await loop.run_in_executor(None, _start)
    except Exception as e:
        raise HTTPException(503, f"Epic auth init failed: {e}")

    return {
        "user_code": device.user_code,
        "device_code": device.device_code,
        "verification_uri": device.verification_uri,
        "expires_in": device.expires_in,
        "interval": device.interval,
    }


@app.get("/api/epic/poll/{device_code}")
async def epic_poll(device_code: str, response: Response,
                    session_id: Optional[str] = Cookie(default=None)):
    session = await _require_session(session_id)
    from rlapi.egs import EGS, get_eos_display_name

    def _try_exchange():
        egs = EGS()
        try:
            return egs._request_eos_token({"grant_type": "device_code", "device_code": device_code})
        finally:
            egs.close()

    loop = asyncio.get_event_loop()
    try:
        eos = await loop.run_in_executor(None, _try_exchange)
    except Exception as e:
        msg = str(e)
        if "authorization_pending" in msg or "slow_down" in msg:
            return {"status": "pending"}
        if "expired" in msg or "timeout" in msg:
            return {"status": "expired"}
        return {"status": "error", "message": msg}

    # Resolve the real Epic username (falls back to the account id)
    display_name = await loop.run_in_executor(
        None, get_eos_display_name, eos.access_token, eos.account_id
    ) or eos.account_id

    tokens = {
        "eos_access_token": eos.access_token,
        "eos_refresh_token": eos.refresh_token,
        "eos_expires_at": eos.expires_at,
        "eos_refresh_expires_at": eos.refresh_expires_at,
        "account_id": eos.account_id,
        "display_name": display_name,
    }
    await db.connect_epic(session["session_id"], eos.account_id, display_name, tokens)
    return {"status": "complete", "account_id": eos.account_id, "display_name": display_name}


@app.post("/api/epic/disconnect")
async def epic_disconnect(session_id: Optional[str] = Cookie(default=None)):
    session = await _require_session(session_id)
    await db.disconnect_epic(session["session_id"])
    return {"status": "disconnected"}


@app.post("/api/epic/refresh-name")
async def epic_refresh_name(session_id: Optional[str] = Cookie(default=None)):
    """Re-fetch the Epic display name in place (no disconnect) and update session + profile."""
    session = await _require_session(session_id)
    if not session.get("eos_account_id"):
        raise HTTPException(400, "Connect your Epic account first")

    from rlcoach.web_pipeline import get_web_credentials
    from rlapi.egs import get_eos_display_name

    creds = await get_web_credentials(session, db)
    if not creds:
        raise HTTPException(400, "Epic auth expired — reconnect your account")
    access_token, account_id, _ = creds

    loop = asyncio.get_event_loop()
    name = await loop.run_in_executor(None, get_eos_display_name, access_token, account_id)
    if not name:
        return {"status": "unchanged", "display_name": session.get("display_name")}
    await db.update_display_name(session["session_id"], name)
    return {"status": "ok", "display_name": name}


@app.post("/api/auth/player_id")
async def set_player_id(request: Request, session_id: Optional[str] = Cookie(default=None)):
    session = await _require_session(session_id)
    body = await request.json()
    player_id = (body.get("player_id") or "").strip()[:80]
    if not player_id:
        raise HTTPException(400, "player_id required")
    # Accept loose format — log a warning if it doesn't match expected pattern
    if not _PLAYER_ID_RE.match(player_id):
        log.warning("Unexpected player_id format: %s", player_id[:20])
    await db.update_player_id(session["session_id"], player_id)
    return {"status": "ok", "player_id": player_id}


# ── rank detection ─────────────────────────────────────────────────────────────

@app.get("/api/rank")
async def get_ranks(session_id: Optional[str] = Cookie(default=None)):
    """
    Fetch all ranked playlist ranks from PsyNet for the connected Epic account.
    Returns {ranks: {playlist_label: {rank, tier, icon_url, mmr_estimate}}}
    """
    session = await _require_session(session_id)
    if not session.get("eos_account_id"):
        return {"ranks": {}, "available": False}

    from rlcoach.web_pipeline import get_web_credentials
    from rlcoach.stats_api import fetch_all_ranks

    creds = await get_web_credentials(session, db)
    if not creds:
        return {"ranks": {}, "available": False, "error": "Epic auth expired"}

    access_token, account_id, display_name = creds
    ranks = await fetch_all_ranks(access_token, account_id, display_name)
    return {"ranks": ranks, "available": bool(ranks)}


# ── replay fetch ──────────────────────────────────────────────────────────────

@app.post("/api/fetch")
async def trigger_fetch(session_id: Optional[str] = Cookie(default=None)):
    session = await _require_session(session_id)
    await _require_epic(session)

    if not session.get("player_id"):
        raise HTTPException(400, "Set your player ID before fetching replays")

    active = await db.get_active_job(session["session_id"])
    if active:
        prog = json.loads(active["progress"])
        return {"job_id": active["job_id"], "status": "already_running",
                "active_type": prog.get("type", "fetch")}

    job_id = str(uuid.uuid4())
    await db.create_job(job_id, session["session_id"])
    asyncio.create_task(
        run_pipeline_job(job_id, dict(session), db, ANTHROPIC_API_KEY)
    )
    return {"job_id": job_id, "status": "started"}


@app.get("/api/fetch/status/{job_id}")
async def fetch_status(job_id: str, session_id: Optional[str] = Cookie(default=None)):
    session = await _require_session(session_id)
    job = await db.get_job(job_id)
    if not job or job["session_id"] != session["session_id"]:
        raise HTTPException(404)
    return json.loads(job["progress"])


@app.get("/api/fetch/stream/{job_id}")
async def fetch_stream(job_id: str, session_id: Optional[str] = Cookie(default=None)):
    session = await _require_session(session_id)

    async def _gen():
        last_seen = None
        for _ in range(720):
            job = await db.get_job(job_id)
            if not job or job["session_id"] != session["session_id"]:
                yield 'data: {"status":"error","step":"Job not found"}\n\n'
                return
            ps = job["progress"]
            if ps != last_seen:
                last_seen = ps
                yield f"data: {ps}\n\n"
                if json.loads(ps).get("status") in ("complete", "error"):
                    return
            await asyncio.sleep(1)

    return StreamingResponse(_gen(), media_type="text/event-stream")


# ── matches ────────────────────────────────────────────────────────────────────

@app.get("/api/matches")
async def list_matches(session_id: Optional[str] = Cookie(default=None)):
    session = await _require_session(session_id)
    return await db.get_matches(session["session_id"])


@app.get("/api/matches/{match_id}")
async def get_match(match_id: str, session_id: Optional[str] = Cookie(default=None)):
    session = await _require_session(session_id)
    m = await db.get_match(match_id, session["session_id"])
    if not m:
        raise HTTPException(404)
    return m


@app.get("/api/matches/{match_id}/dashboard")
async def match_dashboard(match_id: str, session_id: Optional[str] = Cookie(default=None)):
    session = await _require_session(session_id)
    m = await db.get_match(match_id, session["session_id"])
    if not m:
        raise HTTPException(404)
    path = Path(m["folder_path"]) / "dashboard.html"
    if not path.exists():
        raise HTTPException(404, "AI dashboard not yet generated for this match")
    html = path.read_text(encoding="utf-8")
    html = _inject_dashboard_nav(html)
    return HTMLResponse(html)


@app.post("/api/matches/{match_id}/analyze")
async def analyze_match(match_id: str, session_id: Optional[str] = Cookie(default=None)):
    """Trigger on-demand AI analysis for a single already-parsed match."""
    session = await _require_session(session_id)
    m = await db.get_match(match_id, session["session_id"])
    if not m:
        raise HTTPException(404)
    if m.get("has_analysis"):
        return {"status": "already_done"}

    # Daily cap check up-front (the job re-checks too)
    today = date.today().isoformat()
    if session.get("eos_account_id"):
        used = await db.get_usage(session["eos_account_id"], today)
        if used >= DAILY_LIMIT:
            raise HTTPException(429, f"Daily AI limit reached ({used}/{DAILY_LIMIT}). Try again tomorrow.")

    # One job at a time per session (prevents ledger/output races)
    active = await db.get_active_job(session["session_id"])
    if active:
        prog = json.loads(active["progress"])
        return {"job_id": active["job_id"], "status": "already_running",
                "active_type": prog.get("type", "fetch"),
                "active_match": prog.get("match_id")}

    from rlcoach.web_pipeline import run_analysis_job
    job_id = str(uuid.uuid4())
    await db.create_job(job_id, session["session_id"])
    asyncio.create_task(run_analysis_job(job_id, dict(session), dict(m), db, ANTHROPIC_API_KEY))
    return {"job_id": job_id, "status": "started"}


def _inject_dashboard_nav(html: str) -> str:
    """Prepend a slim 'back to RLCoach' bar to a generated match dashboard."""
    nav = (
        '<div style="position:sticky;top:0;z-index:9999;display:flex;align-items:center;'
        'gap:14px;padding:9px 18px;background:#0b1420;border-bottom:1px solid #1b2a3e;'
        'font-family:Oxanium,system-ui,sans-serif">'
        '<a href="/" style="display:inline-flex;align-items:center;gap:8px;color:#34d6f7;text-decoration:none;font-weight:700;font-size:15px">'
        '&larr; <img src="/static/logo.png" alt="RLCoach" style="height:22px;width:auto"/></a>'
        '<span style="font-family:IBM Plex Mono,monospace;font-size:11px;color:#56697f">'
        'AI Match Report</span></div>'
    )
    marker = '<div class="wrap">'
    i = html.find(marker)
    if i != -1:
        return html[:i] + nav + html[i:]
    if "<body" in html:
        idx = html.find(">", html.find("<body")) + 1
        return html[:idx] + nav + html[idx:]
    return nav + html


# ── usage ─────────────────────────────────────────────────────────────────────

@app.get("/api/usage")
async def usage(session_id: Optional[str] = Cookie(default=None)):
    session = await _require_session(session_id)
    if not session.get("eos_account_id"):
        return {"today": 0, "limit": DAILY_LIMIT, "remaining": DAILY_LIMIT, "has_api_key": bool(ANTHROPIC_API_KEY)}
    today = date.today().isoformat()
    count = await db.get_usage(session["eos_account_id"], today)
    return {
        "today": count,
        "limit": DAILY_LIMIT,
        "remaining": max(0, DAILY_LIMIT - count),
        "has_api_key": bool(ANTHROPIC_API_KEY),
    }


# ── profile ───────────────────────────────────────────────────────────────────

@app.get("/api/profile")
async def get_profile(session_id: Optional[str] = Cookie(default=None)):
    session = await _require_session(session_id)
    return await db.get_profile(session["session_id"]) or {}


@app.post("/api/profile")
async def save_profile(request: Request, session_id: Optional[str] = Cookie(default=None)):
    session = await _require_session(session_id)
    body = await request.json()
    body["display_name"] = session.get("display_name") or body.get("display_name")
    await db.upsert_profile(session["session_id"], body)
    return {"status": "ok"}


# ── coaching generation ────────────────────────────────────────────────────────

@app.post("/api/coaching/generate")
async def coaching_generate(session_id: Optional[str] = Cookie(default=None)):
    session = await _require_session(session_id)
    await _require_epic(session)

    if not session.get("player_id"):
        raise HTTPException(400, "Set your player ID first")

    profile = await db.get_profile(session["session_id"])
    if not profile:
        raise HTTPException(400, "Complete your profile setup first")

    # One job at a time per session (prevents ledger/output races)
    active = await db.get_active_job(session["session_id"])
    if active:
        prog = json.loads(active["progress"])
        return {"job_id": active["job_id"], "status": "already_running",
                "active_type": prog.get("type", "fetch")}

    job_id = str(uuid.uuid4())
    await db.create_job(job_id, session["session_id"])
    asyncio.create_task(
        _run_coaching_job(job_id, dict(session), dict(profile), db, ANTHROPIC_API_KEY)
    )
    return {"job_id": job_id, "status": "started"}


@app.get("/api/coaching")
async def get_coaching(session_id: Optional[str] = Cookie(default=None)):
    session = await _require_session(session_id)
    plan = await db.get_latest_coaching_plan(session["session_id"])
    if not plan:
        return {"exists": False}
    return {
        "exists": True,
        "plan_id": plan["plan_id"],
        "generated_at": plan["generated_at"],
        "replay_guids": plan["replay_guids"],
    }


@app.get("/api/coaching/view")
async def view_coaching(session_id: Optional[str] = Cookie(default=None)):
    session = await _require_session(session_id)
    plan = await db.get_latest_coaching_plan(session["session_id"])
    if not plan:
        raise HTTPException(404, "No coaching plan yet")
    return HTMLResponse(_render_coaching_html(plan["content_md"]))


# ── tracker ───────────────────────────────────────────────────────────────────

@app.get("/api/tracker")
async def get_tracker(session_id: Optional[str] = Cookie(default=None)):
    session = await _require_session(session_id)
    return await db.get_tracker(session["session_id"])


@app.post("/api/tracker")
async def save_tracker(request: Request, session_id: Optional[str] = Cookie(default=None)):
    session = await _require_session(session_id)
    body = await request.json()
    if len(json.dumps(body)) > 200_000:
        raise HTTPException(413, "Tracker state too large")
    await db.save_tracker(session["session_id"], body)
    return {"status": "ok"}


# ── resources ─────────────────────────────────────────────────────────────────

@app.get("/api/resources")
async def resources():
    from rlcoach.training_resources import RANK_LADDER, PLAYLIST_OPTIONS, PLATFORM_OPTIONS
    return {
        "ranks": RANK_LADDER,
        "playlists": PLAYLIST_OPTIONS,
        "platforms": PLATFORM_OPTIONS,
    }


# ── coaching background job ────────────────────────────────────────────────────

async def _run_coaching_job(
    job_id: str, session: dict, profile: dict, db, api_key: str
) -> None:
    from rlcoach.web_pipeline import get_web_credentials, _Progress
    from rlcoach.replay_selector import find_win_and_loss
    from rlcoach.stats_api import fetch_player_stats
    from rlcoach.coaching_engine import generate_coaching_plan
    from rlcoach.ledger import Ledger

    p = _Progress(job_id, db)
    await p.update(status="running", step="Starting coaching analysis…", type="coaching")

    session_id = session["session_id"]
    player_id = session.get("player_id") or ""
    gamemode = profile.get("gamemode", "2v2")
    team_size = profile.get("team_size", 2)

    creds = await get_web_credentials(session, db)
    if not creds:
        await p.error("Epic auth expired — please reconnect your Epic account")
        return
    access_token, account_id, display_name = creds

    output_dir = Path("data") / "output" / session_id
    output_dir.mkdir(parents=True, exist_ok=True)
    ledger = Ledger(output_dir / "processed.json")

    await p.msg("Fetching your current rank…")
    stats = None
    try:
        stats = await fetch_player_stats(access_token, account_id, display_name, gamemode)
        if stats.get("rank"):
            await p.msg(f"Rank: {stats['rank']} ({gamemode})")
            await db.update_profile_stats(session_id, stats)
        else:
            await p.msg("Rank not available from API — using self-reported rank")
    except Exception as e:
        await p.msg(f"Stats fetch skipped: {e}")

    await p.update(step=f"Searching for a win and a loss in {gamemode}…")

    async def _cb(msg: str):
        await p.msg(msg)

    win, loss = await find_win_and_loss(
        access_token, account_id, display_name,
        player_id, gamemode, team_size,
        output_dir, ledger, progress_cb=_cb,
    )

    if win is None and loss is None:
        await p.error(
            f"No full competitive {gamemode} games found in your recent history. "
            f"The plan only uses ranked {gamemode} matches (not casual, and not "
            "Dropshot/Rumble/Hoops/Snow Day). Play a few ranked games, then try again."
        )
        return

    if win is None:
        await p.msg("No recent win found — plan based on loss only")
    if loss is None:
        await p.msg("No recent loss found — plan based on win only")

    await p.update(step="Generating your personalised coaching plan with AI…")
    await p.msg("Calling Claude Sonnet 4.6…")

    loop = asyncio.get_event_loop()
    try:
        plan = await loop.run_in_executor(
            None, generate_coaching_plan, profile, win, loss, stats, api_key
        )
    except Exception as e:
        await p.error(f"Coaching plan generation failed: {e}")
        return

    plan_id = str(uuid.uuid4())
    guids = [r.guid for r in [win, loss] if r is not None]
    await db.save_coaching_plan(plan_id, session_id, json.dumps(plan), guids)

    # Seed the tracker — keep the player's MMR history, reset per-plan checkmarks
    existing = await db.get_tracker(session_id)
    await db.save_tracker(session_id, {
        "mmrLog": existing.get("mmrLog", []),
        "drillsDone": {},
        "weeklyDone": {},
    })

    for r in [win, loss]:
        if r is None:
            continue
        await db.upsert_match(
            r.guid, session_id, str(r.folder_path),
            {"guid": r.guid, "map_display": r.map_display, "result": r.result_str,
             "win": r.is_win, "duration_s": r.duration_s, "coaching_source": True},
        )

    state = {"status": "complete", "step": "Coaching plan ready!", "coaching_ready": True,
             "total": 0, "current": 0, "messages": []}
    await db.update_job(job_id, state)
    log.info("Coaching job %s complete for session %s", job_id, session_id)


def _render_coaching_html(plan_json_str: str) -> str:
    """Inject the PLAN object into the interactive coaching dashboard template."""
    template = Path("static/coaching_template.html").read_text(encoding="utf-8")
    try:
        plan = json.loads(plan_json_str)
    except Exception:
        plan = {}
    injected = "const PLAN = " + json.dumps(plan, ensure_ascii=False) + ";"
    if "const PLAN = {};" in template:
        return template.replace("const PLAN = {};", injected, 1)
    return template.replace("/*PLAN_INJECT*/", injected, 1)
