"""
Smart replay selector for initial coaching analysis.

Fetches the match history and finds the most recent:
  - 1 FULL WIN  in the user's chosen playlist / team size
  - 1 FULL LOSS in the user's chosen playlist / team size

"Full" = duration_s > 180 AND team fully populated (N players per side).
Forfeits and short games are skipped.
"""
from __future__ import annotations
import asyncio
import logging
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

log = logging.getLogger(__name__)

# Minimum game duration to count as a "full game"
MIN_DURATION_S = 180

# Playlist strings that the carball/rrrocket parser may report
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


def _playlist_matches(parsed_playlist: str, target: str) -> bool:
    """Check if the replay's playlist string matches the target gamemode label."""
    raw = (parsed_playlist or "").lower()
    aliases = _PLAYLIST_ALIASES.get(target.lower(), [target.lower()])
    return any(a in raw for a in aliases)


def _is_full_game(parsed, target_team_size: int) -> bool:
    if parsed.duration_s < MIN_DURATION_S:
        return False
    per_team = len([p for p in parsed.players if not p.is_orange])
    if per_team < target_team_size:
        return False
    return True


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


def _process_one(tmp_path: Path, guid: str, player_id: str, output_dir: Path, ledger) -> Optional[dict]:
    """Lightweight parse of a single replay. Returns summary dict or None."""
    from rlcoach.parser import parse_replay
    from rlcoach.metrics import compute_metrics, _is_me
    from rlcoach.ledger import file_hash
    from rlcoach.digest import _clean_map_name
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
    result_str = f"W{my_score}-{opp_score}" if is_win else (
        f"D{my_score}-{opp_score}" if my_score == opp_score else f"L{my_score}-{opp_score}"
    )

    return {
        "parsed": parsed,
        "metrics": metrics,
        "my_team": my_team,
        "is_win": is_win,
        "is_draw": my_score == opp_score,
        "map_display": map_clean.replace("_", " ").strip(),
        "result_str": result_str,
        "duration_s": parsed.duration_s,
        "match_id": match_id,
    }


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
    """
    Scan the recent match history and return (win_replay, loss_replay).
    Either can be None if not found in the last 20 matches.
    """
    from rlapi.client import create_client
    import json

    if progress_cb:
        await progress_cb("Connecting to PsyNet for replay selection…")

    try:
        client = await create_client(access_token, account_id, display_name)
        matches = await client.get_match_history(timeout=20.0)
        await client.close()
    except Exception as e:
        log.error("Failed to fetch match history for selection: %s", e)
        return None, None

    win: Optional[SelectedReplay] = None
    loss: Optional[SelectedReplay] = None
    loop = asyncio.get_event_loop()
    debug_dir = output_dir / "failed_replays"
    debug_dir.mkdir(exist_ok=True)

    for entry in matches:
        if win and loss:
            break

        md = entry.get("Match", {})
        guid = md.get("MatchGUID", "")
        url = entry.get("ReplayUrl", "")
        if not guid or not url:
            continue
        if ledger.is_processed_guid(guid):
            continue

        short = guid[:8]
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
            info = await loop.run_in_executor(
                None, _process_one, tmp, guid, player_id, output_dir, ledger
            )
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

        parsed = info["parsed"]

        # Check playlist match
        if not _playlist_matches(parsed.playlist, gamemode):
            log.debug("Skipping %s — playlist %s != %s", short, parsed.playlist, gamemode)
            continue

        # Check full game
        if not _is_full_game(parsed, team_size):
            log.debug("Skipping %s — short game %.0fs or incomplete", short, parsed.duration_s)
            continue

        # Skip draws for coaching purposes
        if info["is_draw"]:
            log.debug("Skipping %s — draw", short)
            continue

        # Run full pipeline and save the replay
        from rlcoach.web_pipeline import _process_replay_sync as _full_process
        from rlcoach.events import extract_moments
        from rlcoach.renderer import render_moment
        from rlcoach.digest import write_match_json, write_match_md
        import re as _re

        date_str = (parsed.date or "00000000").replace("-", "").replace("T", "")[:8]
        map_safe = _re.sub(r"(_GRS)?_[Pp]$", "", parsed.map_name or "Unknown").replace(" ", "-")[:24]
        mode = f"{parsed.team_size or 2}v{parsed.team_size or 2}"
        folder_name = f"{date_str}_{map_safe}_{mode}_{info['result_str']}"
        out_dir = output_dir / folder_name
        moments_dir = out_dir / "moments"
        out_dir.mkdir(parents=True, exist_ok=True)
        moments_dir.mkdir(parents=True, exist_ok=True)

        # Save parquet
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

        # Moments + diagrams
        from rlcoach.config import ThresholdConfig
        import types
        cfg_thresh = types.SimpleNamespace(slow_recovery_s=3.0)
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
            log.warning("Moments failed for %s: %s", short, e)
            moments = []

        write_match_json(parsed, info["metrics"], moments, out_dir)
        write_match_md(parsed, info["metrics"], moments, out_dir)
        ledger.mark_processed_guid(guid, str(out_dir))

        # Load the written match.json
        match_json_path = out_dir / "match.json"
        match_json = json.loads(match_json_path.read_text()) if match_json_path.exists() else {}

        sel = SelectedReplay(
            guid=guid,
            folder_path=out_dir,
            is_win=info["is_win"],
            map_display=info["map_display"],
            result_str=info["result_str"],
            duration_s=info["duration_s"],
            match_json=match_json,
        )

        if info["is_win"] and win is None:
            win = sel
            if progress_cb:
                await progress_cb(f"Found WIN replay: {info['map_display']} {info['result_str']}")
        elif not info["is_win"] and loss is None:
            loss = sel
            if progress_cb:
                await progress_cb(f"Found LOSS replay: {info['map_display']} {info['result_str']}")

    return win, loss
