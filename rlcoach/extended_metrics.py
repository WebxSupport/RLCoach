"""
Additional frame-level metrics for the Claude coaching analysis.

Computes the metrics the master prompt asks for that are not already in match.json:
  - Possession % per team (from ball.hit_team_no)
  - Net coverage % per team (fraction of live play with at least 1 defender goal-side)
  - Ballchase Index per player (2v2 optimised, undefined for other modes)
  - Per-player: goal-side %, avg boost, starvation %, touch proxy, avg dist to ball
  - Goal autopsy windows: team shape + nearest defender info for each goal
"""
from __future__ import annotations
import logging
from typing import Optional

import numpy as np
import pandas as pd

from .metrics import _col, _game_times, _gameplay_mask

log = logging.getLogger(__name__)

FIELD_Y_HALF = 5120.0
BALL_TOUCH_RADIUS = 180.0      # uu — proximity counts as a touch candidate
RADIAL_CHASE_THRESH = 300.0    # uu/s radial velocity toward ball = chasing
GOAL_AUTOPSY_WINDOW_S = 6.0    # seconds before goal to analyse

# Fixed 10-bucket timeline matching the HTML template (labels 0-270)
_BC_LABELS = [0, 30, 60, 90, 120, 150, 180, 210, 240, 270]


def _normalise_boost(b: np.ndarray) -> np.ndarray:
    if b.max() > 100:
        return b / 255.0 * 100.0
    return b


# Possession -------------------------------------------------------------------

def _compute_possession(df: pd.DataFrame, gm: np.ndarray) -> dict:
    raw = _col(df, "ball", "hit_team_no")
    if raw is None:
        return {"blue": 50.0, "orange": 50.0}
    ht = raw[gm]
    valid = ~np.isnan(ht)
    ht_v = ht[valid]
    if len(ht_v) == 0:
        return {"blue": 50.0, "orange": 50.0}
    blue = round(float(100 * (ht_v == 0).mean()), 1)
    return {"blue": blue, "orange": round(100.0 - blue, 1)}


# Net coverage -----------------------------------------------------------------

def _compute_net_coverage(
    df: pd.DataFrame, gm: np.ndarray, teams: dict
) -> dict:
    """teams: {name: {"team": "blue"|"orange", "is_orange": bool}}"""
    by = _col(df, "ball", "pos_y")
    if by is None:
        return {"blue": 0.0, "orange": 0.0}
    by_gm = by[gm]
    n = int(gm.sum())
    result = {}
    for colour in ("blue", "orange"):
        is_orange = colour == "orange"
        players = [nm for nm, info in teams.items() if info["is_orange"] == is_orange]
        if not players:
            result[colour] = 0.0
            continue
        goalside_any = np.zeros(n, dtype=bool)
        for name in players:
            py = _col(df, name, "pos_y")
            if py is None:
                continue
            py_gm = py[gm]
            goalside_any |= (py_gm > by_gm) if is_orange else (py_gm < by_gm)
        result[colour] = round(float(100 * goalside_any.mean()), 1)
    return result


# Per-player stats -------------------------------------------------------------

def _compute_player_stats(
    df: pd.DataFrame, gm: np.ndarray, name: str, is_orange: bool, duration_s: float
) -> dict:
    bx = _col(df, "ball", "pos_x")
    by = _col(df, "ball", "pos_y")
    bz = _col(df, "ball", "pos_z")
    px = _col(df, name, "pos_x")
    py = _col(df, name, "pos_y")
    pz = _col(df, name, "pos_z")
    boost = _col(df, name, "boost")
    out: dict = {}

    if py is not None and by is not None:
        py_g = py[gm]; by_g = by[gm]
        gs = (py_g > by_g) if is_orange else (py_g < by_g)
        out["goalside_pct"] = round(float(100 * gs.mean()), 1)

    if px is not None and py is not None and bx is not None and by is not None:
        px_g = px[gm]; py_g = py[gm]
        bx_g = bx[gm]; by_g = by[gm]
        pz_g = pz[gm] if pz is not None else np.zeros_like(px_g)
        bz_g = bz[gm] if bz is not None else np.zeros_like(bx_g)
        dist = np.sqrt((px_g - bx_g)**2 + (py_g - by_g)**2 + (pz_g - bz_g)**2)
        out["avg_dist_to_ball"] = round(float(np.nanmean(dist)), 0)
        close = dist < BALL_TOUCH_RADIUS
        out["touch_proxy"] = int(np.sum(np.diff(close.astype(int)) == 1))

    if boost is not None:
        b = _normalise_boost(boost[gm])
        valid = ~np.isnan(b)
        if valid.any():
            b_v = b[valid]
            fps = len(b_v) / duration_s if duration_s > 0 else 30.0
            out["avg_boost"] = round(float(b_v.mean()), 1)
            out["starve_pct"] = round(float(100 * (b_v < 5).mean()), 1)
            out["time_at_zero_s"] = round(float((b_v < 5).sum() / fps), 1)

    return out


# Ballchase index (2v2 only) ---------------------------------------------------

def _compute_ballchase(
    df: pd.DataFrame,
    gm: np.ndarray,
    times: np.ndarray,
    my_team_players: list,
    is_orange_team: bool,
) -> dict:
    """
    Vectorised ballchase index. All arrays fetched via _g are already masked
    to gameplay frames — do NOT apply gm again.
    Returns {player_name: {index, longest_s, per_30s}, "_labels": [...]}
    or {} when conditions are not met.
    """
    if len(my_team_players) != 2:
        return {}

    p1, p2 = my_team_players[0], my_team_players[1]
    n = int(gm.sum())

    def _g(name: str, attr: str) -> Optional[np.ndarray]:
        arr = _col(df, name, attr)
        return arr[gm] if arr is not None else None

    bx = _g("ball", "pos_x")
    by = _g("ball", "pos_y")
    bz_raw = _g("ball", "pos_z")
    bz = bz_raw if bz_raw is not None else np.zeros(n)

    p1x = _g(p1, "pos_x");  p1y = _g(p1, "pos_y")
    p1z_raw = _g(p1, "pos_z");  p1z = p1z_raw if p1z_raw is not None else np.zeros(n)

    p2x = _g(p2, "pos_x");  p2y = _g(p2, "pos_y")
    p2z_raw = _g(p2, "pos_z");  p2z = p2z_raw if p2z_raw is not None else np.zeros(n)

    p1vx = _g(p1, "vel_x");  p1vy = _g(p1, "vel_y")
    p2vx = _g(p2, "vel_x");  p2vy = _g(p2, "vel_y")

    if any(v is None for v in [bx, by, p1x, p1y, p2x, p2y, p1vx, p1vy, p2vx, p2vy]):
        return {}

    d1 = np.sqrt((p1x - bx)**2 + (p1y - by)**2 + (p1z - bz)**2)
    d2 = np.sqrt((p2x - bx)**2 + (p2y - by)**2 + (p2z - bz)**2)
    p1_is_cover = d1 > d2

    rv1 = (p1vx * (bx - p1x) + p1vy * (by - p1y)) / np.maximum(d1, 1.0)
    rv2 = (p2vx * (bx - p2x) + p2vy * (by - p2y)) / np.maximum(d2, 1.0)

    if is_orange_team:
        p1_gs = p1y > by;  p2_gs = p2y > by;  ball_own_half = by > 0
    else:
        p1_gs = p1y < by;  p2_gs = p2y < by;  ball_own_half = by < 0

    p1_chase = p1_is_cover & (rv1 > RADIAL_CHASE_THRESH) & ~p1_gs & ~ball_own_half
    p2_chase = (~p1_is_cover) & (rv2 > RADIAL_CHASE_THRESH) & ~p2_gs & ~ball_own_half

    t_end = float(times[-1]) if len(times) else 300.0
    fps_approx = len(times) / max(t_end, 1.0)

    def _stats(is_cover: np.ndarray, chase: np.ndarray) -> dict:
        live = int(is_cover.sum())
        idx = round(100.0 * int(chase.sum()) / live, 1) if live else 0.0
        cur = longest = 0
        for c in chase:
            cur = (cur + 1) if c else 0
            if cur > longest:
                longest = cur
        longest_s = round(longest / fps_approx, 1) if fps_approx > 0 else 0.0
        per_30s = []
        for lb in _BC_LABELS:
            mask = (times >= lb) & (times < lb + 30)
            live_in = int(is_cover[mask].sum())
            chase_in = int(chase[mask].sum())
            per_30s.append(round(100.0 * chase_in / live_in, 1) if live_in else 0.0)
        return {"index": idx, "longest_s": longest_s, "per_30s": per_30s}

    return {
        p1: _stats(p1_is_cover, p1_chase),
        p2: _stats(~p1_is_cover, p2_chase),
        "_labels": _BC_LABELS,
    }


# Goal autopsy windows ---------------------------------------------------------

def _compute_goal_windows(
    df: pd.DataFrame,
    goals: list,
    times: np.ndarray,
    gm: np.ndarray,
    teams: dict,
    my_team: str,
) -> list:
    by_full = _col(df, "ball", "pos_y")
    bx_full = _col(df, "ball", "pos_x")
    times_full = _game_times(df)
    if by_full is None or len(times_full) != len(df):
        return []

    my_players = [nm for nm, info in teams.items() if info["team"] == my_team]
    my_is_orange = any(info["is_orange"] for nm, info in teams.items() if info["team"] == my_team)

    windows = []
    for goal in goals:
        goal_t = goal.time_s
        win_start = goal_t - GOAL_AUTOPSY_WINDOW_S
        win_mask = (times_full >= win_start) & (times_full <= goal_t)
        if not win_mask.any():
            windows.append({})
            continue

        total_frames = int(win_mask.sum())
        all_pos_y = []
        for nm in my_players:
            py = _col(df, nm, "pos_y")
            if py is not None:
                all_pos_y.append(py[win_mask])

        dc_frames = 0
        if all_pos_y and len(all_pos_y) == len(my_players):
            all_off = np.all(
                np.stack(all_pos_y) < 0 if my_is_orange else np.stack(all_pos_y) > 0,
                axis=0,
            )
            dc_frames = int(all_off.sum())

        goal_frame_idx = int(np.argmin(np.abs(times_full - goal_t)))
        by_goal = float(by_full[goal_frame_idx]) if not np.isnan(by_full[goal_frame_idx]) else 0.0
        bx_goal = float(bx_full[goal_frame_idx]) if bx_full is not None and not np.isnan(bx_full[goal_frame_idx]) else 0.0

        nearest_dist = None
        nearest_goalside = False
        for nm in my_players:
            px = _col(df, nm, "pos_x"); py = _col(df, nm, "pos_y")
            if px is None or py is None:
                continue
            d = float(np.sqrt((px[goal_frame_idx] - bx_goal)**2 + (py[goal_frame_idx] - by_goal)**2))
            if nearest_dist is None or d < nearest_dist:
                nearest_dist = d
                nearest_goalside = bool(py[goal_frame_idx] > by_goal) if my_is_orange else bool(py[goal_frame_idx] < by_goal)

        own_goal_y = FIELD_Y_HALF if my_is_orange else -FIELD_Y_HALF
        net_open = True
        for nm in my_players:
            py = _col(df, nm, "pos_y")
            if py is None:
                continue
            py_val = float(py[goal_frame_idx])
            is_gs = (py_val > by_goal) if my_is_orange else (py_val < by_goal)
            if abs(py_val - own_goal_y) < 3500 and is_gs:
                net_open = False
                break

        bvx = _col(df, "ball", "vel_x"); bvy = _col(df, "ball", "vel_y")
        ball_speed = 0.0
        if bvx is not None and bvy is not None:
            ball_speed = round(float(np.sqrt(bvx[goal_frame_idx]**2 + bvy[goal_frame_idx]**2)), 0)

        windows.append({
            "goal_t": round(goal_t, 1),
            "scoring_team": goal.scoring_team,
            "conceded": goal.scoring_team != my_team,
            "double_commit_pct": round(100 * dc_frames / total_frames, 1) if total_frames else 0.0,
            "nearest_defender_dist": round(nearest_dist, 0) if nearest_dist is not None else None,
            "nearest_defender_goalside": nearest_goalside,
            "net_open": net_open,
            "ball_speed_uu": ball_speed,
        })

    return windows


# Public API -------------------------------------------------------------------

def compute_extended_metrics(
    frame_df: "pd.DataFrame",
    parsed,
    my_player_id: str,
    duration_s: float,
) -> dict:
    """
    Compute additional frame-level metrics for the Claude coaching prompt.
    Returns a dict serialised to JSON and included in the Claude prompt.
    """
    from .metrics import _is_me

    if frame_df is None or len(frame_df) == 0:
        return {"error": "No frame data available"}

    teams: dict = {}
    for p in parsed.players:
        teams[p.name] = {
            "team": p.team,
            "is_orange": p.is_orange,
            "is_me": _is_me(p.platform_id, my_player_id),
        }

    me = next((p for p in parsed.players if _is_me(p.platform_id, my_player_id)), None)
    my_team = me.team if me else "blue"
    my_is_orange = me.is_orange if me else False
    my_team_players = [nm for nm, info in teams.items() if info["team"] == my_team]

    gm = _gameplay_mask(frame_df, duration_s)
    times_gm = _game_times(frame_df)[gm]
    result: dict = {}

    try:
        result["possession"] = _compute_possession(frame_df, gm)
    except Exception as e:
        log.debug("possession failed: %s", e)

    try:
        result["net_coverage"] = _compute_net_coverage(frame_df, gm, teams)
    except Exception as e:
        log.debug("net_coverage failed: %s", e)

    try:
        per_player = {}
        for p in parsed.players:
            per_player[p.name] = _compute_player_stats(frame_df, gm, p.name, p.is_orange, duration_s)
        result["per_player"] = per_player
    except Exception as e:
        log.debug("per_player failed: %s", e)

    try:
        bc = _compute_ballchase(frame_df, gm, times_gm, my_team_players, my_is_orange)
        if bc:
            labels = bc.pop("_labels", _BC_LABELS)
            result["ballchase"] = {"labels": labels, "players": bc}
    except Exception as e:
        log.debug("ballchase failed: %s", e)

    try:
        result["goal_windows"] = _compute_goal_windows(
            frame_df, parsed.goals, times_gm, gm, teams, my_team
        )
    except Exception as e:
        log.debug("goal_windows failed: %s", e)

    return result
