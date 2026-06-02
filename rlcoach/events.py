"""
FR4 — Extract key moments worth rendering as top-down diagrams.
Each Moment carries a snapshot dict (positions/velocities at that instant)
which the renderer consumes directly.
"""
from dataclasses import dataclass, field
from typing import Optional

import numpy as np

from .parser import ParsedReplay
from .metrics import MatchMetrics, _game_times

PRE_GOAL_WINDOW_S = 5.0  # diagram anchor = T-5s before goal conceded


@dataclass
class Moment:
    t: float          # anchor timestamp (seconds)
    type: str         # "goal_conceded" | "double_commit" | "slow_recovery" | "kickoff"
    note: str
    diagram: str = ""                           # relative path; filled in by renderer
    snapshot: Optional[dict] = None            # positions at anchor time
    extra_snapshots: list = field(default_factory=list)  # [(t, snap), ...] for sequence renders


# ── Snapshot builder ──────────────────────────────────────────────────────────

def _snap_at(parsed: ParsedReplay, t: float) -> dict:
    df = parsed.frame_df
    if df is None or len(df) == 0:
        return {}

    times = _game_times(df)
    idx = int(np.clip(np.searchsorted(times, t), 0, len(times) - 1))

    snap: dict = {}
    for p in parsed.players:
        snap[p.name] = {
            "x":  _v(df, p.name, "pos_x", idx),
            "y":  _v(df, p.name, "pos_y", idx),
            "z":  _v(df, p.name, "pos_z", idx),
            "vx": _v(df, p.name, "vel_x", idx),
            "vy": _v(df, p.name, "vel_y", idx),
            "yaw": _v(df, p.name, "rot_z", idx),
            "team": p.team,
            "is_orange": p.is_orange,
        }
    snap["ball"] = {
        "x":  _v(df, "ball", "pos_x", idx),
        "y":  _v(df, "ball", "pos_y", idx),
        "z":  _v(df, "ball", "pos_z", idx),
        "vx": _v(df, "ball", "vel_x", idx),
        "vy": _v(df, "ball", "vel_y", idx),
    }
    return snap


def _v(df, entity: str, attr: str, idx: int) -> float:
    try:
        val = float(df[(entity, attr)].iloc[idx])
        return 0.0 if np.isnan(val) else val
    except Exception:
        return 0.0


def _multi_snap(parsed: ParsedReplay, base_t: float,
                offsets=(0.0, 1.5, 3.0)) -> list:
    """Return [(t, snapshot), ...] at base_t + each offset."""
    dur = parsed.duration_s
    return [
        (round(base_t + o, 2), _snap_at(parsed, base_t + o))
        for o in offsets
        if 0.0 <= base_t + o <= dur
    ]


# ── Public API ────────────────────────────────────────────────────────────────

def extract_moments(parsed: ParsedReplay, metrics: MatchMetrics,
                    slow_recovery_s: float = 3.0) -> list:
    """Return a list of Moment objects sorted by time."""

    me_pm = next((pm for pm in metrics.players if pm.is_me), None)
    my_team = me_pm.team if me_pm else "blue"
    enemy_team = "orange" if my_team == "blue" else "blue"

    moments: list[Moment] = []

    # 1. Goals conceded (T-5s window)
    for g in parsed.goals:
        if g.scoring_team != enemy_team:
            continue
        anchor = max(0.0, g.time_s - PRE_GOAL_WINDOW_S)
        extras = _multi_snap(parsed, anchor, offsets=(0.0, 2.5, PRE_GOAL_WINDOW_S))
        moments.append(Moment(
            t=round(anchor, 2),
            type="goal_conceded",
            note=f"Goal conceded at {g.time_s:.1f}s by {g.scorer_name}. Diagram shows T-5s run-up.",
            snapshot=_snap_at(parsed, anchor),
            extra_snapshots=extras,
        ))

    # 2. Double-commit events
    for dc in metrics.double_commit_events:
        extras = _multi_snap(parsed, dc.t)
        moments.append(Moment(
            t=dc.t,
            type="double_commit",
            note=(f"Double-commit: both {my_team} players in offensive half "
                  f"for {dc.duration_s:.1f}s with ball moving toward own goal."),
            snapshot=_snap_at(parsed, dc.t),
            extra_snapshots=extras,
        ))

    # 3. Slow recoveries (only for "me")
    if me_pm and me_pm.recovery:
        for ev in me_pm.recovery.recovery_events:
            if ev["duration_s"] >= slow_recovery_s:
                extras = _multi_snap(parsed, ev["t"])
                moments.append(Moment(
                    t=ev["t"],
                    type="slow_recovery",
                    note=(f"Slow recovery after challenge: "
                          f"{ev['duration_s']:.1f}s to return to defensive half."),
                    snapshot=_snap_at(parsed, ev["t"]),
                    extra_snapshots=extras,
                ))

    # 4. Kickoffs
    for ko in metrics.kickoff_outcomes:
        extras = _multi_snap(parsed, ko.t, offsets=(0.0, 1.0, 2.0))
        note = f"Kickoff at {ko.t:.1f}s — result: {ko.result}"
        if ko.conceded_within_s is not None:
            note += f" (conceded within {ko.conceded_within_s:.1f}s)"
        moments.append(Moment(
            t=ko.t,
            type="kickoff",
            note=note,
            snapshot=_snap_at(parsed, ko.t),
            extra_snapshots=extras,
        ))

    moments.sort(key=lambda m: m.t)
    return moments
