"""
Smart replay selector for the coaching plan.

Scans the recent match history and finds the most recent:
  - 1 FULL WIN  in the user's chosen RANKED playlist
  - 1 FULL LOSS in the user's chosen RANKED playlist

Selection rules (strict, for coaching quality):
  * COMPETITIVE only — uses the PsyNet `Match.Playlist` id to require the exact
    ranked playlist (10=1v1, 11=2v2, 13=3v3). This also excludes casual and the
    extra modes (Hoops 27 / Rumble 28 / Dropshot 29 / Snowday 30).
  * FULL game only — duration > 180s and both teams fully populated (no forfeits).
  * Draws are skipped.
Already-processed replays are REUSED from disk (so generating a plan still works
after the user has already pulled their replays into Match History).
"""
from __future__ import annotations
import asyncio
import json
import logging
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

log = logging.getLogger(__name__)

MIN_DURATION_S = 180

# Chosen gamemode -> required RANKED PsyNet playlist id
RANKED_PLAYLIST = {"1v1": 10, "2v2": 11, "3v3": 13}

# Parser playlist-string aliases (fallback only — when the PsyNet id is absent)
_PLAYLIST_ALIASES = {
    "1v1": ["ranked duel", "duel", "1v1"],
    "2v2": ["ranked doubles", "doubles", "2v2"],
    "3v3": ["ranked standard", "standard", "3v3"],
}


@dataclass
class SelectedReplay:
    guid: str
    folder_path: Path
    is_win: bool
    map_display: str
    result_str: str
    duration_s: float
    match_json: dict


def _entry_playlist_id(entry: dict, md: dict) -> Optional[int]:
    """Pull the PsyNet playlist id from a match-history entry, if present."""
    for src in (md, entry):
        for key in ("Playlist", "PlaylistID", "PlaylistId"):
            v = src.get(key)
            if v is not None:
                try:
                    return int(v)
                except (TypeError, ValueError):
                    pass
    return None


def _playlist_matches(parsed_playlist: str, target: str) -> bool:
    raw = (parsed_playlist or "").lower()
    return any(a in raw for a in _PLAYLIST_ALIASES.get(target.lower(), [target.lower()]))


def _is_full_game(parsed, target_team_size: int) -> bool:
    if parsed.duration_s < MIN_DURATION_S:
        return False
    per_team = len([p for p in parsed.players if not p.is_orange])
    return per_team >= target_team_size


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


def _selected_from_match_json(guid: str, folder: str, mj: dict, team_size: int) -> Optional[SelectedReplay]:
    """Build a SelectedReplay from an already-written match.json (reuse path)."""
    dur = mj.get("duration_s", 0) or 0
    if dur < MIN_DURATION_S:
        return None
    players = mj.get("players", [])
    blue = [p for p in players if p.get("team") == "blue"]
    orange = [p for p in players if p.get("team") == "orange"]
    if min(len(blue), len(orange)) < team_size:
        return None
    res = mj.get("result", {})
    bs, os_ = res.get("blue_score", 0), res.get("orange_score", 0)
    if bs == os_:
        return None  # draw
    win = bool(res.get("win", False))
    pt = res.get("player_team", "blue")
    my, opp = (os_, bs) if pt == "orange" else (bs, os_)
    rs = f"W{my}-{opp}" if win else f"L{my}-{opp}"
    return SelectedReplay(
        guid=guid, folder_path=Path(folder), is_win=win,
        map_display=mj.get("map_display") or mj.get("map") or "Unknown",
        result_str=rs, duration_s=dur, match_json=mj,
    )


def _process_one(tmp_path: Path, guid: str, player_id: str) -> Optional[dict]:
    from rlcoach.parser import parse_replay
    from rlcoach.metrics import compute_metrics
    from rlcoach.ledger import file_hash
    import re as _re

    match_id = file_hash(tmp_path)
    try:
        parsed = parse_replay(tmp_path, match_id)
    except Exception as e:
        log.debug("Parse failed for %s: %s", guid[:8], e)
        return None
    metrics = compute_metrics(parsed, player_id)
    me_pm = next((pm for pm in metrics.players if pm.is_me), None)
    my_team = me_pm.team if me_pm else "blue"
    if my_team == "orange":
        my_score, opp_score = parsed.orange_score, parsed.blue_score
    else:
        my_score, opp_score = parsed.blue_score, parsed.orange_score
    is_win = my_score > opp_score
    map_clean = _re.sub(r"(_GRS)?_[Pp]$", "", parsed.map_name or "Unknown")
    result_str = (f"W{my_score}-{opp_score}" if is_win else
                  (f"D{my_score}-{opp_score}" if my_score == opp_score else f"L{my_score}-{opp_score}"))
    return {
        "parsed": parsed, "metrics": metrics, "my_team": my_team, "is_win": is_win,
        "is_draw": my_score == opp_score,
        "map_display": map_clean.replace("_", " ").strip(),
        "result_str": result_str, "duration_s": parsed.duration_s, "match_id": match_id,
    }


def _save_and_build(info: dict, guid: str, output_dir: Path, ledger) -> Optional[SelectedReplay]:
    """Run the full pipeline for a freshly-parsed replay and return a SelectedReplay."""
    from rlcoach.events import extract_moments
    from rlcoach.renderer import render_moment
    from rlcoach.digest import write_match_json, write_match_md
    import re as _re

    parsed = info["parsed"]
    date_str = (parsed.date or "00000000").replace("-", "").replace("T", "")[:8]
    map_safe = _re.sub(r"(_GRS)?_[Pp]$", "", parsed.map_name or "Unknown").replace(" ", "-")[:24]
    mode = f"{parsed.team_size or 2}v{parsed.team_size or 2}"
    out_dir = output_dir / f"{date_str}_{map_safe}_{mode}_{info['result_str']}"
    moments_dir = out_dir / "moments"
    out_dir.mkdir(parents=True, exist_ok=True)
    moments_dir.mkdir(parents=True, exist_ok=True)

    if parsed.frame_df is not None and len(parsed.frame_df) > 0:
        try:
            import pandas as pd
            df_save = parsed.frame_df.copy()
            for col in df_save.columns:
                if df_save[col].dtype == object:
                    df_save[col] = pd.to_numeric(df_save[col], errors="coerce").astype("float32")
            df_save.to_parquet(str(out_dir / "frames.parquet"))
        except Exception as e:
            log.warning("Parquet save failed: %s", e)

    try:
        moments = extract_moments(parsed, info["metrics"], 3.0)
        for m in moments:
            ts_str = f"{int(m.t):04d}"
            out_png = moments_dir / f"{ts_str}_{m.type}.png"
            if m.snapshot:
                ok = render_moment(m.snapshot, out_png, m.type.replace("_", " ").title(), m.extra_snapshots or None)
                if ok:
                    m.diagram = f"moments/{ts_str}_{m.type}.png"
    except Exception as e:
        log.warning("Moments failed for %s: %s", guid[:8], e)
        moments = []

    write_match_json(parsed, info["metrics"], moments, out_dir)
    write_match_md(parsed, info["metrics"], moments, out_dir)
    ledger.mark_processed_guid(guid, str(out_dir))

    mj_path = out_dir / "match.json"
    mj = json.loads(mj_path.read_text(encoding="utf-8")) if mj_path.exists() else {}
    return SelectedReplay(
        guid=guid, folder_path=out_dir, is_win=info["is_win"],
        map_display=info["map_display"], result_str=info["result_str"],
        duration_s=info["duration_s"], match_json=mj,
    )


async def find_win_and_loss(
    access_token: str,
    account_id: str,
    display_name: str,
    player_id: str,
    gamemode: str,
    team_size: int,
    output_dir: Path,
    ledger,
    progress_cb=None,
) -> tuple[Optional[SelectedReplay], Optional[SelectedReplay]]:
    from rlapi.client import create_client

    if progress_cb:
        await progress_cb("Connecting to PsyNet for replay selection…")
    try:
        client = await create_client(access_token, account_id, display_name)
        matches = await client.get_match_history(timeout=20.0)
        await client.close()
    except Exception as e:
        log.error("Failed to fetch match history for selection: %s", e)
        return None, None

    required_pl = RANKED_PLAYLIST.get(gamemode)
    win: Optional[SelectedReplay] = None
    loss: Optional[SelectedReplay] = None
    loop = asyncio.get_event_loop()
    debug_dir = output_dir / "failed_replays"
    debug_dir.mkdir(exist_ok=True)

    def _assign(sel):
        nonlocal win, loss
        if sel is None:
            return None
        if sel.is_win and win is None:
            win = sel
            return f"Found WIN: {sel.map_display} {sel.result_str}"
        if (not sel.is_win) and loss is None:
            loss = sel
            return f"Found LOSS: {sel.map_display} {sel.result_str}"
        return None

    for entry in matches:
        if win and loss:
            break
        md = entry.get("Match", {})
        guid = md.get("MatchGUID", "")
        if not guid:
            continue
        short = guid[:8]

        # 1) COMPETITIVE + exact standard mode (authoritative via PsyNet playlist id).
        #    Excludes casual and Hoops/Rumble/Dropshot/Snowday in one check.
        pl = _entry_playlist_id(entry, md)
        if required_pl is not None and pl is not None and pl != required_pl:
            log.debug("skip %s — playlist %s != ranked %s", short, pl, required_pl)
            continue

        # 2) Reuse an already-processed replay (so the plan works after a fetch)
        folder = ledger.guid_output_folder(guid)
        if folder and (Path(folder) / "match.json").exists():
            try:
                mj = json.loads((Path(folder) / "match.json").read_text(encoding="utf-8"))
            except Exception:
                mj = None
            if mj is not None:
                # If we couldn't pre-filter by id, verify the mode by string now
                if pl is None and not _playlist_matches(mj.get("playlist") or mj.get("mode"), gamemode):
                    continue
                msg = _assign(_selected_from_match_json(guid, folder, mj, team_size))
                if msg and progress_cb:
                    await progress_cb(msg)
                continue

        # 3) New replay — download + parse + save
        url = entry.get("ReplayUrl", "")
        if not url:
            continue
        if progress_cb:
            await progress_cb(f"Checking replay {short}…")
        try:
            tmp = await _download_replay(url)
        except Exception as e:
            log.debug("Download failed %s: %s", short, e)
            continue
        debug_copy = debug_dir / f"{short}.replay"
        shutil.copy2(str(tmp), str(debug_copy))
        try:
            info = await loop.run_in_executor(None, _process_one, tmp, guid, player_id)
        except Exception as e:
            log.debug("Process failed %s: %s", short, e)
            info = None
        finally:
            try:
                tmp.unlink(missing_ok=True)
                debug_copy.unlink(missing_ok=True)
            except Exception:
                pass
        if info is None:
            continue

        # Fallback mode check when the playlist id was unavailable
        if pl is None and not _playlist_matches(info["parsed"].playlist, gamemode):
            log.debug("skip %s — parsed playlist %s != %s", short, info["parsed"].playlist, gamemode)
            continue
        if not _is_full_game(info["parsed"], team_size):
            log.debug("skip %s — short/incomplete (%.0fs)", short, info["duration_s"])
            continue
        if info["is_draw"]:
            continue

        msg = _assign(_save_and_build(info, guid, output_dir, ledger))
        if msg and progress_cb:
            await progress_cb(msg)

    return win, loss
