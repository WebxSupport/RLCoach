"""
Layer 1 — touch-event analysis (the touch-centric half of the coaching framework).

Depends on real touch events (parser now recovers carball hitbox hits; a
synthesis fallback covers replays where carball still yields none). For each
touch it derives a TYPE and an OUTCOME from the surrounding frame data, then
rolls touches up into possession chains, challenges, and per-player summaries.

Touch types     : controlled · pass · shot · clear · challenge · panic · neutral
Touch outcomes  : positive · neutral · negative
Possession ends : goal · shot · clear · turnover · lost · stall

All heuristics are documented inline and tuned for 2v2/3v3 Soccar.

RL coords: X ±4096 (width), Y ±5120 (length). Blue defends -Y, Orange +Y.
"""
from __future__ import annotations

import logging
from dataclasses import asdict, dataclass, field
from typing import Optional

import numpy as np

from .metrics import _col, _game_times, _gameplay_mask, _is_me

log = logging.getLogger(__name__)

FIELD_Y = 5120.0
THIRD = FIELD_Y / 3.0  # ≈ 1706.7

# Heuristic thresholds -----------------------------------------------------------
CHALLENGE_WINDOW_S = 0.5    # an opposing touch this close = a contested 50/50
CONTROL_NEXT_S = 2.5        # next same-team touch within this = retained possession
PASS_DIST = 1200.0         # ball travelled ≥ this to a teammate = a pass (else dribble/control)
CLEAR_SPEED = 1400.0       # ball speed after a defensive-third touch = a clear
PANIC_PRESSURE = 750.0     # nearest opponent closer than this = under pressure
GIVEAWAY_SPACE = 1300.0    # nearest opponent farther than this = you had time (lost it = giveaway)
GOAL_ATTRIB_S = 6.0        # a goal within this of a touch is attributed to that possession
SPEED_AFTER_FRAMES = 6      # frames after a touch to measure resulting ball speed


# ── Output structures ────────────────────────────────────────────────────────

@dataclass
class Touch:
    t: float
    frame: int
    player: str
    team: str
    is_me: bool
    type: str
    outcome: str
    third: str            # 'def' | 'neut' | 'off' (touching team's perspective)
    pressure: float       # nearest-opponent distance at the touch (uu)
    ball_speed_after: float
    giveaway: bool = False


@dataclass
class Possession:
    team: str
    start_t: float
    end_t: float
    duration_s: float
    touch_count: int
    end_reason: str       # goal | shot | clear | turnover | lost | stall


@dataclass
class Challenge:
    t: float
    player: str
    team: str
    is_me: bool
    type: str             # immediate | delayed | shadow
    outcome: str          # win | neutral | loss


@dataclass
class PlayerTouchSummary:
    name: str
    team: str
    is_me: bool
    total: int = 0
    positive: int = 0
    neutral: int = 0
    negative: int = 0
    giveaways: int = 0
    type_counts: dict = field(default_factory=dict)
    avg_pressure: float = 0.0
    challenges: int = 0
    challenge_wins: int = 0
    first_touches: int = 0       # touches where you just received/won the ball
    first_touch_positive: int = 0
    first_touch_negative: int = 0


@dataclass
class TouchAnalysis:
    touches: list = field(default_factory=list)        # list[Touch]
    possessions: list = field(default_factory=list)    # list[Possession]
    challenges: list = field(default_factory=list)     # list[Challenge]
    per_player: dict = field(default_factory=dict)      # name -> PlayerTouchSummary
    team_possession: dict = field(default_factory=dict) # {'blue': %, 'orange': %} by touch count
    warnings: list = field(default_factory=list)


# ── Helpers ─────────────────────────────────────────────────────────────────

def _third_of(y: float, is_orange: bool) -> str:
    """Field third from the touching team's perspective."""
    if is_orange:
        if y > THIRD:
            return "def"
        if y < -THIRD:
            return "off"
    else:
        if y < -THIRD:
            return "def"
        if y > THIRD:
            return "off"
    return "neut"


def _frame_index(times: np.ndarray, t: float) -> int:
    return int(np.clip(np.searchsorted(times, t), 0, len(times) - 1))


# ── Core ────────────────────────────────────────────────────────────────────

def compute_touch_analysis(parsed, my_player_id: str) -> TouchAnalysis:
    df = parsed.frame_df
    out = TouchAnalysis()

    hits = sorted(parsed.hits, key=lambda h: h.time_s)
    if not hits:
        out.warnings.append("No touch events available — touch analysis skipped")
        return out

    team_of = {p.name: p.team for p in parsed.players}
    orange_of = {p.name: p.is_orange for p in parsed.players}
    isme_of = {p.name: _is_me(p.platform_id, my_player_id) for p in parsed.players}

    # annotate teams (some pipelines rely on this downstream)
    for h in hits:
        if getattr(h, "team", None) is None:
            h.team = team_of.get(h.player_name)

    has_frames = df is not None and len(df) > 0
    if has_frames:
        times = _game_times(df)
        bx = _col(df, "ball", "pos_x"); by = _col(df, "ball", "pos_y")
        bvx = _col(df, "ball", "vel_x"); bvy = _col(df, "ball", "vel_y")
        bvz = _col(df, "ball", "vel_z")
        opp_pos = {nm: (_col(df, nm, "pos_x"), _col(df, nm, "pos_y")) for nm in team_of}
    else:
        times = None

    def _ball_speed_after(fi: int) -> float:
        if not has_frames or bvx is None or bvy is None:
            return 0.0
        hi = min(len(bvx), fi + SPEED_AFTER_FRAMES)
        seg = np.sqrt(bvx[fi:hi] ** 2 + bvy[fi:hi] ** 2 + (bvz[fi:hi] ** 2 if bvz is not None else 0))
        seg = seg[~np.isnan(seg)]
        return float(seg.max()) if len(seg) else 0.0

    def _pressure(fi: int, touching_team: str) -> float:
        """Nearest opponent distance to the ball at the touch frame."""
        if not has_frames or bx is None:
            return 9999.0
        best = 9999.0
        for nm, (px, py) in opp_pos.items():
            if team_of.get(nm) == touching_team or px is None:
                continue
            d = float(np.sqrt((px[fi] - bx[fi]) ** 2 + (py[fi] - by[fi]) ** 2))
            if not np.isnan(d):
                best = min(best, d)
        return best

    # Build Touch objects -------------------------------------------------------
    touches: list[Touch] = []
    n = len(hits)
    for i, h in enumerate(hits):
        team = h.team
        is_orange = orange_of.get(h.player_name, False)
        fi = _frame_index(times, h.time_s) if has_frames else 0
        y = float(by[fi]) if has_frames and by is not None and not np.isnan(by[fi]) else 0.0
        third = _third_of(y, is_orange)
        spd_after = _ball_speed_after(fi)
        press = _pressure(fi, team)

        nxt = hits[i + 1] if i + 1 < n else None
        prv = hits[i - 1] if i > 0 else None
        next_same = nxt is not None and nxt.team == team
        next_opp = nxt is not None and nxt.team != team
        dt_next = (nxt.time_s - h.time_s) if nxt else 1e9

        # contested = an opposing touch within the challenge window either side
        contested = (
            (nxt is not None and nxt.team != team and (nxt.time_s - h.time_s) <= CHALLENGE_WINDOW_S)
            or (prv is not None and prv.team != team and (h.time_s - prv.time_s) <= CHALLENGE_WINDOW_S)
        )

        ttype, outcome, giveaway = "neutral", "neutral", False

        if getattr(h, "is_goal", False):
            ttype, outcome = "shot", "positive"
        elif getattr(h, "is_shot", False):
            goal_soon = any(g.scoring_team == team and 0 <= g.time_s - h.time_s <= GOAL_ATTRIB_S
                            for g in parsed.goals)
            ttype, outcome = "shot", ("positive" if goal_soon else "neutral")
        elif contested:
            ttype = "challenge"
            outcome = "positive" if next_same else ("negative" if next_opp else "neutral")
        elif third == "def" and spd_after >= CLEAR_SPEED:
            ttype = "clear"
            # cleared the danger; positive if we kept it, neutral if it went to them
            outcome = "neutral" if next_opp else "positive"
        elif next_same and dt_next <= CONTROL_NEXT_S:
            moved = _ball_travel(df, by, bx, fi, times, nxt.time_s) if has_frames else 0.0
            if nxt.player_name != h.player_name and moved >= PASS_DIST:
                ttype, outcome = "pass", "positive"
            else:
                ttype, outcome = "controlled", "positive"
        elif next_opp:
            # lost possession without clearing
            if press < PANIC_PRESSURE:
                ttype = "panic" if third == "def" else "challenge"
                outcome = "negative" if third == "def" else "neutral"
            elif press >= GIVEAWAY_SPACE:
                ttype, outcome, giveaway = "controlled", "negative", True   # had time, gave it away
            else:
                ttype, outcome = "challenge", "neutral"
        # else: terminal touch with no follow-up → neutral/neutral

        touches.append(Touch(
            t=round(h.time_s, 2), frame=int(getattr(h, "frame", fi)),
            player=h.player_name, team=team, is_me=isme_of.get(h.player_name, False),
            type=ttype, outcome=outcome, third=third,
            pressure=round(press, 0), ball_speed_after=round(spd_after, 0),
            giveaway=giveaway,
        ))

    out.touches = touches

    # Possession chains ---------------------------------------------------------
    out.possessions = _build_possessions(touches, parsed.goals)

    # Challenges ----------------------------------------------------------------
    out.challenges = _build_challenges(touches, df, times if has_frames else None,
                                       parsed, has_frames)

    # Per-player summary --------------------------------------------------------
    out.per_player = _summarise_players(touches, out.challenges, team_of, isme_of)

    # Team possession by touch count -------------------------------------------
    blue = sum(1 for t in touches if t.team == "blue")
    tot = len(touches)
    if tot:
        out.team_possession = {"blue": round(100.0 * blue / tot, 1),
                               "orange": round(100.0 * (tot - blue) / tot, 1)}

    return out


def _ball_travel(df, by, bx, fi: int, times: np.ndarray, t_next: float) -> float:
    """Straight-line distance the ball travels between this touch and the next."""
    if bx is None or by is None:
        return 0.0
    fj = _frame_index(times, t_next)
    try:
        return float(np.sqrt((bx[fj] - bx[fi]) ** 2 + (by[fj] - by[fi]) ** 2))
    except Exception:
        return 0.0


def _build_possessions(touches: list, goals: list) -> list:
    poss: list[Possession] = []
    if not touches:
        return poss
    cur = None
    for i, t in enumerate(touches):
        if cur is None or cur["team"] != t.team:
            if cur is not None:
                poss.append(_close_possession(cur, touches, i, goals))
            cur = {"team": t.team, "start_t": t.t, "end_t": t.t,
                   "touch_count": 1, "last_idx": i}
        else:
            cur["end_t"] = t.t
            cur["touch_count"] += 1
            cur["last_idx"] = i
    if cur is not None:
        poss.append(_close_possession(cur, touches, len(touches), goals))
    return poss


def _close_possession(cur: dict, touches: list, next_idx: int, goals: list) -> Possession:
    last = touches[cur["last_idx"]]
    team = cur["team"]
    nxt = touches[next_idx] if next_idx < len(touches) else None
    goal_soon = any(g.scoring_team == team and 0 <= g.time_s - last.t <= GOAL_ATTRIB_S for g in goals)
    if goal_soon or last.type == "shot" and any(
            g.scoring_team == team and 0 <= g.time_s - last.t <= GOAL_ATTRIB_S for g in goals):
        reason = "goal"
    elif last.type == "shot":
        reason = "shot"
    elif last.type == "clear":
        reason = "clear"
    elif nxt is not None and nxt.team != team:
        reason = "turnover" if last.outcome == "negative" else "lost"
    else:
        reason = "stall"
    return Possession(
        team=team, start_t=cur["start_t"], end_t=cur["end_t"],
        duration_s=round(cur["end_t"] - cur["start_t"], 2),
        touch_count=cur["touch_count"], end_reason=reason,
    )


def _build_challenges(touches, df, times, parsed, has_frames) -> list:
    """A challenge = a touch typed 'challenge'. Classify approach + outcome."""
    challenges = []
    orange_of = {p.name: p.is_orange for p in parsed.players}
    for t in touches:
        if t.type != "challenge":
            continue
        ctype = "immediate"
        if has_frames and times is not None:
            fi = _frame_index(times, t.t)
            vx = _col(df, t.player, "vel_x"); vy = _col(df, t.player, "vel_y")
            bx = _col(df, "ball", "pos_x"); by = _col(df, "ball", "pos_y")
            if vx is not None and bx is not None:
                px = _col(df, t.player, "pos_x"); py = _col(df, t.player, "pos_y")
                d = float(np.sqrt((px[fi] - bx[fi]) ** 2 + (py[fi] - by[fi]) ** 2)) or 1.0
                rv = (vx[fi] * (bx[fi] - px[fi]) + vy[fi] * (by[fi] - py[fi])) / d
                spd = float(np.sqrt(vx[fi] ** 2 + vy[fi] ** 2))
                if spd < 500:
                    ctype = "shadow"
                elif rv < 300:
                    ctype = "delayed"
                else:
                    ctype = "immediate"
        outcome = "win" if t.outcome == "positive" else ("loss" if t.outcome == "negative" else "neutral")
        challenges.append(Challenge(
            t=t.t, player=t.player, team=t.team, is_me=t.is_me,
            type=ctype, outcome=outcome,
        ))
    return challenges


def _summarise_players(touches, challenges, team_of, isme_of) -> dict:
    summ: dict = {}
    for nm, team in team_of.items():
        summ[nm] = PlayerTouchSummary(name=nm, team=team, is_me=isme_of.get(nm, False))
    press_acc: dict = {}
    prev_team = None
    for t in touches:
        s = summ.get(t.player)
        if s is None:
            prev_team = t.team
            continue
        s.total += 1
        setattr(s, t.outcome, getattr(s, t.outcome) + 1)
        s.type_counts[t.type] = s.type_counts.get(t.type, 0) + 1
        if t.giveaway:
            s.giveaways += 1
        # first touch = you just received/won the ball (previous touch was the other team)
        if prev_team is None or prev_team != t.team:
            s.first_touches += 1
            if t.outcome == "positive":
                s.first_touch_positive += 1
            elif t.outcome == "negative":
                s.first_touch_negative += 1
        press_acc.setdefault(t.player, []).append(t.pressure)
        prev_team = t.team
    for c in challenges:
        s = summ.get(c.player)
        if s is None:
            continue
        s.challenges += 1
        if c.outcome == "win":
            s.challenge_wins += 1
    for nm, s in summ.items():
        vals = [p for p in press_acc.get(nm, []) if p < 9999]
        s.avg_pressure = round(float(np.mean(vals)), 0) if vals else 0.0
    return summ


# ── Serialisation ─────────────────────────────────────────────────────────────

def touch_analysis_to_dict(ta: TouchAnalysis, include_touches: bool = False) -> dict:
    d = {
        "team_possession": ta.team_possession,
        "possessions": {
            "count": len(ta.possessions),
            "by_end_reason": _count_by(ta.possessions, "end_reason"),
            "avg_duration_s": round(float(np.mean([p.duration_s for p in ta.possessions])), 2) if ta.possessions else 0.0,
            "avg_touches": round(float(np.mean([p.touch_count for p in ta.possessions])), 2) if ta.possessions else 0.0,
        },
        "challenges": {
            "count": len(ta.challenges),
            "by_type": _count_by(ta.challenges, "type"),
            "by_outcome": _count_by(ta.challenges, "outcome"),
        },
        "per_player": {nm: asdict(s) for nm, s in ta.per_player.items()},
        "warnings": ta.warnings,
    }
    if include_touches:
        d["touches"] = [asdict(t) for t in ta.touches]
    return d


def _count_by(items: list, attr: str) -> dict:
    out: dict = {}
    for it in items:
        k = getattr(it, attr)
        out[k] = out.get(k, 0) + 1
    return out
