"""
Positional analysis — the frame-data half of the coaching framework.

Everything here is computed purely from the per-frame DataFrame (positions /
velocities), so it works on the rrrocket parse path that has no touch events.

Covers:
  - Defensive coverage zones      (near/back post, goal line, midfield, backboard)
  - Support distance distribution (too close / optimal / too far vs the 1800-2500uu band)
  - Distance to play              (avg distance to ball / nearest teammate / nearest opponent)
  - Last-man analysis             (time as last defender, depth, risky pushes)

Each section also surfaces a short list of worst-offender moments (timestamp +
the player's actual position + the ideal target) so the renderer can draw an
"actual vs ideal" diagram for distance mistakes.

RL coordinates:  X +/-4096 (width)   Y +/-5120 (length)
  Blue defends Y = -5120,  Orange defends Y = +5120.
"""
from __future__ import annotations

import logging
from dataclasses import asdict, dataclass, field
from typing import Optional

import numpy as np
import pandas as pd

from .metrics import _col, _game_times, _gameplay_mask, _is_me

log = logging.getLogger(__name__)

FIELD_X = 4096.0
FIELD_Y = 5120.0

# Support-distance band (uu) for the second man — from the coaching framework.
SUPPORT_MIN = 1800.0
SUPPORT_MAX = 2500.0
SUPPORT_IDEAL = (SUPPORT_MIN + SUPPORT_MAX) / 2.0

# Coverage-zone depth bands, measured as distance from own goal line (uu).
ZONE_DEEP = 1300.0     # <= this from own goal = goal-line / backboard region
ZONE_MID = 3400.0      # deep..mid = post coverage band; beyond = midfield
ZONE_WIDE_X = 1300.0   # |x| beyond this while deep = pinned on the backboard/corner
POST_CENTRAL_X = 450.0  # |x| below this is "central", not a distinct post side

# Possession proxy: a teammate "has" the ball when this close to it (uu).
CONTROL_RADIUS = 950.0

# Minimum spacing (s) between surfaced worst-moments so they don't cluster.
MOMENT_SPACING_S = 8.0
MAX_MOMENTS = 6


# ── Output structures ────────────────────────────────────────────────────────

@dataclass
class CoverageZones:
    near_post_pct: float = 0.0
    back_post_pct: float = 0.0
    goal_line_pct: float = 0.0
    midfield_pct: float = 0.0
    backboard_pct: float = 0.0
    own_half_pct: float = 0.0   # share of live play spent in own half (the denominator context)


@dataclass
class SupportMoment:
    t: float
    dist: float
    kind: str          # "too_close" | "too_far"
    actual: list       # [x, y] of the supporter
    teammate: list     # [x, y] of the possessor
    ball: list         # [x, y]
    ideal_lo: float = SUPPORT_MIN
    ideal_hi: float = SUPPORT_MAX


@dataclass
class SupportDistance:
    too_close_pct: float = 0.0
    optimal_pct: float = 0.0
    too_far_pct: float = 0.0
    avg_support_dist: float = 0.0
    support_frames: int = 0
    worst_moments: list = field(default_factory=list)  # list[SupportMoment]


@dataclass
class DistanceToPlay:
    avg_dist_ball: float = 0.0
    avg_dist_nearest_teammate: float = 0.0
    avg_dist_nearest_opponent: float = 0.0


@dataclass
class LastManMoment:
    t: float
    depth: float       # distance from own goal
    actual: list       # [x, y]
    ball: list         # [x, y]


@dataclass
class LastManMetrics:
    last_man_pct: float = 0.0
    avg_depth_when_last: float = 0.0
    risky_push_pct: float = 0.0     # share of last-man time spent out of own defensive half
    risky_moments: list = field(default_factory=list)  # list[LastManMoment]


@dataclass
class PlayerPositioning:
    name: str
    team: str
    is_me: bool
    coverage: CoverageZones = field(default_factory=CoverageZones)
    support: SupportDistance = field(default_factory=SupportDistance)
    distances: DistanceToPlay = field(default_factory=DistanceToPlay)
    last_man: LastManMetrics = field(default_factory=LastManMetrics)


# ── Geometry helpers ───────────────────────────────────────────────────────────

def _own_goal_y(is_orange: bool) -> float:
    return FIELD_Y if is_orange else -FIELD_Y


def _in_own_half(py: np.ndarray, is_orange: bool) -> np.ndarray:
    return (py > 0) if is_orange else (py < 0)


def _xy(df: pd.DataFrame, name: str, gm: np.ndarray):
    x = _col(df, name, "pos_x")
    y = _col(df, name, "pos_y")
    if x is None or y is None:
        return None, None
    return x[gm], y[gm]


# ── Coverage zones ─────────────────────────────────────────────────────────────

def _coverage_zones(px, py, bx, is_orange: bool) -> CoverageZones:
    """Partition the player's own-half frames into 5 coverage zones."""
    own_y = _own_goal_y(is_orange)
    in_half = _in_own_half(py, is_orange)
    n_live = len(py)
    if n_live == 0:
        return CoverageZones()

    own_half_pct = round(100.0 * in_half.mean(), 1)
    idx = np.where(in_half)[0]
    if len(idx) == 0:
        return CoverageZones(own_half_pct=own_half_pct)

    d_goal = np.abs(py[idx] - own_y)
    px_h = px[idx]
    bx_h = bx[idx]

    deep = d_goal <= ZONE_DEEP
    mid = (d_goal > ZONE_DEEP) & (d_goal <= ZONE_MID)
    high = d_goal > ZONE_MID

    wide = np.abs(px_h) > ZONE_WIDE_X
    # Post side: which side of the net the player sits on relative to the ball.
    same_side = (np.sign(px_h) == np.sign(bx_h)) & (np.abs(px_h) > POST_CENTRAL_X) & (np.abs(bx_h) > POST_CENTRAL_X)

    goal_line = deep & ~wide
    backboard = deep & wide
    near_post = mid & same_side
    back_post = mid & ~same_side
    midfield = high

    n = len(idx)
    return CoverageZones(
        near_post_pct=round(100.0 * near_post.sum() / n, 1),
        back_post_pct=round(100.0 * back_post.sum() / n, 1),
        goal_line_pct=round(100.0 * goal_line.sum() / n, 1),
        midfield_pct=round(100.0 * midfield.sum() / n, 1),
        backboard_pct=round(100.0 * backboard.sum() / n, 1),
        own_half_pct=own_half_pct,
    )


# ── Support distance ───────────────────────────────────────────────────────────

def _support_distance(
    df, gm, times, me_name, my_team_names, is_orange, bx, by,
) -> SupportDistance:
    """
    For each live frame where a teammate is controlling the ball in the
    attacking/neutral area and the tracked player is the supporter, measure the
    distance from the supporter to the possessor and bucket it against the
    1800-2500uu band.
    """
    others = [n for n in my_team_names if n != me_name]
    if not others:
        return SupportDistance()

    mx, my = _xy(df, me_name, gm)
    if mx is None:
        return SupportDistance()

    # Teammate positions + their distance to the ball.
    tm_pos = {}
    tm_dball = {}
    for n in others:
        tx, ty = _xy(df, n, gm)
        if tx is None:
            continue
        tm_pos[n] = (tx, ty)
        tm_dball[n] = np.sqrt((tx - bx) ** 2 + (ty - by) ** 2)
    if not tm_pos:
        return SupportDistance()

    # Possessor each frame = teammate (excluding me) nearest the ball, if in control.
    names = list(tm_pos.keys())
    dball_stack = np.vstack([tm_dball[n] for n in names])           # (k, N)
    poss_idx = np.argmin(dball_stack, axis=0)
    poss_dball = dball_stack[poss_idx, np.arange(dball_stack.shape[1])]

    my_dball = np.sqrt((mx - bx) ** 2 + (my - by) ** 2)

    # Gate: possessor in control, ball not deep in our own defensive third,
    # and the tracked player is NOT the one nearest the ball (i.e. is support).
    own_y = _own_goal_y(is_orange)
    ball_not_deep = np.abs(by - own_y) > (FIELD_Y - ZONE_MID)  # ball ahead of our deep third
    i_am_support = my_dball > poss_dball
    gate = (poss_dball < CONTROL_RADIUS) & ball_not_deep & i_am_support

    gi = np.where(gate)[0]
    if len(gi) == 0:
        return SupportDistance()

    poss_x = np.array([tm_pos[names[poss_idx[i]]][0][i] for i in gi])
    poss_y = np.array([tm_pos[names[poss_idx[i]]][1][i] for i in gi])
    sup_dist = np.sqrt((mx[gi] - poss_x) ** 2 + (my[gi] - poss_y) ** 2)

    n = len(sup_dist)
    too_close = sup_dist < SUPPORT_MIN
    too_far = sup_dist > SUPPORT_MAX
    optimal = ~too_close & ~too_far

    # Worst moments: largest deviation from the band, spaced out in time.
    deviation = np.where(too_close, SUPPORT_MIN - sup_dist,
                         np.where(too_far, sup_dist - SUPPORT_MAX, 0.0))
    order = np.argsort(-deviation)
    chosen, chosen_t = [], []
    tg = times[gi]
    for j in order:
        if deviation[j] <= 0:
            break
        tj = float(tg[j])
        if any(abs(tj - ct) < MOMENT_SPACING_S for ct in chosen_t):
            continue
        chosen_t.append(tj)
        chosen.append(SupportMoment(
            t=round(tj, 2),
            dist=round(float(sup_dist[j]), 0),
            kind="too_close" if too_close[j] else "too_far",
            actual=[round(float(mx[gi][j]), 0), round(float(my[gi][j]), 0)],
            teammate=[round(float(poss_x[j]), 0), round(float(poss_y[j]), 0)],
            ball=[round(float(bx[gi][j]), 0), round(float(by[gi][j]), 0)],
        ))
        if len(chosen) >= MAX_MOMENTS:
            break
    chosen.sort(key=lambda m: m.t)

    return SupportDistance(
        too_close_pct=round(100.0 * too_close.sum() / n, 1),
        optimal_pct=round(100.0 * optimal.sum() / n, 1),
        too_far_pct=round(100.0 * too_far.sum() / n, 1),
        avg_support_dist=round(float(sup_dist.mean()), 0),
        support_frames=int(n),
        worst_moments=chosen,
    )


# ── Distance to play ───────────────────────────────────────────────────────────

def _distance_to_play(df, gm, me_name, my_team_names, opp_names, bx, by) -> DistanceToPlay:
    mx, my = _xy(df, me_name, gm)
    if mx is None:
        return DistanceToPlay()
    out = DistanceToPlay()
    out.avg_dist_ball = round(float(np.nanmean(np.sqrt((mx - bx) ** 2 + (my - by) ** 2))), 0)

    def _nearest(names):
        stacks = []
        for n in names:
            tx, ty = _xy(df, n, gm)
            if tx is None:
                continue
            stacks.append(np.sqrt((mx - tx) ** 2 + (my - ty) ** 2))
        if not stacks:
            return 0.0
        return round(float(np.nanmean(np.min(np.vstack(stacks), axis=0))), 0)

    out.avg_dist_nearest_teammate = _nearest([n for n in my_team_names if n != me_name])
    out.avg_dist_nearest_opponent = _nearest(opp_names)
    return out


# ── Last man ───────────────────────────────────────────────────────────────────

def _last_man(df, gm, times, me_name, my_team_names, is_orange, bx, by) -> LastManMetrics:
    own_y = _own_goal_y(is_orange)
    depth = {}
    for n in my_team_names:
        _, ny = _xy(df, n, gm)
        if ny is None:
            return LastManMetrics()
        depth[n] = np.abs(ny - own_y)   # smaller = closer to own goal = deeper

    names = list(depth.keys())
    if me_name not in names:
        return LastManMetrics()
    depth_stack = np.vstack([depth[n] for n in names])
    # NaN-safe: a player with no position this frame (demoed / off-field) must
    # not be picked as the deepest defender. Treat NaN as +inf for the argmin,
    # and ignore frames where every teammate is missing.
    safe_stack = np.where(np.isnan(depth_stack), np.inf, depth_stack)
    last_idx = np.argmin(safe_stack, axis=0)
    all_missing = np.all(np.isnan(depth_stack), axis=0)
    me_pos = names.index(me_name)
    i_am_last = (last_idx == me_pos) & ~all_missing

    n_live = depth_stack.shape[1]
    if n_live == 0 or not i_am_last.any():
        return LastManMetrics()

    mx, my = _xy(df, me_name, gm)
    li = np.where(i_am_last)[0]
    my_depth = depth[me_name][li]
    in_own_half = _in_own_half(my[li], is_orange)
    risky = ~in_own_half   # last man but pushed out of own half → net exposed

    # Risky moments: deepest-pushed last-man frames, spaced out.
    ri = li[risky]
    moments, mt = [], []
    if len(ri):
        # rank by how far up the field (largest depth = furthest from own goal)
        for j in ri[np.argsort(-depth[me_name][ri])]:
            tj = float(times[j])
            if any(abs(tj - c) < MOMENT_SPACING_S for c in mt):
                continue
            mt.append(tj)
            moments.append(LastManMoment(
                t=round(tj, 2),
                depth=round(float(depth[me_name][j]), 0),
                actual=[round(float(mx[j]), 0), round(float(my[j]), 0)],
                ball=[round(float(bx[j]), 0), round(float(by[j]), 0)],
            ))
            if len(moments) >= MAX_MOMENTS:
                break
        moments.sort(key=lambda m: m.t)

    avg_depth = float(np.nanmean(my_depth)) if np.isfinite(my_depth).any() else 0.0
    return LastManMetrics(
        last_man_pct=round(100.0 * i_am_last.mean(), 1),
        avg_depth_when_last=round(avg_depth, 0),
        risky_push_pct=round(100.0 * risky.mean(), 1),
        risky_moments=moments,
    )


# ── Public API ─────────────────────────────────────────────────────────────────

def compute_positioning(parsed, my_player_id: str) -> list:
    """Return list[PlayerPositioning], one per player."""
    df = parsed.frame_df
    if df is None or len(df) == 0:
        return []

    dur = parsed.duration_s
    if not dur or dur <= 0:
        t = _game_times(df)
        dur = float(t[-1]) if len(t) else 0.0

    gm = _gameplay_mask(df, dur)
    times = _game_times(df)[gm]

    bx = _col(df, "ball", "pos_x")
    by = _col(df, "ball", "pos_y")
    bx = bx[gm] if bx is not None else np.zeros(int(gm.sum()))
    by = by[gm] if by is not None else np.zeros(int(gm.sum()))

    by_team = {"blue": [], "orange": []}
    for p in parsed.players:
        by_team[p.team].append(p.name)

    results = []
    for p in parsed.players:
        is_me = _is_me(p.platform_id, my_player_id)
        my_team_names = by_team[p.team]
        opp_names = by_team["orange" if p.team == "blue" else "blue"]

        px, py = _xy(df, p.name, gm)
        pp = PlayerPositioning(name=p.name, team=p.team, is_me=is_me)
        if px is None:
            results.append(pp)
            continue

        try:
            pp.coverage = _coverage_zones(px, py, bx, p.is_orange)
        except Exception as e:
            log.debug("coverage failed for %s: %s", p.name, e)
        try:
            pp.support = _support_distance(df, gm, times, p.name, my_team_names, p.is_orange, bx, by)
        except Exception as e:
            log.debug("support failed for %s: %s", p.name, e)
        try:
            pp.distances = _distance_to_play(df, gm, p.name, my_team_names, opp_names, bx, by)
        except Exception as e:
            log.debug("distance failed for %s: %s", p.name, e)
        try:
            pp.last_man = _last_man(df, gm, times, p.name, my_team_names, p.is_orange, bx, by)
        except Exception as e:
            log.debug("last_man failed for %s: %s", p.name, e)

        results.append(pp)

    return results


def positioning_to_dict(positioning: list) -> dict:
    """Serialise compute_positioning() output to a JSON-ready dict keyed by player."""
    out = {}
    for pp in positioning:
        out[pp.name] = {
            "team": pp.team,
            "is_me": pp.is_me,
            "coverage": asdict(pp.coverage),
            "support": asdict(pp.support),
            "distances": asdict(pp.distances),
            "last_man": asdict(pp.last_man),
        }
    return out
