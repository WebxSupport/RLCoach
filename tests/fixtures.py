"""
Synthetic ParsedReplay fixtures for verifying the analysis pipeline without a
real .replay file.

The generated frame_df matches the production schema:
  - MultiIndex columns (entity, field)
  - entities: each player name + "ball" + "game"
  - player/ball fields: pos_x, pos_y, pos_z, vel_x, vel_y, vel_z, rot_z, boost
  - ball extra: hit_team_no
  - game: seconds_remaining, time

Field convention (RL world units):
  X: +/-4096 (width)   Y: +/-5120 (length)   Z: 0..2044 (height)
  Blue defends Y = -5120, Orange defends Y = +5120.

The default scenario is a 2v2 where the tracked player ("Me", blue) chronically
over-commits: they spend a large share of play in the offensive half even when
the ball is travelling back toward their own net, and they support far too tight
to their teammate. That gives the positioning metrics something real to flag.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from rlcoach.parser import GoalEvent, ParsedReplay, PlayerMeta

TRACKED_ID = "steam:76561198335346016"

FIELD_X = 4096.0
FIELD_Y = 5120.0


def _yaw_from_vel(vx: np.ndarray, vy: np.ndarray, default: float = 0.0) -> np.ndarray:
    yaw = np.arctan2(vy, vx)
    moving = (vx ** 2 + vy ** 2) > 1.0
    return np.where(moving, yaw, default)


def make_synthetic_parsed(
    *,
    n_frames: int = 9000,
    duration_s: float = 300.0,
    seed: int = 7,
) -> ParsedReplay:
    """Build a deterministic synthetic 2v2 ParsedReplay with full frame data."""
    rng = np.random.default_rng(seed)
    fps = n_frames / duration_s

    # ── Canonical clock ──────────────────────────────────────────────────────
    t = np.linspace(0.0, duration_s, n_frames)
    seconds_remaining = np.maximum(0.0, duration_s - t)

    # ── Ball: a slow oscillation down the field plus jitter ──────────────────
    # by sweeps from blue half to orange half repeatedly; bx wanders.
    by = 3600.0 * np.sin(2 * np.pi * t / 47.0) + rng.normal(0, 250, n_frames)
    bx = 2600.0 * np.sin(2 * np.pi * t / 31.0 + 1.1) + rng.normal(0, 200, n_frames)
    bz = np.clip(300.0 + 250.0 * np.sin(2 * np.pi * t / 13.0), 93.0, 1900.0)
    by = np.clip(by, -FIELD_Y + 100, FIELD_Y - 100)
    bx = np.clip(bx, -FIELD_X + 100, FIELD_X - 100)
    bvy = np.gradient(by, t)
    bvx = np.gradient(bx, t)
    bvz = np.gradient(bz, t)

    # Possession proxy: whichever team's ball half + noise. 0 = blue, 1 = orange.
    hit_team = np.where(by < 0, 0, 1).astype(float)
    flip = rng.random(n_frames) < 0.15
    hit_team = np.where(flip, 1 - hit_team, hit_team)

    players: list[PlayerMeta] = []
    frame_cols: dict[tuple, np.ndarray] = {}

    def add_player(name, pid, is_orange, px, py, pz, boost, core):
        team = "orange" if is_orange else "blue"
        players.append(PlayerMeta(
            name=name, platform_id=pid, team=team, is_orange=is_orange, **core,
        ))
        vx = np.gradient(px, t)
        vy = np.gradient(py, t)
        vz = np.gradient(pz, t)
        frame_cols[(name, "pos_x")] = px
        frame_cols[(name, "pos_y")] = py
        frame_cols[(name, "pos_z")] = pz
        frame_cols[(name, "vel_x")] = vx
        frame_cols[(name, "vel_y")] = vy
        frame_cols[(name, "vel_z")] = vz
        frame_cols[(name, "rot_z")] = _yaw_from_vel(vx, vy)
        frame_cols[(name, "boost")] = boost

    # ── Me (blue, tracked): over-commits — hugs the ball, stays ball-side ─────
    # Position chases the ball with a forward (toward orange net) bias, so when
    # the ball comes back to blue's half "Me" is still upfield.
    me_x = np.clip(bx * 0.85 + rng.normal(0, 300, n_frames), -FIELD_X, FIELD_X)
    me_y = np.clip(by * 0.80 + 900.0 + rng.normal(0, 350, n_frames), -FIELD_Y, FIELD_Y)
    me_z = np.full(n_frames, 17.0)
    me_boost = np.clip(45 + 30 * np.sin(2 * np.pi * t / 19.0) + rng.normal(0, 12, n_frames), 0, 100)
    add_player("Me", TRACKED_ID, False, me_x, me_y, me_z, me_boost,
               dict(goals=1, shots=4, assists=0, saves=1, score=320))

    # ── Teammate (blue): disciplined — sits back-post-ish, lags the ball ──────
    tm_x = np.clip(bx * 0.45 + rng.normal(0, 250, n_frames), -FIELD_X, FIELD_X)
    tm_y = np.clip(by * 0.55 - 1700.0 + rng.normal(0, 300, n_frames), -FIELD_Y, FIELD_Y)
    tm_z = np.full(n_frames, 17.0)
    tm_boost = np.clip(55 + 25 * np.sin(2 * np.pi * t / 23.0 + 2) + rng.normal(0, 10, n_frames), 0, 100)
    add_player("Teammate", "steam:11111111111111111", False, tm_x, tm_y, tm_z, tm_boost,
               dict(goals=2, shots=5, assists=1, saves=3, score=410))

    # ── Opponents (orange): mirror-ish, one forward one back ─────────────────
    o1_x = np.clip(-bx * 0.6 + rng.normal(0, 300, n_frames), -FIELD_X, FIELD_X)
    o1_y = np.clip(by * 0.7 + 1200.0 + rng.normal(0, 300, n_frames), -FIELD_Y, FIELD_Y)
    o1_z = np.full(n_frames, 17.0)
    o1_boost = np.clip(50 + 28 * np.sin(2 * np.pi * t / 21.0 + 1) + rng.normal(0, 11, n_frames), 0, 100)
    add_player("Opp1", "steam:22222222222222222", True, o1_x, o1_y, o1_z, o1_boost,
               dict(goals=2, shots=6, assists=1, saves=2, score=395))

    o2_x = np.clip(-bx * 0.4 + rng.normal(0, 250, n_frames), -FIELD_X, FIELD_X)
    o2_y = np.clip(by * 0.5 + 2400.0 + rng.normal(0, 300, n_frames), -FIELD_Y, FIELD_Y)
    o2_z = np.full(n_frames, 17.0)
    o2_boost = np.clip(48 + 26 * np.sin(2 * np.pi * t / 25.0 + 3) + rng.normal(0, 10, n_frames), 0, 100)
    add_player("Opp2", "steam:33333333333333333", True, o2_x, o2_y, o2_z, o2_boost,
               dict(goals=1, shots=3, assists=2, saves=1, score=300))

    # ── Ball columns ─────────────────────────────────────────────────────────
    frame_cols[("ball", "pos_x")] = bx
    frame_cols[("ball", "pos_y")] = by
    frame_cols[("ball", "pos_z")] = bz
    frame_cols[("ball", "vel_x")] = bvx
    frame_cols[("ball", "vel_y")] = bvy
    frame_cols[("ball", "vel_z")] = bvz
    frame_cols[("ball", "hit_team_no")] = hit_team

    # ── Game columns ─────────────────────────────────────────────────────────
    frame_cols[("game", "seconds_remaining")] = seconds_remaining
    frame_cols[("game", "time")] = t

    cols = pd.MultiIndex.from_tuples(list(frame_cols.keys()))
    df = pd.DataFrame({k: v for k, v in frame_cols.items()})
    df.columns = cols
    df.index = pd.Index(t, name="time")

    # ── Goals (blue 3, orange 4 → a loss) ────────────────────────────────────
    goals = [
        GoalEvent(frame=int(40 * fps), time_s=40.0, scorer_name="Teammate", scoring_team="blue"),
        GoalEvent(frame=int(75 * fps), time_s=75.0, scorer_name="Opp1", scoring_team="orange"),
        GoalEvent(frame=int(120 * fps), time_s=120.0, scorer_name="Me", scoring_team="blue"),
        GoalEvent(frame=int(150 * fps), time_s=150.0, scorer_name="Opp2", scoring_team="orange"),
        GoalEvent(frame=int(200 * fps), time_s=200.0, scorer_name="Opp1", scoring_team="orange"),
        GoalEvent(frame=int(240 * fps), time_s=240.0, scorer_name="Teammate", scoring_team="blue"),
        GoalEvent(frame=int(285 * fps), time_s=285.0, scorer_name="Opp1", scoring_team="orange"),
    ]

    return ParsedReplay(
        match_id="SYNTHETIC-0001",
        map_name="DFH Stadium",
        date="2026-06-06",
        playlist="2v2",
        duration_s=duration_s,
        fps=fps,
        team_size=2,
        blue_score=3,
        orange_score=4,
        players=players,
        goals=goals,
        hits=[],          # intentionally empty — mirrors the rrrocket path
        demos=[],
        frame_df=df,
        warnings=[],
    )


if __name__ == "__main__":
    p = make_synthetic_parsed()
    print(f"frames={len(p.frame_df)} cols={p.frame_df.shape[1]} "
          f"players={[pl.name for pl in p.players]} goals={len(p.goals)}")
    print("sample columns:", list(p.frame_df.columns[:6]))
