"""
Rotation analysis — event-based rotation-opportunity grading.

The aggregate signals (ballchase %, double-commit windows, coverage %) tell you
*that* rotation is loose; this tells you *which rotations* were good or bad and
why. It anchors on the coaching maxim "rotate out after your touch": every time
the tracked player gives up the ball is a rotation opportunity, graded on what
they did in the ~2.5s after.

Each opportunity is classified:
  Excellent  — rotated goal-side toward the BACK post, kept a support gap, ideally grabbed a pad
  Acceptable — rotated out and held coverage, with minor inefficiencies
  Poor       — ball-side rotation / through the middle / collapsed onto the teammate / didn't rotate out
  Critical   — caused a double-commit pushing forward, or the team conceded in the window

This is where support distance + positioning come together: direction (back vs
ball-side), goal-side depth, support gap, pad collection and team structure are
all read from the frame data around the touch.

RL coords: X ±4096 (width), Y ±5120 (length). Blue defends -Y, Orange +Y.
"""
from __future__ import annotations

import logging
from dataclasses import asdict, dataclass, field
from typing import Optional

import numpy as np

from .metrics import _col, _game_times, _gameplay_mask, _is_me
from .phrasing import field_fraction
from .positioning import SUPPORT_MIN, SUPPORT_MAX

log = logging.getLogger(__name__)

FIELD_Y = 5120.0

ROT_WINDOW_S = 2.5       # how long after a touch we judge the rotation
GROUP_GAP_S = 1.5        # collapse consecutive own touches (a dribble) into one opportunity
GOALWARD_MARGIN = 250.0  # uu closer to own goal to count as actually rotating back
MIDDLE_X = 900.0         # |x| within this for the whole window = through the middle
SIDE_X = 500.0           # |x| beyond this to have a definite post side
COLLAPSE_DIST = 1500.0   # support gap below this = overlap / smothering the teammate
PAD_GAIN = 8.0           # boost rise in the window = grabbed a pad on the way
CONCEDE_S = 6.0          # enemy goal within this of the touch = critical

_GRADE_SCORE = {"excellent": 100.0, "acceptable": 65.0, "poor": 25.0, "critical": 0.0}


@dataclass
class RotationEvent:
    t: float
    grade: str                       # excellent | acceptable | poor | critical
    reasons: list = field(default_factory=list)
    goalward: bool = False
    back_post: bool = False
    ball_side: bool = False
    through_middle: bool = False
    got_pad: bool = False
    support_after: float = 0.0
    caused_double_commit: bool = False
    conceded: bool = False
    actual: list = field(default_factory=list)   # [x,y] end position (for diagrams)
    ball: list = field(default_factory=list)      # [x,y] at the touch


@dataclass
class RotationAnalysis:
    opportunities: int = 0
    excellent: int = 0
    acceptable: int = 0
    poor: int = 0
    critical: int = 0
    score: float = 0.0               # 0-100, weighted by grade
    events: list = field(default_factory=list)   # list[RotationEvent], worst first
    notes: list = field(default_factory=list)


# ── helpers ────────────────────────────────────────────────────────────────────

def _norm_boost(b):
    finite = b[~np.isnan(b)] if b is not None else None
    if finite is not None and finite.size and finite.max() > 100:
        return b / 255.0 * 100.0
    return b


def _group_touches(times_of_touches: list) -> list:
    """Collapse consecutive own touches within GROUP_GAP_S; return the last of each group."""
    if not times_of_touches:
        return []
    ts = sorted(times_of_touches)
    anchors, last = [], ts[0]
    for t in ts[1:]:
        if t - last > GROUP_GAP_S:
            anchors.append(last)
        last = t
    anchors.append(last)
    return anchors


# ── core ────────────────────────────────────────────────────────────────────────

def compute_rotation(parsed, my_player_id: str) -> RotationAnalysis:
    out = RotationAnalysis()
    df = parsed.frame_df
    if df is None or len(df) == 0:
        out.notes.append("No frame data — rotation analysis unavailable")
        return out

    me = next((p for p in parsed.players if _is_me(p.platform_id, my_player_id)), None)
    if me is None:
        out.notes.append("Tracked player not found")
        return out

    team_names = [p.name for p in parsed.players if p.team == me.team]
    if len(team_names) < 2:
        out.notes.append("1v1 — no rotation partner; rotation grading skipped")
        return out

    my_touches = [h.time_s for h in parsed.hits if h.player_name == me.name]
    if not my_touches:
        out.notes.append("No touches for the tracked player — rotation analysis skipped")
        return out

    dur = parsed.duration_s
    if not dur or dur <= 0:
        t_all = _game_times(df)
        dur = float(t_all[-1]) if len(t_all) else 0.0

    times = _game_times(df)
    is_orange = me.is_orange
    own_goal_y = FIELD_Y if is_orange else -FIELD_Y

    bx = _col(df, "ball", "pos_x"); by = _col(df, "ball", "pos_y")
    bvy = _col(df, "ball", "vel_y")
    mx = _col(df, me.name, "pos_x"); my = _col(df, me.name, "pos_y")
    mb = _col(df, me.name, "boost")
    mb = _norm_boost(mb) if mb is not None else None
    if bx is None or by is None or mx is None or my is None:
        out.notes.append("Missing position columns — rotation analysis unavailable")
        return out

    teammates = [n for n in team_names if n != me.name]
    tm_pos = {n: (_col(df, n, "pos_x"), _col(df, n, "pos_y")) for n in teammates}

    enemy = "orange" if me.team == "blue" else "blue"
    enemy_goal_times = sorted(g.time_s for g in parsed.goals if g.scoring_team == enemy)

    def idx_at(t):
        return int(np.clip(np.searchsorted(times, t), 0, len(times) - 1))

    n = len(times)
    events: list[RotationEvent] = []

    for t in _group_touches(my_touches):
        i0 = idx_at(t)
        i1 = idx_at(t + ROT_WINDOW_S)
        if i1 <= i0:
            continue

        x0, y0 = float(mx[i0]), float(my[i0])
        x1, y1 = float(mx[i1]), float(my[i1])
        bx_t = float(bx[i0]) if not np.isnan(bx[i0]) else 0.0
        by_end = float(by[i1]) if not np.isnan(by[i1]) else 0.0
        if np.isnan(x0) or np.isnan(x1):
            continue

        # direction / depth
        goalward = (abs(own_goal_y - y1) < abs(own_goal_y - y0) - GOALWARD_MARGIN)
        goal_side_of_ball = (y1 > by_end) if is_orange else (y1 < by_end)
        ball_sign = np.sign(bx_t) if abs(bx_t) > SIDE_X else 0
        my_sign = np.sign(x1) if abs(x1) > SIDE_X else 0
        back_post = bool(ball_sign != 0 and my_sign != 0 and my_sign != ball_sign)
        ball_side = bool(ball_sign != 0 and my_sign == ball_sign and not goalward)
        through_middle = bool(np.all(np.abs(mx[i0:i1]) < MIDDLE_X))

        # support gap to nearest teammate at end of window
        support_after = 9999.0
        for nm, (tx, ty) in tm_pos.items():
            if tx is None:
                continue
            d = float(np.hypot(x1 - tx[i1], y1 - ty[i1]))
            if not np.isnan(d):
                support_after = min(support_after, d)
        collapsed = support_after < COLLAPSE_DIST
        too_far = support_after > SUPPORT_MAX + 900 and support_after < 9999

        # pad collected? (boost rises during the window)
        got_pad = False
        if mb is not None:
            seg = mb[i0:i1 + 1]
            seg = seg[~np.isnan(seg)]
            if seg.size and float(seg.max()) > float(mb[i0]) + PAD_GAIN:
                got_pad = True

        # team structure: a SUSTAINED double-commit forming in the window — both my-team
        # players forward AND the ball coming back toward our net — but only chargeable to
        # THIS rotation if the player themselves failed to rotate out (not goalward).
        caused_dc = False
        if not goalward:
            try:
                forward = np.ones(i1 - i0, dtype=bool)
                for nm in team_names:
                    py = _col(df, nm, "pos_y")
                    if py is None:
                        forward = None
                        break
                    seg = py[i0:i1]
                    forward &= (seg < 0) if is_orange else (seg > 0)   # in offensive half
                if forward is not None and bvy is not None:
                    back = (bvy[i0:i1] > 0) if is_orange else (bvy[i0:i1] < 0)  # ball toward own goal
                    cond = forward & back
                    fps = max(1.0, (i1 - i0) / ROT_WINDOW_S)
                    need = max(3, int(0.7 * fps))   # require ~0.7s sustained, not a 1-frame blip
                    run = mxrun = 0
                    for v in cond:
                        run = run + 1 if v else 0
                        mxrun = max(mxrun, run)
                    caused_dc = mxrun >= need
            except Exception:
                pass

        # concede charged to the rotation only if the player was out of position (not goalward)
        conceded = (not goalward) and any(t <= gt <= t + CONCEDE_S for gt in enemy_goal_times)

        # ── grade ──
        reasons = []
        if not goalward:
            reasons.append("didn't rotate out — stayed forward")
        if ball_side:
            reasons.append("ball-side rotation (took the near post)")
        if through_middle:
            reasons.append("rotated through the middle")
        if collapsed:
            reasons.append(f"collapsed onto your teammate ({field_fraction(support_after)} apart — overlap)")
        if too_far:
            reasons.append(f"drifted too far to support ({field_fraction(support_after)} apart)")

        pos_good = goalward and goal_side_of_ball and back_post and not through_middle \
            and SUPPORT_MIN - 300 <= support_after <= SUPPORT_MAX + 300

        if conceded or caused_dc:
            grade = "critical"
            if conceded:
                reasons.insert(0, "team conceded within the rotation window")
            if caused_dc:
                reasons.insert(0, "pushed up into a double-commit")
        elif (not goalward) or ball_side or through_middle or collapsed:
            grade = "poor"
        elif pos_good:
            grade = "excellent"
            if got_pad:
                reasons.append("clean back-post rotation with a pad grabbed")
            else:
                reasons.append("clean back-post rotation, goal-side")
        else:
            grade = "acceptable"
            if not got_pad:
                reasons.append("rotated out but skipped the pad")
            if not back_post and goalward:
                reasons.append("covered centrally rather than back post")

        events.append(RotationEvent(
            t=round(float(t), 2), grade=grade, reasons=reasons,
            goalward=goalward, back_post=back_post, ball_side=ball_side,
            through_middle=through_middle, got_pad=got_pad,
            support_after=round(support_after, 0) if support_after < 9999 else 0.0,
            caused_double_commit=caused_dc, conceded=conceded,
            actual=[round(x1, 0), round(y1, 0)], ball=[round(bx_t, 0), round(by_end, 0)],
        ))

    if not events:
        out.notes.append("No rotation opportunities detected")
        return out

    out.opportunities = len(events)
    out.excellent = sum(1 for e in events if e.grade == "excellent")
    out.acceptable = sum(1 for e in events if e.grade == "acceptable")
    out.poor = sum(1 for e in events if e.grade == "poor")
    out.critical = sum(1 for e in events if e.grade == "critical")
    out.score = round(sum(_GRADE_SCORE[e.grade] for e in events) / len(events), 1)

    # surface worst first (critical, then poor), keep a couple of good ones for contrast
    order = {"critical": 0, "poor": 1, "acceptable": 2, "excellent": 3}
    events.sort(key=lambda e: (order[e.grade], e.t))
    out.events = events[:8]
    return out


def rotation_to_dict(r: RotationAnalysis) -> dict:
    return {
        "opportunities": r.opportunities,
        "excellent": r.excellent,
        "acceptable": r.acceptable,
        "poor": r.poor,
        "critical": r.critical,
        "score": r.score,
        "events": [asdict(e) for e in r.events],
        "notes": r.notes,
    }
