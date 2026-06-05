"""
Async pipeline runner for the web app.

Orchestrates: credential refresh → PsyNet poll → per-replay processing
→ extended metrics → optional Claude analysis → DB progress updates.

All CPU-heavy sync work (parse, metrics, render, Claude) runs in a thread
pool executor so the FastAPI event loop stays unblocked.
"""
from __future__ import annotations
import asyncio
import json
import logging
import shutil
import tempfile
import types
from datetime import date, timezone
from pathlib import Path
from typing import Optional

log = logging.getLogger(__name__)

DAILY_LIMIT = 5


# ── credential management ──────────────────────────────────────────────────────

async def get_web_credentials(session: dict, db) -> Optional[tuple]:
    """
    Return (access_token, account_id, display_name) or None.
    Transparently refreshes expired access tokens and persists new ones to DB.
    """
    from rlcoach.psynet_auth import _is_expired
    from rlapi.egs import EGS

    tokens = json.loads(session.get("auth_tokens") or "{}")
    if not tokens:
        return None

    access_token = tokens.get("eos_access_token", "")
    refresh_token = tokens.get("eos_refresh_token", "")
    expires_at = tokens.get("eos_expires_at", "")
    refresh_expires_at = tokens.get("eos_refresh_expires_at", "")
    account_id = tokens.get("account_id", "")
    display_name = tokens.get("display_name", "Player")

    if not access_token or not account_id:
        return None

    if not _is_expired(expires_at):
        return access_token, account_id, display_name

    if not refresh_token or _is_expired(refresh_expires_at):
        log.warning("Refresh token expired — re-auth required")
        return None

    # Refresh in executor (blocking HTTP call)
    def _do_refresh():
        egs = EGS()
        try:
            return egs.refresh_eos_token(refresh_token)
        finally:
            egs.close()

    try:
        loop = asyncio.get_event_loop()
        new_eos = await loop.run_in_executor(None, _do_refresh)
    except Exception as e:
        log.warning("Token refresh failed: %s", e)
        return None

    new_tokens = {
        "eos_access_token": new_eos.access_token,
        "eos_refresh_token": new_eos.refresh_token,
        "eos_expires_at": new_eos.expires_at,
        "eos_refresh_expires_at": new_eos.refresh_expires_at,
        "account_id": new_eos.account_id,
        "display_name": display_name,
    }
    await db.update_tokens(session["session_id"], new_tokens)
    log.info("EOS token refreshed for %s", account_id)
    return new_eos.access_token, new_eos.account_id, display_name


# ── sync processing (runs in executor) ───────────────────────────────────────

def _process_replay_sync(
    replay_path: Path,
    guid: str,
    player_id: str,
    output_dir: Path,
    ledger,
) -> Optional[dict]:
    """
    Full pipeline for one replay: parse → metrics → moments → render → write.
    Returns the match summary dict or None on failure.
    """
    from rlcoach.parser import parse_replay
    from rlcoach.metrics import compute_metrics
    from rlcoach.events import extract_moments
    from rlcoach.renderer import render_moment
    from rlcoach.digest import write_match_json, write_match_md
    from rlcoach.ledger import file_hash
    import pandas as pd
    import re as _re

    match_id = file_hash(replay_path)

    cfg_thresh = types.SimpleNamespace(
        slow_recovery_s=3.0,
        double_commit_min_duration_s=1.0,
        file_stable_wait_s=3.0,
        kickoff_concede_window_s=10.0,
    )

    # Parse
    try:
        parsed = parse_replay(replay_path, match_id)
    except Exception as e:
        log.error("Parse failed for %s: %s", guid[:8], e)
        return None

    # Metrics
    metrics = compute_metrics(
        parsed, player_id,
        slow_recovery_s=cfg_thresh.slow_recovery_s,
        double_commit_min_s=cfg_thresh.double_commit_min_duration_s,
    )

    # Tracked player's team
    from rlcoach.metrics import _is_me
    me_pm = next((pm for pm in metrics.players if pm.is_me), None)
    my_team = me_pm.team if me_pm else "blue"

    # Moments
    moments = extract_moments(parsed, metrics, cfg_thresh.slow_recovery_s)

    # Output folder
    date_str = (parsed.date or "00000000").replace("-", "").replace("T", "")[:8]
    map_clean = _re.sub(r"(_GRS)?_[Pp]$", "", parsed.map_name or "Unknown")
    map_safe = map_clean.replace(" ", "-")[:24]
    mode = f"{parsed.team_size or 2}v{parsed.team_size or 2}"
    if my_team == "orange":
        my_score, opp_score = parsed.orange_score, parsed.blue_score
    else:
        my_score, opp_score = parsed.blue_score, parsed.orange_score
    result_str = (
        f"W{my_score}-{opp_score}" if my_score > opp_score else
        (f"L{my_score}-{opp_score}" if opp_score > my_score else f"D{my_score}-{opp_score}")
    )
    folder_name = f"{date_str}_{map_safe}_{mode}_{result_str}"
    out_dir = output_dir / folder_name
    moments_dir = out_dir / "moments"
    out_dir.mkdir(parents=True, exist_ok=True)
    moments_dir.mkdir(parents=True, exist_ok=True)

    # Parquet
    if parsed.frame_df is not None and len(parsed.frame_df) > 0:
        try:
            df_save = parsed.frame_df.copy()
            for col in df_save.columns:
                if df_save[col].dtype == object:
                    df_save[col] = pd.to_numeric(df_save[col], errors="coerce").astype("float32")
            df_save.to_parquet(str(out_dir / "frames.parquet"))
        except Exception as e:
            log.warning("Parquet save failed: %s", e)

    # Render diagrams
    for m in moments:
        ts_str = f"{int(m.t):04d}"
        out_png = moments_dir / f"{ts_str}_{m.type}.png"
        if m.snapshot:
            ok = render_moment(
                snapshot=m.snapshot or {},
                output_path=out_png,
                title=m.type.replace("_", " ").title(),
                extra_snapshots=m.extra_snapshots or None,
            )
            if ok:
                m.diagram = f"moments/{ts_str}_{m.type}.png"

    # Write digest
    write_match_json(parsed, metrics, moments, out_dir)
    write_match_md(parsed, metrics, moments, out_dir)

    # Mark in ledger
    ledger.mark_processed(replay_path, str(out_dir), match_id)
    if guid:
        ledger.mark_processed_guid(guid, str(out_dir))

    # Build summary dict for DB
    blue_players = [
        {"name": pm.name, "is_me": pm.is_me, "goals": pm.core.get("goals", 0),
         "shots": pm.core.get("shots", 0), "saves": pm.core.get("saves", 0),
         "score": pm.core.get("score", 0)}
        for pm in metrics.players if pm.team == "blue"
    ]
    orange_players = [
        {"name": pm.name, "is_me": pm.is_me, "goals": pm.core.get("goals", 0),
         "shots": pm.core.get("shots", 0), "saves": pm.core.get("saves", 0),
         "score": pm.core.get("score", 0)}
        for pm in metrics.players if pm.team == "orange"
    ]
    summary = {
        "match_id": match_id,
        "guid": guid,
        "folder": folder_name,
        "folder_path": str(out_dir),
        "map": parsed.map_name,
        "map_display": map_clean.replace("_", " ").strip(),
        "mode": mode,
        "date": parsed.date or "",
        "result": result_str,
        "win": my_score > opp_score,
        "blue_score": parsed.blue_score,
        "orange_score": parsed.orange_score,
        "my_team": my_team,
        "duration_s": parsed.duration_s,
        "double_commits": len(metrics.double_commit_events),
        "players_blue": blue_players,
        "players_orange": orange_players,
    }
    return summary


def _run_claude_analysis_sync(
    match_json_path: Path,
    frames_parquet_path: Path,
    api_key: str,
) -> Optional[str]:
    """
    Load match data + compute extended metrics, then call Claude.
    Returns HTML string or None on failure.
    """
    import json as _json
    from rlcoach.extended_metrics import compute_extended_metrics

    # Load match.json
    try:
        match_data = _json.loads(match_json_path.read_text(encoding="utf-8"))
    except Exception as e:
        log.error("Failed to read match.json: %s", e)
        return None

    # Load frames.parquet for extended metrics
    try:
        import pandas as pd
        frame_df = pd.read_parquet(str(frames_parquet_path))
    except Exception as e:
        log.warning("Could not load frames.parquet: %s — extended metrics unavailable", e)
        frame_df = None

    # Rebuild a minimal ParsedReplay-like object for extended_metrics
    ext_metrics = {}
    if frame_df is not None:
        try:
            # Reconstruct minimal parsed object needed by extended_metrics
            goals_raw = match_data.get("team_metrics", {})
            duration_s = match_data.get("duration_s", 300)
            player_id = match_data.get("me", {}).get("platform_id", "")

            class _FakePlayer:
                def __init__(self, pd):
                    self.name = pd.get("name", "")
                    self.platform_id = pd.get("platform_id", "")
                    self.team = pd.get("team", "blue")
                    self.is_orange = self.team == "orange"

            class _FakeGoal:
                def __init__(self, gd):
                    self.time_s = gd.get("t", 0)
                    self.scoring_team = gd.get("team", "blue")
                    # Map "A" → match_data my_team, "B" → opponent
                    # The match.json stores goals in digest format
                    # We just need scoring_team as a string

            class _FakeParsed:
                pass

            fake_parsed = _FakeParsed()
            fake_parsed.players = [_FakePlayer(p) for p in match_data.get("players", [])]
            # Goals from moments
            fake_parsed.goals = []
            for m in match_data.get("moments", []):
                if "goal" in m.get("type", ""):
                    class _G:
                        pass
                    g = _G()
                    g.time_s = m["t"]
                    g.scoring_team = "blue"  # best effort
                    fake_parsed.goals.append(g)

            my_player_id = player_id
            ext_metrics = compute_extended_metrics(frame_df, fake_parsed, my_player_id, duration_s)
        except Exception as e:
            log.warning("Extended metrics computation failed: %s", e)
            ext_metrics = {"error": str(e)}

    from rlcoach.claude_analyst import analyse_match
    try:
        html = analyse_match(match_data, ext_metrics, api_key)
        return html
    except Exception as e:
        log.error("Claude analysis failed: %s", e)
        return None


# ── download ───────────────────────────────────────────────────────────────────

async def _download_replay(url: str) -> Path:
    import httpx
    tmp = Path(tempfile.mktemp(suffix=".replay"))
    async with httpx.AsyncClient(timeout=120.0, follow_redirects=True) as client:
        async with client.stream("GET", url) as resp:
            resp.raise_for_status()
            with open(tmp, "wb") as f:
                async for chunk in resp.aiter_bytes(65536):
                    f.write(chunk)
    return tmp


# ── progress helper ────────────────────────────────────────────────────────────

class _Progress:
    def __init__(self, job_id: str, db):
        self._job_id = job_id
        self._db = db
        self._state = {
            "status": "running",
            "step": "Starting…",
            "total": 0,
            "current": 0,
            "messages": [],
            "matches": [],
        }

    async def update(self, **kwargs):
        self._state.update(kwargs)
        await self._db.update_job(self._job_id, self._state)

    async def msg(self, text: str):
        self._state["messages"] = (self._state["messages"] + [text])[-20:]
        await self._db.update_job(self._job_id, self._state)

    async def done(self, matches: list):
        self._state.update({"status": "complete", "step": "Done", "matches": matches})
        await self._db.update_job(self._job_id, self._state)

    async def error(self, text: str):
        self._state.update({"status": "error", "step": text})
        await self._db.update_job(self._job_id, self._state)


# ── main pipeline coroutine ────────────────────────────────────────────────────

async def run_pipeline_job(
    job_id: str,
    session: dict,
    db,
    api_key: str,
) -> None:
    """
    Full async pipeline. Runs as a background task in the FastAPI event loop.
    Heavy sync work dispatched to a thread-pool executor.
    """
    from rlcoach.ledger import Ledger

    progress = _Progress(job_id, db)
    await progress.update(status="running", step="Authenticating…")

    loop = asyncio.get_event_loop()
    session_id = session["session_id"]
    player_id = session.get("player_id") or ""
    eos_account_id = session.get("eos_account_id", "")

    # 1. Credentials
    creds = await get_web_credentials(session, db)
    if creds is None:
        await progress.error("Epic sign-in expired — open the ⚙ menu (top right) → "
                             "Reconnect Epic, then try again.")
        return
    access_token, account_id, display_name = creds

    # 2. Output dir + ledger (per session)
    output_dir = Path("data") / "output" / session_id
    output_dir.mkdir(parents=True, exist_ok=True)
    ledger_path = output_dir / "processed.json"
    ledger = Ledger(ledger_path)

    # 3. Connect to PsyNet
    await progress.update(step="Connecting to PsyNet…")
    try:
        from rlapi.client import create_client
        client = await create_client(access_token, account_id, display_name)
    except Exception as e:
        await progress.error(f"PsyNet connection failed: {e}")
        return

    # 4. Fetch match history
    await progress.update(step="Fetching match history…")
    try:
        matches = await client.get_match_history(timeout=20.0)
    except Exception as e:
        await progress.error(f"Failed to get match history: {e}")
        try:
            await client.close()
        except Exception:
            pass
        return
    finally:
        try:
            await client.close()
        except Exception:
            pass

    # 5. Filter to new
    new_entries = []
    for entry in matches:
        md = entry.get("Match", {})
        guid = md.get("MatchGUID", "")
        url = entry.get("ReplayUrl", "")
        if not guid or not url:
            continue
        if ledger.is_processed_guid(guid):
            continue
        new_entries.append((guid, url))

    total = len(new_entries)
    await progress.update(step=f"Found {total} new replays", total=total, current=0)
    if total == 0:
        await progress.done([])
        return

    # 6. Process each replay
    processed_summaries = []
    today_str = date.today().isoformat()

    for i, (guid, replay_url) in enumerate(new_entries):
        short = guid[:8]
        await progress.update(
            step=f"Processing {short}… ({i+1}/{total})",
            current=i,
        )
        await progress.msg(f"Downloading {short}…")

        # Download
        try:
            tmp_path = await _download_replay(replay_url)
        except Exception as e:
            await progress.msg(f"Download failed for {short}: {e}")
            ledger.mark_processed_guid(guid, "", skipped=True)
            continue

        # Debug copy
        debug_dir = output_dir / "failed_replays"
        debug_dir.mkdir(exist_ok=True)
        debug_copy = debug_dir / f"{short}.replay"
        shutil.copy2(str(tmp_path), str(debug_copy))

        await progress.msg(f"Parsing {short}…")

        # Parse + process (sync, in executor)
        try:
            summary = await loop.run_in_executor(
                None, _process_replay_sync, tmp_path, guid, player_id, output_dir, ledger
            )
        except Exception as e:
            await progress.msg(f"Processing error for {short}: {e}")
            summary = None
        finally:
            try:
                tmp_path.unlink(missing_ok=True)
                debug_copy.unlink(missing_ok=True)
            except Exception:
                pass

        if summary is None:
            continue

        # Store the match card in DB. NO AI analysis here — that's now an
        # explicit, per-match action the user triggers from the card.
        await db.upsert_match(
            match_id=guid,
            session_id=session_id,
            folder_path=summary["folder_path"],
            summary=summary,
            has_analysis=False,
        )
        processed_summaries.append(summary)
        await progress.msg(f"Added: {summary.get('map_display', short)} {summary.get('result', '')}")

    await progress.update(current=total)
    await progress.done(processed_summaries)
    log.info("Fetch job %s complete — %d replays added (analysis on demand)", job_id, len(processed_summaries))


# ── single-match analysis (on-demand) ─────────────────────────────────────────

async def run_analysis_job(
    job_id: str,
    session: dict,
    match: dict,
    db,
    api_key: str,
) -> None:
    """
    Run Claude analysis for ONE already-parsed match, on demand.
    Respects the daily AI cap. Writes dashboard.html + marks the match analysed.
    """
    progress = _Progress(job_id, db)
    await progress.update(status="running", step="Starting analysis…",
                          type="analysis", match_id=match["match_id"])

    session_id = session["session_id"]
    eos_account_id = session.get("eos_account_id", "")
    today_str = date.today().isoformat()

    if not api_key:
        await progress.error("AI analysis is not configured on this server")
        return

    # Daily cap
    usage = await db.get_usage(eos_account_id, today_str)
    if usage >= DAILY_LIMIT:
        await progress.error(f"Daily AI limit reached ({usage}/{DAILY_LIMIT}). Try again tomorrow.")
        return

    folder_path = Path(match["folder_path"])
    match_json_path = folder_path / "match.json"
    frames_path = folder_path / "frames.parquet"
    if not match_json_path.exists():
        await progress.error("Match data missing — re-fetch this replay and try again")
        return

    await progress.update(step="Computing advanced metrics…")
    await progress.msg("Running Claude Sonnet 4.6 analysis…")

    loop = asyncio.get_event_loop()
    try:
        html = await loop.run_in_executor(
            None, _run_claude_analysis_sync, match_json_path, frames_path, api_key
        )
    except Exception as e:
        await progress.error(f"Analysis failed: {e}")
        return

    if not html:
        await progress.error("Analysis failed — the AI response could not be parsed. Please retry.")
        return

    (folder_path / "dashboard.html").write_text(html, encoding="utf-8")
    await db.mark_analysis_done(match["match_id"])
    await db.increment_usage(eos_account_id, today_str)

    state = {"status": "complete", "step": "Analysis ready!", "type": "analysis",
             "analysis_ready": True, "match_id": match["match_id"],
             "total": 0, "current": 0, "messages": []}
    await db.update_job(job_id, state)
    log.info("Analysis job %s complete for match %s", job_id, match["match_id"])
