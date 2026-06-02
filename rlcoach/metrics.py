"""
FR3 — Coaching metrics computed from ParsedReplay frame data.

RL coordinate conventions:
  X: ±4096 (width),  Y: ±5120 (length)
  Blue defends Y ≈ -5120   →  blue defensive third: Y < -1707
  Orange defends Y ≈ +5120 →  orange defensive third: Y > +1707
  Midfield: Y = 0
"""
import logging
from dataclasses import dataclass, field
from typing import Optional

import numpy as np
import pandas as pd

from .parser import ParsedReplay

log = logging.getLogger(__name__)

FIELD_Y_HALF = 5120.0
THIRD_BOUNDARY = FIELD_Y_HALF / 3.0  # ≈ 1706.7


# ── Output structures ──────────────────────────────────────────────────────────

@dataclass
class PositioningMetrics:
    def_third_pct: float = 0.0
    neut_third_pct: float = 0.0
    off_third_pct: float = 0.0
    def_third_timeseries: list = field(default_factory=list)  # [[t, pct], ...]


@dataclass
class BoostMetrics:
    avg_boost: float = 0.0
    time_zero_s: float = 0.0


@dataclass
class RecoveryMetrics:
    avg_recovery_s: float = 0.0
    slow_recoveries: int = 0
    recovery_events: list = field(default_factory=list)  # [{"t", "duration_s"}, ...]


@dataclass
class KickoffOutcome:
    t: float
    result: str              # "won" | "lost" | "neutral"
    conceded_within_s: Optional[float] = None


@dataclass
class DoubleCommitEvent:
    t: float
    duration_s: float


@dataclass
class PlayerMetrics:
    name: str
    platform_id: str
    team: str
    is_me: bool
    core: dict = field(default_factory=dict)
    positioning: Optional[PositioningMetrics] = None
    boost: Optional[BoostMetrics] = None
    recovery: Optional[RecoveryMetrics] = None


@dataclass
class MatchMetrics:
    players: list = field(default_factory=list)               # list[PlayerMetrics]
    double_commit_events: list = field(default_factory=list)  # list[DoubleCommitEvent]
    kickoff_outcomes: list = field(default_factory=list)      # list[KickoffOutcome]
    possession_chains: list = field(default_factory=list)
    warnings: list = field(default_factory=list)


# ── Helpers ────────────────────────────────────────────────────────────────────

def _col(df: pd.DataFrame, entity: str, attr: str) -> Optional[np.ndarray]:
    try:
        return df[(entity, attr)].to_numpy().astype(float)
    except KeyError:
        return None


def _game_times(df: pd.DataFrame) -> np.ndarray:
    """
    Return canonical in-game elapsed time (seconds) for each frame.

    The in-game clock matches the scoreboard — it is derived from the
    ('game', 'seconds_remaining') column which FREEZES during goal
    celebrations and kickoff countdowns.  This prevents the 10-30s
    per-goal drift that accumulates in the raw ('game', 'time') column.

    Conversion:  elapsed = seconds_remaining[first_valid] − seconds_remaining

    Overtime handling: when seconds_remaining has run to 0 and play
    continues, wall-clock deltas from ('game', 'time') are appended.

    Falls back to raw ('game', 'time'), then to the frame-number index,
    if seconds_remaining is unavailable.
    """
    try:
        sr = df[('game', 'seconds_remaining')].to_numpy(dtype=float, na_value=np.nan)
        valid = ~np.isnan(sr)
        if valid.any():
            return _elapsed_from_sr(sr, valid, df)
    except (KeyError, TypeError, AttributeError):
        pass
    # Fallback 1: raw wall-clock (includes celebration overhead)
    try:
        t = df[('game', 'time')].to_numpy().astype(float)
        if not np.all(np.isnan(t)):
            return t
    except (KeyError, TypeError):
        pass
    # Fallback 2: frame index
    return df.index.to_numpy().astype(float)


def _elapsed_from_sr(sr: np.ndarray, valid: np.ndarray,
                     df: pd.DataFrame) -> np.ndarray:
    """
    Convert a seconds_remaining countdown array to elapsed time.

    Handles:
    - Pre-match frames (sr not yet published → NaN, filled by interpolation)
    - Overtime (sr stuck at 0 while game continues → wall-clock continuation)
    """
    sr0 = float(sr[valid][0])                          # initial clock value e.g. 300
    elapsed = np.where(valid, np.maximum(0.0, sr0 - sr), np.nan)

    # Overtime: sr == 0 but there are still many frames remaining.
    # Threshold of >10 frames at 0 distinguishes genuine overtime from a
    # final celebration that coincidentally ends at 0.
    ot_idx = np.where(valid & (sr == 0))[0]
    if len(ot_idx) > 10:
        try:
            gt = df[('game', 'time')].to_numpy(dtype=float, na_value=np.nan)
            ot_start = int(ot_idx[0])
            gt0 = float(gt[ot_start]) if not np.isnan(gt[ot_start]) else 0.0
            for i in ot_idx:
                if not np.isnan(gt[i]):
                    elapsed[i] = sr0 + max(0.0, float(gt[i]) - gt0)
        except Exception:
            pass  # leave overtime frames at sr0 (close enough)

    # Fill NaN gaps (pre-match frames, any missing values) via linear interpolation
    nan_mask = np.isnan(elapsed)
    if nan_mask.any() and not nan_mask.all():
        idx = np.arange(len(elapsed))
        elapsed = np.interp(idx, idx[~nan_mask], elapsed[~nan_mask])

    return elapsed


def _thirds_masks(y: np.ndarray, is_orange: bool):
    """Return (def_mask, neut_mask, off_mask) bool arrays."""
    if is_orange:
        def_mask = y > THIRD_BOUNDARY
        off_mask = y < -THIRD_BOUNDARY
    else:
        def_mask = y < -THIRD_BOUNDARY
        off_mask = y > THIRD_BOUNDARY
    neut_mask = ~def_mask & ~off_mask
    return def_mask, neut_mask, off_mask


# ── Per-player metrics ─────────────────────────────────────────────────────────

def _positioning(df: pd.DataFrame, name: str, is_orange: bool) -> PositioningMetrics:
    y = _col(df, name, "pos_y")
    if y is None:
        return PositioningMetrics()

    valid = ~np.isnan(y)
    if valid.sum() == 0:
        return PositioningMetrics()

    y_v = y[valid]
    times = _game_times(df)[valid]
    def_m, neut_m, off_m = _thirds_masks(y_v, is_orange)
    n = len(y_v)

    # Rolling 30-second window time-series (sampled every ~3 s)
    duration = float(times[-1] - times[0]) if len(times) > 1 else 1.0
    fps = len(times) / duration if duration > 0 else 30.0
    window = int(30.0 * fps)
    step = max(1, int(3.0 * fps))
    ts = []
    for i in range(0, len(times), step):
        lo, hi = max(0, i - window // 2), min(n, i + window // 2)
        chunk = y_v[lo:hi]
        if len(chunk) == 0:
            continue
        d_m, _, _ = _thirds_masks(chunk, is_orange)
        ts.append([round(float(times[i]), 2), round(100.0 * d_m.sum() / len(chunk), 1)])

    return PositioningMetrics(
        def_third_pct=round(100.0 * def_m.sum() / n, 1),
        neut_third_pct=round(100.0 * neut_m.sum() / n, 1),
        off_third_pct=round(100.0 * off_m.sum() / n, 1),
        def_third_timeseries=ts,
    )


def _boost(df: pd.DataFrame, name: str, duration_s: float) -> BoostMetrics:
    b = _col(df, name, "boost")
    if b is None:
        return BoostMetrics()

    valid = ~np.isnan(b)
    b_v = b[valid]
    if len(b_v) == 0:
        return BoostMetrics()

    # Normalise: carball may store 0-255 or 0-100
    if b_v.max() > 100:
        b_v = b_v / 255.0 * 100.0

    fps = len(b_v) / duration_s if duration_s > 0 else 30.0
    return BoostMetrics(
        avg_boost=round(float(b_v.mean()), 1),
        time_zero_s=round(float((b_v < 5).sum()) / fps, 1),
    )


def _recovery(df: pd.DataFrame, name: str, is_orange: bool,
              hits: list, slow_thresh_s: float) -> RecoveryMetrics:
    """
    After each ball contact by this player, measure time until they return
    to their defensive half (Y < 0 for blue, Y > 0 for orange).
    """
    y = _col(df, name, "pos_y")
    if y is None:
        return RecoveryMetrics()

    times = _game_times(df)
    my_hits = [h for h in hits if h.player_name == name]
    if not my_hits:
        return RecoveryMetrics()

    home_fn = lambda yv: yv > 0.0 if is_orange else yv < 0.0  # noqa: E731
    durations = []
    events = []

    for hit in my_hits:
        idx = int(np.searchsorted(times, hit.time_s))
        if idx >= len(times) - 1:
            continue
        for fi in range(idx, min(idx + int(10 * 30), len(times))):
            if np.isnan(y[fi]):
                continue
            if home_fn(y[fi]):
                dur = times[fi] - hit.time_s
                if dur > 0:
                    durations.append(dur)
                    events.append({"t": round(hit.time_s, 2), "duration_s": round(dur, 2)})
                break

    if not durations:
        return RecoveryMetrics()

    return RecoveryMetrics(
        avg_recovery_s=round(float(np.mean(durations)), 2),
        slow_recoveries=sum(1 for d in durations if d >= slow_thresh_s),
        recovery_events=events,
    )


# ── Team-level metrics ─────────────────────────────────────────────────────────

def _gameplay_mask(df: pd.DataFrame, duration_s: float) -> np.ndarray:
    """
    Boolean mask of frames that belong to live gameplay.

    With the canonical elapsed time from _game_times() (derived from
    seconds_remaining), the clock freezes during goal celebrations and
    kickoff countdowns.  This means celebration frames have elapsed ==
    goal_time ≤ duration_s, so the simple duration cap is both necessary
    and sufficient — only genuine post-match frames can exceed duration_s.

    Falls back to all-True when duration_s is unknown (0).
    """
    times = _game_times(df)
    if duration_s and duration_s > 0:
        return times <= (duration_s + 1.0)   # +1s grace for rounding
    return np.ones(len(times), dtype=bool)


def _double_commits(df: pd.DataFrame, my_team_names: list,
                    min_dur_s: float, duration_s: float = 0.0) -> list:
    """
    Flag windows where ALL players on my team are in the offensive half
    simultaneously while the ball is moving toward our goal.
    Uses offensive *half* (Y > 0 for blue) per PRD definition.
    """
    if not my_team_names or df is None or len(df) == 0:
        return []

    gm = _gameplay_mask(df, duration_s)
    times = _game_times(df)[gm]
    is_orange_team = False  # determined below

    off_masks = []
    for name in my_team_names:
        y = _col(df, name, "pos_y")
        if y is None:
            return []
        off_masks.append(y[gm])

    # Determine team from first player's starting position
    if len(off_masks) > 0 and not np.isnan(off_masks[0][0]):
        is_orange_team = float(off_masks[0][0]) > 0

    all_off = np.ones(len(times), dtype=bool)
    for y in off_masks:
        in_off = y > 0 if not is_orange_team else y < 0
        all_off &= in_off

    ball_vy = _col(df, "ball", "vel_y")
    if ball_vy is None:
        ball_toward_home = np.ones(len(times), dtype=bool)
    else:
        ball_toward_home = (ball_vy[gm] < 0) if not is_orange_team else (ball_vy[gm] > 0)

    trigger = all_off & ball_toward_home

    events = []
    in_ev, start_t = False, 0.0
    for i, val in enumerate(trigger):
        if val and not in_ev:
            in_ev, start_t = True, times[i]
        elif not val and in_ev:
            in_ev = False
            dur = times[i] - start_t
            if dur >= min_dur_s:
                events.append(DoubleCommitEvent(t=round(start_t, 2), duration_s=round(dur, 2)))
    if in_ev:
        dur = times[-1] - start_t
        if dur >= min_dur_s:
            events.append(DoubleCommitEvent(t=round(start_t, 2), duration_s=round(dur, 2)))

    return events


def _kickoff_outcomes(df: pd.DataFrame, goals: list, duration_s: float) -> list:
    """Detect kickoff moments (ball near center) and classify win/loss/neutral."""
    if df is None or len(df) == 0:
        return []

    bx = _col(df, "ball", "pos_x")
    by = _col(df, "ball", "pos_y")
    if bx is None or by is None:
        return []

    gm = _gameplay_mask(df, duration_s)
    times = _game_times(df)[gm]
    bx = bx[gm]
    by = by[gm]
    at_center = (np.abs(bx) < 100) & (np.abs(by) < 100)

    kickoff_times = [0.0]
    for i in range(1, len(at_center)):
        if at_center[i] and not at_center[i - 1]:
            kickoff_times.append(float(times[i]))

    goal_times = sorted(g.time_s for g in goals)
    outcomes = []
    for i, kt in enumerate(kickoff_times):
        next_kt = kickoff_times[i + 1] if i + 1 < len(kickoff_times) else duration_s + 1
        in_period = [gt for gt in goal_times if kt < gt < next_kt]
        if in_period:
            first_gt = in_period[0]
            first_goal = next((g for g in goals if abs(g.time_s - first_gt) < 0.5), None)
            if first_goal and first_goal.scoring_team == "orange":
                outcomes.append(KickoffOutcome(t=round(kt, 2), result="lost",
                                               conceded_within_s=round(first_gt - kt, 2)))
            else:
                outcomes.append(KickoffOutcome(t=round(kt, 2), result="won"))
        else:
            outcomes.append(KickoffOutcome(t=round(kt, 2), result="neutral"))

    return outcomes


def _possession_chains(hits: list) -> list:
    chains = []
    current = None
    for h in sorted(hits, key=lambda x: x.time_s):
        team = getattr(h, "team", None)
        if team is None:
            continue
        if current is None or current["team"] != team:
            if current:
                chains.append(current)
            current = {"team": team, "start_t": round(h.time_s, 2),
                       "end_t": round(h.time_s, 2), "touch_count": 1}
        else:
            current["end_t"] = round(h.time_s, 2)
            current["touch_count"] += 1
    if current:
        chains.append(current)
    return chains


# ── Public API ─────────────────────────────────────────────────────────────────

def compute_metrics(parsed: ParsedReplay, my_player_id: str,
                    slow_recovery_s: float = 3.0,
                    double_commit_min_s: float = 1.0) -> MatchMetrics:

    df = parsed.frame_df
    warnings = list(parsed.warnings)

    if df is None or len(df) == 0:
        warnings.append("No frame data — all position metrics unavailable")
        player_metrics = [
            PlayerMetrics(
                name=p.name, platform_id=p.platform_id, team=p.team,
                is_me=_is_me(p.platform_id, my_player_id),
                core={"goals": p.goals, "shots": p.shots, "assists": p.assists,
                      "saves": p.saves, "score": p.score},
            )
            for p in parsed.players
        ]
        return MatchMetrics(players=player_metrics, warnings=warnings)

    # Annotate hits with team
    player_team = {p.name: p.team for p in parsed.players}
    for h in parsed.hits:
        h.team = player_team.get(h.player_name)

    # Per-player metrics
    player_metrics = []
    for p in parsed.players:
        pm = PlayerMetrics(
            name=p.name,
            platform_id=p.platform_id,
            team=p.team,
            is_me=_is_me(p.platform_id, my_player_id),
            core={"goals": p.goals, "shots": p.shots, "assists": p.assists,
                  "saves": p.saves, "score": p.score},
        )
        try:
            pm.positioning = _positioning(df, p.name, p.is_orange)
            pm.boost = _boost(df, p.name, parsed.duration_s)
            pm.recovery = _recovery(df, p.name, p.is_orange, parsed.hits, slow_recovery_s)
        except Exception as e:
            warnings.append(f"Metrics error for {p.name}: {e}")
        player_metrics.append(pm)

    # Determine my team
    me_meta = next((p for p in parsed.players if _is_me(p.platform_id, my_player_id)), None)
    my_team_names = (
        [p.name for p in parsed.players if p.team == me_meta.team]
        if me_meta else
        [p.name for p in parsed.players if not p.is_orange]
    )

    # Use game-time-derived duration as fallback when header TotalSecondsPlayed is 0
    dur = parsed.duration_s
    if not dur or dur <= 0:
        t = _game_times(df)
        dur = float(t[-1]) if len(t) > 0 else 0.0

    double_commits, kickoffs, chains = [], [], []
    try:
        double_commits = _double_commits(df, my_team_names, double_commit_min_s, dur)
    except Exception as e:
        warnings.append(f"Double-commit detection error: {e}")
    try:
        kickoffs = _kickoff_outcomes(df, parsed.goals, dur)
    except Exception as e:
        warnings.append(f"Kickoff analysis error: {e}")
    try:
        chains = _possession_chains(parsed.hits)
    except Exception as e:
        warnings.append(f"Possession chain error: {e}")

    return MatchMetrics(
        players=player_metrics,
        double_commit_events=double_commits,
        kickoff_outcomes=kickoffs,
        possession_chains=chains,
        warnings=warnings,
    )


def _is_me(platform_id: str, my_id: str) -> bool:
    if not my_id:
        return False
    return (platform_id == my_id or
            my_id.split(":")[-1] in platform_id or
            platform_id.split(":")[-1] in my_id)
