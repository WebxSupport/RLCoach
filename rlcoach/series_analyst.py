"""
Series (multi-match) analysis.

Aggregates the per-match data we already compute (match.json) across a set of
recent ranked games, computes win-vs-loss splits and trends, then asks Claude
Sonnet 4.6 for a session-level "series report". Native to our stack — no
external dependency on third-party analysers.
"""
from __future__ import annotations
import json
import logging
import re
import statistics as stats
from datetime import date
from pathlib import Path
from typing import Optional

log = logging.getLogger(__name__)

MODEL = "claude-sonnet-4-6"
MAX_TOKENS = 6000


# ── aggregation ───────────────────────────────────────────────────────────────

def _me(mj: dict) -> Optional[dict]:
    for p in mj.get("players", []):
        if p.get("is_me"):
            return p
    return None


def _mean(xs):
    xs = [x for x in xs if x is not None]
    return round(stats.fmean(xs), 1) if xs else None


def _analysis_fields(mj: dict, name: Optional[str]) -> dict:
    """
    Pull the tracked player's NEW framework metrics from match.json["analysis"]
    (positioning / touch / shooting). Returns {} for older match.jsons that
    predate the analysis block — those fields stay absent and are simply
    excluded from the averages (graceful degradation as replays re-fetch).
    """
    a = mj.get("analysis") or {}
    if not a or not name:
        return {}
    out: dict = {}
    pos = (a.get("positioning") or {}).get(name)
    if isinstance(pos, dict):
        cov = pos.get("coverage") or {}
        sup = pos.get("support") or {}
        lm = pos.get("last_man") or {}
        out["back_post_pct"] = cov.get("back_post_pct")
        out["near_post_pct"] = cov.get("near_post_pct")
        out["own_half_pct"] = cov.get("own_half_pct")
        out["support_too_close_pct"] = sup.get("too_close_pct")
        out["support_too_far_pct"] = sup.get("too_far_pct")
        out["last_man_risky_pct"] = lm.get("risky_push_pct")
    tp = ((a.get("touch") or {}).get("per_player") or {}).get(name)
    if isinstance(tp, dict):
        tot = tp.get("total") or 0
        out["touch_positive_pct"] = round(100 * (tp.get("positive", 0)) / tot, 1) if tot else None
        out["giveaways"] = tp.get("giveaways")
        ch = tp.get("challenges") or 0
        out["challenge_win_pct"] = round(100 * (tp.get("challenge_wins", 0)) / ch, 1) if ch else None
    sh = a.get("shooting") or {}
    me_sh = next((v for v in (sh.get("per_player") or {}).values()
                  if isinstance(v, dict) and v.get("is_me")), None)
    if me_sh:
        out["xg"] = me_sh.get("xg")
        out["xg_diff"] = round((me_sh.get("goals", 0) or 0) - (me_sh.get("xg") or 0), 2)
    rot = a.get("rotation") or {}
    opp = rot.get("opportunities") or 0
    if opp:
        out["rotation_score"] = rot.get("score")
        out["poor_rotation_pct"] = round(100 * (rot.get("poor", 0) + rot.get("critical", 0)) / opp, 1)
        out["critical_errors"] = rot.get("critical")
    return out


def _extract_game(mj: dict) -> Optional[dict]:
    """Pull the tracked player's per-game line from one match.json."""
    me = _me(mj)
    if not me:
        return None
    res = mj.get("result", {})
    pt = res.get("player_team", "blue")
    bs, os_ = res.get("blue_score", 0), res.get("orange_score", 0)
    my, opp = (os_, bs) if pt == "orange" else (bs, os_)
    win = bool(res.get("win", False))
    core = me.get("core", {})
    pos = me.get("positioning") or {}
    boost = me.get("boost") or {}
    air = me.get("air") or {}
    dc = len((mj.get("team_metrics") or {}).get("double_commit_events", []))
    shots = core.get("shots", 0) or 0
    goals = core.get("goals", 0) or 0
    g = {
        "result": f"W{my}-{opp}" if win else (f"D{my}-{opp}" if my == opp else f"L{my}-{opp}"),
        "win": win,
        "map": mj.get("map_display") or mj.get("map") or "Unknown",
        "played_at": mj.get("played_at", 0) or 0,
        "goals": goals, "shots": shots, "saves": core.get("saves", 0),
        "assists": core.get("assists", 0), "score": core.get("score", 0),
        "conv": round(100 * goals / shots, 0) if shots else 0,
        "def_third": pos.get("def_third_pct"), "off_third": pos.get("off_third_pct"),
        "avg_boost": boost.get("avg_boost"), "time_zero_s": boost.get("time_zero_s"),
        "air_time_pct": air.get("air_time_pct"), "high_air_pct": air.get("high_air_pct"),
        "double_commits": dc,
    }
    g.update(_analysis_fields(mj, me.get("name")))  # merge the new framework metrics
    return g


def aggregate_matches(match_jsons: list, limit: int = 10) -> dict:
    """
    Build the hard aggregate (records, averages, win/loss splits, per-game) from
    match.jsons. Only the most recent `limit` games (default 10) are analysed.
    """
    games = [g for g in (_extract_game(mj) for mj in match_jsons) if g]
    games.sort(key=lambda g: g["played_at"], reverse=True)
    games = games[:max(1, limit)]   # cap long-term analysis to the N most recent
    if not games:
        return {"games": 0}

    wins = [g for g in games if g["win"]]
    losses = [g for g in games if not g["win"] and not g["result"].startswith("D")]

    metric_keys = ["goals", "shots", "saves", "assists", "conv", "avg_boost",
                   "time_zero_s", "def_third", "off_third", "air_time_pct",
                   "high_air_pct", "double_commits",
                   # new framework metrics (None on pre-analysis match.jsons → excluded)
                   "back_post_pct", "near_post_pct", "own_half_pct",
                   "support_too_close_pct", "support_too_far_pct", "last_man_risky_pct",
                   "touch_positive_pct", "giveaways", "challenge_win_pct", "xg", "xg_diff",
                   "rotation_score", "poor_rotation_pct", "critical_errors"]

    def avg_over(rows, key):
        return _mean([r.get(key) for r in rows])

    overall = {k: avg_over(games, k) for k in metric_keys}
    win_avg = {k: avg_over(wins, k) for k in metric_keys}
    loss_avg = {k: avg_over(losses, k) for k in metric_keys}

    # How many of the analysed games actually carry the new metrics yet.
    analysed = sum(1 for g in games if g.get("back_post_pct") is not None or g.get("xg") is not None)

    return {
        "games": len(games),
        "wins": len(wins),
        "losses": len(losses),
        "framework_games": analysed,   # games with the new metrics available
        "averages": overall,
        "winAverages": win_avg,
        "lossAverages": loss_avg,
        "perGame": [
            {"n": i + 1, "result": g["result"], "win": g["win"], "map": g["map"],
             "goals": g["goals"], "shots": g["shots"], "saves": g["saves"],
             "avg_boost": g["avg_boost"], "double_commits": g["double_commits"],
             "air_time_pct": g["air_time_pct"],
             "support_too_close_pct": g.get("support_too_close_pct"),
             "challenge_win_pct": g.get("challenge_win_pct"),
             "giveaways": g.get("giveaways"), "xg": g.get("xg")}
            for i, g in enumerate(games)
        ],
    }


# ── Claude series report ──────────────────────────────────────────────────────

_SYSTEM = """You are an elite Rocket League analyst writing a session/series report across many games.
Return ONLY a single JSON object in a ```json code block — no prose outside it."""

_PROMPT = """
# Series analysis — {games} recent ranked {gamemode} games for {player}

## Aggregated data (hard numbers — already computed)
Record: {wins}W - {losses}L over {games} games.

Per-game lines and win/loss averages:
```json
{agg}
```

## Metric legend (averages/winAverages/lossAverages keys)
Core: goals, shots, saves, assists, conv (conversion %), avg_boost, time_zero_s, def_third/off_third
(% time in each third), air_time_pct, double_commits. Framework metrics (when present — derived from
frame data): back_post_pct / near_post_pct (defensive coverage side — high near-post = ball-side
rotation), own_half_pct, support_too_close_pct / support_too_far_pct (support distance vs the
1800-2500uu band), last_man_risky_pct (last-man pushed out of own half), touch_positive_pct
(share of touches that kept/created), giveaways, challenge_win_pct, xg (expected goals), xg_diff
(goals − xG; negative = finishing problem), rotation_score (0-100, quality of rotations out of the
play), poor_rotation_pct (% of rotations graded poor/critical — ball-side / through-middle /
overcommit), critical_errors (rotations that exposed the net or caused a double-commit). Lean on
these framework metrics where available — they are the highest-resolution signal.

## Your task
Find the SESSION-LEVEL story across these games — not single-match noise. Compare the player's
**win averages vs loss averages** to isolate what actually separates their wins from losses
(the highest-leverage finding). Assess **consistency** (are the bad games clustered, is one metric
swinging wildly?). Identify the **single recurring habit** holding them back, and the **trend**
across the session. Every claim cites the numbers.

Return EXACTLY this JSON:
```json
{{
  "headline": "one punchy sentence — the biggest session-level takeaway",
  "summary": "2-3 sentences framing the session",
  "winVsLoss": [
    {{ "metric": "e.g. Avg boost", "win": 0, "loss": 0, "insight": "what this difference means" }}
  ],
  "consistency": [ {{ "label": "short", "detail": "one line with numbers" }} ],
  "recurringHabit": {{ "title": "short", "detail": "the one habit, with evidence across games" }},
  "trend": "improving | flat | declining — one sentence of why, from the per-game order",
  "topFixes": [ {{ "title": "short", "detail": "what to do", "metric": "current → target" }} ]
}}
```
Rules:
- `winVsLoss`: 3-5 metrics where wins and losses differ most (use winAverages vs lossAverages).
- `topFixes`: exactly 3, ranked by impact, each tied to a number.
- Be specific and honest; this is a Grand-Champion-level read of the session.
"""


def _extract_json(text: str) -> Optional[dict]:
    m = re.search(r"```json\s*([\s\S]+?)\s*```", text, re.IGNORECASE)
    if m:
        try:
            return json.loads(m.group(1))
        except json.JSONDecodeError:
            pass
    start = text.find("{")
    if start != -1:
        depth = 0
        for i, ch in enumerate(text[start:], start):
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(text[start:i + 1])
                    except json.JSONDecodeError:
                        break
    return None


def generate_series_report(aggregate: dict, profile: dict, api_key: str) -> dict:
    """Aggregate → Claude → SERIES object (with hard aggregate merged back in)."""
    import anthropic

    gamemode = profile.get("gamemode", "2v2")
    player = profile.get("display_name") or "Player"

    prompt = _PROMPT.format(
        games=aggregate.get("games", 0),
        wins=aggregate.get("wins", 0),
        losses=aggregate.get("losses", 0),
        gamemode=gamemode, player=player,
        agg=json.dumps({k: aggregate[k] for k in
                        ("averages", "winAverages", "lossAverages", "perGame") if k in aggregate},
                       ensure_ascii=False)[:9000],
    )

    client = anthropic.Anthropic(api_key=api_key)
    log.info("Generating series report via %s over %d games…", MODEL, aggregate.get("games", 0))
    msg = client.messages.create(
        model=MODEL, max_tokens=MAX_TOKENS, system=_SYSTEM,
        messages=[{"role": "user", "content": prompt}],
    )
    report = _extract_json(msg.content[0].text)
    if report is None:
        raise ValueError("Could not parse the series report JSON from Claude")

    report["meta"] = {
        "player": player,
        "gamemode": gamemode,
        "generated": date.today().isoformat(),
    }
    report["record"] = {"games": aggregate.get("games", 0),
                        "wins": aggregate.get("wins", 0),
                        "losses": aggregate.get("losses", 0)}
    report["averages"] = aggregate.get("averages", {})
    report["perGame"] = aggregate.get("perGame", [])
    return report
