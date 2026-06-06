"""
Shot-quality / Expected Goals (xG) model — the framework's Shooting section.

Each shot (a carball is_shot/is_goal touch) is scored on the features that
actually determine whether it goes in:

    distance   — ball → target-goal centre
    angle      — how head-on the shot is (central vs from the wing)
    speed      — ball speed off the touch (harder to react to)
    defence    — opponents goal-side in the shooting lane, and whether the net
                 is guarded

These feed a transparent logistic xG (0–1). It is a HEURISTIC, not a trained
model — its value is comparative: xG vs actual goals separates a finishing
problem (goals ≪ xG) from a chance-creation problem (few shots / low xG).

RL coords: X ±4096 (width), Y ±5120 (length). Blue attacks +Y, Orange attacks −Y.
"""
from __future__ import annotations

import logging
import math
from dataclasses import asdict, dataclass, field
from typing import Optional

import numpy as np

from .metrics import _col, _game_times, _is_me

log = logging.getLogger(__name__)

FIELD_Y = 5120.0
GOAL_HALF_WIDTH = 893.0
NET_GUARD_RADIUS = 1500.0   # opponent within this of own goal centre = guarding the net
LANE_HALF_WIDTH = 1100.0    # |x| within this of the shot lane counts a defender as in the way
SPEED_AFTER_FRAMES = 6
GOAL_MATCH_S = 4.0          # max shot→goal gap when attributing a goal to its shot

# Logistic xG weights (hand-tuned for plausibility; documented, not trained).
_W0 = -1.85
_W_DIST = 2.7
_W_ANGLE = 1.4
_W_SPEED = 0.8
_W_DEF = 1.5     # per goal-side defender in the lane
_W_NET = 0.7     # additional if the net is actively guarded
_DIST_SCALE = 5500.0   # uu at which distance factor → ~0


@dataclass
class Shot:
    t: float
    frame: int
    player: str
    team: str
    is_me: bool
    distance: float
    angle_deg: float          # 0 = dead centre / head-on
    speed: float
    defenders_in_lane: int
    net_guarded: bool
    xg: float
    goal: bool


@dataclass
class ShootingReport:
    shots: list = field(default_factory=list)        # list[Shot]
    per_player: dict = field(default_factory=dict)    # name -> {shots, goals, xg, conv_pct, xg_per_shot, finishing}
    team: dict = field(default_factory=dict)          # {'blue': {...}, 'orange': {...}}
    warnings: list = field(default_factory=list)


def _sigmoid(z: float) -> float:
    return 1.0 / (1.0 + math.exp(-z))


def _xg(distance: float, angle_factor: float, speed: float,
        defenders: int, net_guarded: bool) -> float:
    """Transparent logistic xG from shot features. Returns 0.01–0.95."""
    dist_factor = max(0.0, 1.0 - distance / _DIST_SCALE)
    speed_factor = min(1.0, speed / 2500.0)
    z = (_W0
         + _W_DIST * dist_factor
         + _W_ANGLE * angle_factor
         + _W_SPEED * speed_factor
         - _W_DEF * defenders
         - (_W_NET if net_guarded else 0.0))
    return round(min(0.95, max(0.01, _sigmoid(z))), 3)


def compute_shooting(parsed, my_player_id: str) -> ShootingReport:
    out = ShootingReport()
    df = parsed.frame_df

    # A "shot" = a touch flagged is_shot or is_goal by the parser.
    shot_hits = [h for h in parsed.hits if getattr(h, "is_shot", False) or getattr(h, "is_goal", False)]
    if not shot_hits:
        out.warnings.append("No shot events available — shooting analysis skipped")
        return out

    team_of = {p.name: p.team for p in parsed.players}
    orange_of = {p.name: p.is_orange for p in parsed.players}
    isme_of = {p.name: _is_me(p.platform_id, my_player_id) for p in parsed.players}
    goal_times_by_team = {"blue": [], "orange": []}
    for g in parsed.goals:
        goal_times_by_team.setdefault(g.scoring_team, []).append(g.time_s)

    has_frames = df is not None and len(df) > 0
    if has_frames:
        times = _game_times(df)
        bx = _col(df, "ball", "pos_x"); by = _col(df, "ball", "pos_y")
        bvx = _col(df, "ball", "vel_x"); bvy = _col(df, "ball", "vel_y")
        bvz = _col(df, "ball", "vel_z")

    for h in shot_hits:
        team = team_of.get(h.player_name, "blue")
        is_orange = orange_of.get(h.player_name, False)
        attack_y = -FIELD_Y if is_orange else FIELD_Y   # goal this team attacks

        if has_frames:
            fi = int(np.clip(np.searchsorted(times, h.time_s), 0, len(times) - 1))
            sx = float(bx[fi]) if bx is not None and not np.isnan(bx[fi]) else 0.0
            sy = float(by[fi]) if by is not None and not np.isnan(by[fi]) else 0.0
            # distance to the goal centre
            dy = abs(attack_y - sy)
            dist = math.hypot(sx, dy)
            # angle: head-on if the ball is directly in front of the goal mouth
            angle_factor = (dy / dist) if dist > 1 else 0.0           # 1 = head-on, 0 = from the byline
            angle_deg = round(math.degrees(math.acos(max(0.0, min(1.0, angle_factor)))), 1)
            # ball speed just after the touch
            hi = min(len(bvx), fi + SPEED_AFTER_FRAMES) if bvx is not None else fi
            if bvx is not None and bvy is not None and hi > fi:
                seg = np.sqrt(bvx[fi:hi] ** 2 + bvy[fi:hi] ** 2 + (bvz[fi:hi] ** 2 if bvz is not None else 0))
                seg = seg[~np.isnan(seg)]
                speed = float(seg.max()) if len(seg) else 0.0
            else:
                speed = 0.0
            defenders, net_guarded = _defence_at(df, fi, team_of, team, attack_y, sx, sy, is_orange)
        else:
            sx = sy = 0.0; dist = 3000.0; angle_factor = 0.6; angle_deg = 53.0
            speed = 0.0; defenders = 0; net_guarded = False

        xg = _xg(dist, angle_factor, speed, defenders, net_guarded)

        out.shots.append(Shot(
            t=round(h.time_s, 2), frame=int(getattr(h, "frame", 0)),
            player=h.player_name, team=team, is_me=isme_of.get(h.player_name, False),
            distance=round(dist, 0), angle_deg=angle_deg, speed=round(speed, 0),
            defenders_in_lane=defenders, net_guarded=net_guarded, xg=xg, goal=False,
        ))

    # Attribute each goal event to exactly ONE shot — the nearest same-team shot
    # just before it — so a single goal can't inflate multiple shots' tallies.
    for g in parsed.goals:
        cands = [s for s in out.shots
                 if s.team == g.scoring_team and not s.goal and -0.3 <= g.time_s - s.t <= GOAL_MATCH_S]
        if cands:
            best = min(cands, key=lambda s: abs(g.time_s - s.t))
            best.goal = True

    _aggregate(out, team_of, isme_of)
    return out


def _defence_at(df, fi, team_of, shooting_team, attack_y, sx, sy, is_orange):
    """Count opponents in the shooting lane between ball and goal, + net guard."""
    defenders = 0
    net_guarded = False
    for nm, tm in team_of.items():
        if tm == shooting_team:
            continue
        px = _col(df, nm, "pos_x"); py = _col(df, nm, "pos_y")
        if px is None or py is None:
            continue
        try:
            ox, oy = float(px[fi]), float(py[fi])
        except Exception:
            continue
        if np.isnan(ox) or np.isnan(oy):
            continue
        # goal-side of the ball (between ball and the goal it's being shot at)
        goal_side = (oy < sy) if is_orange else (oy > sy)
        in_lane = abs(ox - sx) < LANE_HALF_WIDTH or abs(ox) < LANE_HALF_WIDTH
        if goal_side and in_lane:
            defenders += 1
        if math.hypot(ox, attack_y - oy) < NET_GUARD_RADIUS:
            net_guarded = True
    return defenders, net_guarded


def _aggregate(out: ShootingReport, team_of, isme_of):
    per = {}
    for s in out.shots:
        d = per.setdefault(s.player, {"name": s.player, "team": s.team,
                                      "is_me": isme_of.get(s.player, False),
                                      "shots": 0, "goals": 0, "xg": 0.0})
        d["shots"] += 1
        d["goals"] += int(s.goal)
        d["xg"] += s.xg
    for d in per.values():
        d["xg"] = round(d["xg"], 2)
        d["xg_per_shot"] = round(d["xg"] / d["shots"], 3) if d["shots"] else 0.0
        d["conv_pct"] = round(100.0 * d["goals"] / d["shots"], 1) if d["shots"] else 0.0
        # finishing: goals above/below expectation
        diff = d["goals"] - d["xg"]
        d["finishing"] = ("clinical" if diff > 0.7 else
                          "cold" if diff < -0.7 else "as expected")
    out.per_player = per

    for colour in ("blue", "orange"):
        ss = [s for s in out.shots if s.team == colour]
        out.team[colour] = {
            "shots": len(ss),
            "goals": sum(1 for s in ss if s.goal),
            "xg": round(sum(s.xg for s in ss), 2),
        }


def shooting_to_dict(report: ShootingReport, include_shots: bool = True) -> dict:
    d = {
        "team": report.team,
        "per_player": report.per_player,
        "warnings": report.warnings,
    }
    if include_shots:
        d["shots"] = [asdict(s) for s in report.shots]
    return d
