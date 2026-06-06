"""
Layer 3 — pattern-recognition engine.

The framework's "most valuable piece": it does not report stats, it identifies
recurring habits, their match impact, and the fix. Every pattern is emitted in
the canonical coaching structure:

    Evidence   — the numbers that prove it happened
    Pattern    — the habit, named plainly
    Consequence— what it cost in THIS match (goals, double-commits, turnovers)
    Fix        — the concrete behavioural change + a target metric

It consumes the lower layers (positioning, touch_analysis, metrics,
extended_metrics) for the tracked player, scores each detected habit by
frequency × match-impact, applies optional rank-tier focus weighting, and
returns the highest-impact patterns. Representative timestamps are attached so
the wiring phase can render an actual-vs-ideal diagram per pattern.
"""
from __future__ import annotations

import logging
from dataclasses import asdict, dataclass, field
from typing import Optional

from .metrics import _is_me

log = logging.getLogger(__name__)


# ── Output structures ────────────────────────────────────────────────────────

@dataclass
class Pattern:
    category: str          # rotation | possession | positioning | boost | challenge | defense
    title: str             # short habit label
    severity: str          # critical | major | minor
    evidence: str
    pattern: str
    consequence: str
    fix: str
    metric: str            # "current X → target Y"
    confidence: float      # 0..1
    score: float = 0.0     # internal ranking score (frequency × impact)
    diagram: Optional[str] = None   # which renderer fits: support|coverage|lastman|None
    timestamps: list = field(default_factory=list)  # representative moments for diagrams


@dataclass
class PatternReport:
    player: str
    is_me: bool
    rank_tier: Optional[str]
    patterns: list = field(default_factory=list)   # list[Pattern], ranked
    summary: str = ""


# Rank-tier focus — boosts the score of the categories that matter most at each
# tier (from the framework's rank-specific coaching). Optional.
TIER_FOCUS = {
    "bronze": {"possession": 1.4, "positioning": 1.3, "rotation": 1.2},
    "silver": {"possession": 1.4, "positioning": 1.3, "rotation": 1.2},
    "gold": {"possession": 1.3, "positioning": 1.3, "rotation": 1.3},
    "platinum": {"rotation": 1.4, "challenge": 1.3, "boost": 1.2, "defense": 1.2},
    "diamond": {"rotation": 1.4, "challenge": 1.3, "boost": 1.2, "defense": 1.2},
    "champion": {"possession": 1.3, "positioning": 1.3, "challenge": 1.2},
    "grandchampion": {"challenge": 1.4, "positioning": 1.3, "boost": 1.2},
    "ssl": {"challenge": 1.4, "positioning": 1.3, "boost": 1.3},
}


def _tier_key(rank_tier: Optional[str]) -> Optional[str]:
    if not rank_tier:
        return None
    r = rank_tier.lower()
    for key in TIER_FOCUS:
        if key in r:
            return key
    return None


# ── Context assembly ───────────────────────────────────────────────────────

def _build_context(parsed, my_player_id, positioning, touch, metrics, extended):
    me = next((p for p in parsed.players if _is_me(p.platform_id, my_player_id)), None)
    if me is None:
        return None
    name, team = me.name, me.team
    enemy = "orange" if team == "blue" else "blue"

    pos = next((pp for pp in positioning if pp.name == name), None)
    pm = next((m for m in metrics.players if m.name == name), None)
    tsum = touch.per_player.get(name) if touch else None
    ext_pp = (extended.get("per_player", {}) or {}).get(name, {})
    bc = (extended.get("ballchase", {}) or {}).get("players", {}).get(name, {})

    goals_conceded = sum(1 for g in parsed.goals if g.scoring_team == enemy)
    goals_scored = sum(1 for g in parsed.goals if g.scoring_team == team)
    conceded_windows = [w for w in (extended.get("goal_windows") or []) if w.get("conceded")]

    return {
        "name": name, "team": team, "enemy": enemy,
        "pos": pos, "pm": pm, "tsum": tsum, "ext_pp": ext_pp,
        "ballchase_idx": bc.get("index"),
        "double_commits": len(metrics.double_commit_events),
        "dc_events": metrics.double_commit_events,
        "goals_conceded": goals_conceded, "goals_scored": goals_scored,
        "conceded_windows": conceded_windows,
        "kickoffs": metrics.kickoff_outcomes,
    }


# ── Detectors ───────────────────────────────────────────────────────────────
# Each returns a Pattern or None. Thresholds are heuristic; targets come from
# the framework. Severity/score scale with how far past the threshold + impact.

def _sev(eff: float) -> str:
    """Grade severity off the confidence-weighted effective score."""
    return "critical" if eff >= 5 else "major" if eff >= 2.5 else "minor"


def _d_over_support(ctx) -> Optional[Pattern]:
    pos = ctx["pos"]
    if not pos or pos.support.support_frames < 30:
        return None
    close = pos.support.too_close_pct
    if close < 30:
        return None
    dc = ctx["double_commits"]
    # impact: how tight + how many double commits it produced
    score = (close - 30) / 10 + dc * 1.2
    moments = [m.t for m in pos.support.worst_moments if m.kind == "too_close"][:4]
    return Pattern(
        category="positioning", title="Over-supporting the play", severity=_sev(score),
        evidence=(f"You were inside the {int(pos.support.support_frames)}-frame support window "
                  f"and TOO CLOSE to your teammate {close:.0f}% of the time "
                  f"(avg {pos.support.avg_support_dist:.0f}uu)."),
        pattern="You collapse onto your teammate when they have the ball instead of holding a support gap.",
        consequence=(f"This fed {dc} double-commit window(s) this match"
                     + (f" and contributed to {ctx['goals_conceded']} conceded goal(s)." if dc else ".")),
        fix="Hold 1800–2500uu of support distance as second man — close enough to follow up, far enough that losing the ball doesn't open the net.",
        metric=f"too-close {close:.0f}% → <20%",
        confidence=0.8, score=score, diagram="support", timestamps=moments,
    )


def _d_under_support(ctx) -> Optional[Pattern]:
    pos = ctx["pos"]
    if not pos or pos.support.support_frames < 30:
        return None
    far = pos.support.too_far_pct
    if far < 55:
        return None
    score = (far - 55) / 12
    moments = [m.t for m in pos.support.worst_moments if m.kind == "too_far"][:4]
    return Pattern(
        category="positioning", title="Supporting too far back", severity=_sev(score),
        evidence=f"As support you were TOO FAR from the ball-carrier {far:.0f}% of the time (avg {pos.support.avg_support_dist:.0f}uu).",
        pattern="You sit too deep behind the play, so there is no follow-up when your teammate's touch creates a chance.",
        consequence="Won balls die with no second-man support; attacks fizzle and possession is handed back.",
        fix="Close the gap to 1800–2500uu when your teammate is attacking so you can finish rebounds.",
        metric=f"too-far {far:.0f}% → <40%",
        confidence=0.65, score=score, diagram="support", timestamps=moments,
    )


def _d_ball_side(ctx) -> Optional[Pattern]:
    pos = ctx["pos"]
    if not pos:
        return None
    near, back = pos.coverage.near_post_pct, pos.coverage.back_post_pct
    if near < 12 or near <= back * 1.5:
        return None
    score = (near - back) / 6
    return Pattern(
        category="rotation", title="Ball-side / near-post rotation", severity=_sev(score),
        evidence=f"In your own half you covered the NEAR post {near:.0f}% vs the BACK post only {back:.0f}%.",
        pattern="You rotate ball-side and cover the near post, cutting across your teammate instead of taking back post.",
        consequence="Cross-crease passes and back-post taps go unguarded — the most common 2s concession.",
        fix="Default to BACK post, goal-side and facing play. When unsure whose ball it is, take the far post, not the near one.",
        metric=f"back-post {back:.0f}% → >40%",
        confidence=0.7, score=score, diagram="coverage", timestamps=[],
    )


def _d_overcommit(ctx) -> Optional[Pattern]:
    pos = ctx["pos"]
    if not pos:
        return None
    own = pos.coverage.own_half_pct
    bc = ctx["ballchase_idx"]
    # overcommitting: spends little time in own half AND/OR chronic ballchase
    trigger = (own < 42) or (bc is not None and bc > 10)
    if not trigger:
        return None
    score = 0.0
    if own < 42:
        score += (42 - own) / 5
    if bc is not None and bc > 10:
        score += (bc - 10) / 3
    score += ctx["double_commits"] * 0.8
    ev = f"You spent only {own:.0f}% of live play in your own half"
    if bc is not None:
        ev += f"; ballchase index {bc:.0f}% ({'chronic' if bc > 10 else 'loose'})"
    ev += "."
    return Pattern(
        category="rotation", title="Overcommitting / ball-chasing", severity=_sev(score),
        evidence=ev,
        pattern="You follow the ball forward instead of rotating out, leaving your teammate isolated on defence.",
        consequence=(f"{ctx['double_commits']} double-commit window(s); counters arrive with your net undermanned."),
        fix="After your touch, rotate out wide and back — cede the ball to your teammate and reset to cover.",
        metric=f"own-half time {own:.0f}% → >55%" + (f", ballchase {bc:.0f}% → <8%" if bc is not None else ""),
        confidence=0.75, score=score, diagram="coverage", timestamps=[e.t for e in ctx["dc_events"][:4]],
    )


def _d_last_man_risk(ctx) -> Optional[Pattern]:
    pos = ctx["pos"]
    if not pos or pos.last_man.last_man_pct < 15:
        return None
    risk = pos.last_man.risky_push_pct
    if risk < 18:
        return None
    score = (risk - 18) / 6 + ctx["goals_conceded"] * 0.5
    moments = [m.t for m in pos.last_man.risky_moments][:4]
    return Pattern(
        category="defense", title="Last-man overcommit", severity=_sev(score),
        evidence=(f"You were last defender {pos.last_man.last_man_pct:.0f}% of the match and pushed "
                  f"out of your defensive half while last man {risk:.0f}% of that time."),
        pattern="As the last line of defence you step to the ball instead of holding — if you lose it, the net is open.",
        consequence=f"Directly exposes the net; tied to {ctx['goals_conceded']} conceded goal(s) this match.",
        fix="When last man, apply the commit test: 'if I lose this, is the net open?' If yes — shadow and delay, don't challenge.",
        metric=f"risky last-man pushes {risk:.0f}% → <10%",
        confidence=0.7, score=score, diagram="lastman", timestamps=moments,
    )


def _d_giveaways(ctx) -> Optional[Pattern]:
    t = ctx["tsum"]
    if not t or t.total < 10:
        return None
    give = t.giveaways
    neg_rate = 100.0 * t.negative / t.total if t.total else 0
    if give < 2 and neg_rate < 18:
        return None
    score = give * 1.4 + max(0, neg_rate - 18) / 5
    return Pattern(
        category="possession", title="Giving away possession", severity=_sev(score),
        evidence=(f"{give} clear giveaway(s) (lost the ball with space and time) and "
                  f"{t.negative}/{t.total} negative touches ({neg_rate:.0f}%)."),
        pattern="You surrender the ball under little pressure — rushing the touch when you had time to settle it.",
        consequence="Each giveaway hands the opponent a free attack; turnovers are the leading feed to counters.",
        fix="When unpressured, take a controlled first touch into space before moving the ball — don't first-time it away.",
        metric=f"giveaways {give} → 0; negative touches {neg_rate:.0f}% → <10%",
        confidence=0.7, score=score, diagram=None, timestamps=[],
    )


def _d_panic_clears(ctx) -> Optional[Pattern]:
    t = ctx["tsum"]
    if not t:
        return None
    panic = t.type_counts.get("panic", 0)
    clears = t.type_counts.get("clear", 0)
    if panic < 2 and clears < 8:
        return None
    score = panic * 1.6 + max(0, clears - 8) / 3
    if score < 2:
        return None
    return Pattern(
        category="possession", title="Panic clears / booming the ball away", severity=_sev(score),
        evidence=f"{panic} panic touch(es) and {clears} clears — much of your defensive output is hitting the ball away, not controlling it.",
        pattern="Under pressure you boom the ball rather than make a controlled save/clear, conceding possession every time.",
        consequence="The ball comes straight back; you defend the same attack repeatedly instead of escaping with it.",
        fix="Clear WIDE toward the boost/wall (never up the middle), or take the controlled save to keep possession when you have the half-second.",
        metric=f"panic touches {panic} → 0",
        confidence=0.6, score=score, diagram=None, timestamps=[],
    )


def _d_challenge_timing(ctx) -> Optional[Pattern]:
    t = ctx["tsum"]
    if not t or t.challenges < 5:
        return None
    losses = t.challenges - t.challenge_wins
    loss_rate = 100.0 * losses / t.challenges
    if loss_rate < 55:
        return None
    score = (loss_rate - 55) / 8 + ctx["goals_conceded"] * 0.4
    return Pattern(
        category="challenge", title="Losing challenges (poor timing)", severity=_sev(score),
        evidence=f"You lost {losses}/{t.challenges} challenges ({loss_rate:.0f}%).",
        pattern="Your challenge timing is off — committing early or flat-footed, so you lose the 50/50 and the space behind it.",
        consequence=f"Lost challenges in midfield let opponents through your first line; tied to {ctx['goals_conceded']} concession(s).",
        fix="Delay the challenge — match the attacker's speed, stay goal-side, and strike as they touch, not before.",
        metric=f"challenge loss rate {loss_rate:.0f}% → <45%",
        confidence=0.6, score=score, diagram=None, timestamps=[],
    )


def _d_boost_starve(ctx) -> Optional[Pattern]:
    ext = ctx["ext_pp"] or {}
    pm = ctx["pm"]
    starve = ext.get("starve_pct")
    if starve is None and pm and pm.boost:
        # fall back to time at zero as a rough proxy share — skip if unknown
        starve = None
    if starve is None or starve < 12:
        return None
    avg = ext.get("avg_boost", pm.boost.avg_boost if pm and pm.boost else None)
    score = (starve - 12) / 4
    ev = f"You were boost-starved (<5 boost) {starve:.0f}% of the match"
    if avg is not None and avg <= 100:   # guard against unnormalised 0–255 boost
        ev += f", averaging {avg:.0f} boost"
    ev += "."
    return Pattern(
        category="boost", title="Boost starvation", severity=_sev(score),
        evidence=ev,
        pattern="You run empty too often — over-spending then chasing big pads, arriving to plays with nothing.",
        consequence="No boost means no challenge, no rotation speed, and slow recoveries — you're a passenger when starved.",
        fix="Route through small pads on every rotation; keep a working reserve (~30+) instead of committing to 0.",
        metric=f"time starved {starve:.0f}% → <8%",
        confidence=0.7, score=score, diagram=None, timestamps=[],
    )


def _d_slow_reset(ctx) -> Optional[Pattern]:
    # NOTE: the recovery metric measures time to get back to one's own half
    # after a touch — a rotation/reset signal (conflated with mechanical
    # recovery), and naturally long for attackers. Kept conservative: only
    # fires when clearly slow, capped so it can't dominate the ranking.
    pm = ctx["pm"]
    if not pm or not pm.recovery or not pm.recovery.recovery_events:
        return None
    avg = pm.recovery.avg_recovery_s
    slow = pm.recovery.slow_recoveries
    if avg < 3.0 and slow < 6:
        return None
    score = min(6.0, slow * 0.35 + max(0.0, avg - 3.0) * 1.0)
    if score < 2:
        return None
    return Pattern(
        category="rotation", title="Slow to reset into defence", severity=_sev(score),
        evidence=f"Averaged {avg:.1f}s to get back to your defensive half after a touch ({slow} resets ≥3s).",
        pattern="After committing forward you drift rather than rotating straight back, so you reset into defence late.",
        consequence="You arrive late on the counter — the second wave catches you out of position.",
        fix="Rotate back the instant the ball leaves you: powerslide to face play, half-flip when behind it, and beeline for back post.",
        metric=f"avg reset {avg:.1f}s → <2.0s",
        confidence=0.5, score=score, diagram=None, timestamps=[e["t"] for e in pm.recovery.recovery_events[:4]],
    )


_DETECTORS = [
    _d_over_support, _d_under_support, _d_ball_side, _d_overcommit,
    _d_last_man_risk, _d_giveaways, _d_panic_clears, _d_challenge_timing,
    _d_boost_starve, _d_slow_reset,
]


# ── Public API ────────────────────────────────────────────────────────────────

def compute_patterns(parsed, my_player_id: str, *,
                     positioning=None, touch=None, metrics=None, extended=None,
                     rank_tier: Optional[str] = None, top_n: int = 6) -> PatternReport:
    """
    Detect and rank the tracked player's recurring habits.

    Sub-analyses are computed on demand if not supplied, so this can be called
    standalone:  compute_patterns(parsed, my_id).
    """
    if metrics is None:
        from .metrics import compute_metrics
        metrics = compute_metrics(parsed, my_player_id)
    if positioning is None:
        from .positioning import compute_positioning
        positioning = compute_positioning(parsed, my_player_id)
    if touch is None:
        from .touch_analysis import compute_touch_analysis
        touch = compute_touch_analysis(parsed, my_player_id)
    if extended is None:
        from .extended_metrics import compute_extended_metrics
        try:
            extended = compute_extended_metrics(parsed.frame_df, parsed, my_player_id, parsed.duration_s)
        except Exception as e:
            log.debug("extended metrics unavailable for patterns: %s", e)
            extended = {}

    ctx = _build_context(parsed, my_player_id, positioning, touch, metrics, extended)
    if ctx is None:
        return PatternReport(player="", is_me=False, rank_tier=rank_tier,
                             summary="Tracked player not found in this replay.")

    tier = _tier_key(rank_tier)
    focus = TIER_FOCUS.get(tier, {}) if tier else {}

    patterns = []
    for det in _DETECTORS:
        try:
            p = det(ctx)
        except Exception as e:
            log.debug("detector %s failed: %s", det.__name__, e)
            p = None
        if p is None:
            continue
        if focus:
            p.score *= focus.get(p.category, 1.0)
        # Clamp to a comparable 0–10 range so no single detector's raw formula
        # can dominate, then grade + rank by the CONFIDENCE-WEIGHTED score so a
        # low-confidence (conflated) signal can't outrank a solid one.
        p.score = round(min(p.score, 10.0), 2)
        p.severity = _sev(p.score * p.confidence)
        patterns.append(p)

    patterns.sort(key=lambda x: x.score * x.confidence, reverse=True)
    patterns = patterns[:top_n]

    summary = _summarise(ctx, patterns)
    return PatternReport(
        player=ctx["name"], is_me=True, rank_tier=rank_tier,
        patterns=patterns, summary=summary,
    )


def _summarise(ctx, patterns) -> str:
    if not patterns:
        return (f"No high-impact habits detected for {ctx['name']} "
                f"({ctx['goals_scored']}-{ctx['goals_conceded']}). Solid, balanced game.")
    top = patterns[0]
    return (f"{ctx['name']}'s biggest fixable habit this match: {top.title.lower()} "
            f"({top.severity}). {top.consequence}")


def patterns_to_dict(report: PatternReport) -> dict:
    return {
        "player": report.player,
        "is_me": report.is_me,
        "rank_tier": report.rank_tier,
        "summary": report.summary,
        "patterns": [asdict(p) for p in report.patterns],
    }
