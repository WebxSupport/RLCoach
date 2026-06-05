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
    return {
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


def aggregate_matches(match_jsons: list) -> dict:
    """Build the hard aggregate (records, averages, win/loss splits, per-game) from match.jsons."""
    games = [g for g in (_extract_game(mj) for mj in match_jsons) if g]
    games.sort(key=lambda g: g["played_at"], reverse=True)
    if not games:
        return {"games": 0}

    wins = [g for g in games if g["win"]]
    losses = [g for g in games if not g["win"] and not g["result"].startswith("D")]

    metric_keys = ["goals", "shots", "saves", "assists", "conv", "avg_boost",
                   "time_zero_s", "def_third", "off_third", "air_time_pct",
                   "high_air_pct", "double_commits"]

    def avg_over(rows, key):
        return _mean([r.get(key) for r in rows])

    overall = {k: avg_over(games, k) for k in metric_keys}
    win_avg = {k: avg_over(wins, k) for k in metric_keys}
    loss_avg = {k: avg_over(losses, k) for k in metric_keys}

    return {
        "games": len(games),
        "wins": len(wins),
        "losses": len(losses),
        "averages": overall,
        "winAverages": win_avg,
        "lossAverages": loss_avg,
        "perGame": [
            {"n": i + 1, "result": g["result"], "win": g["win"], "map": g["map"],
             "goals": g["goals"], "shots": g["shots"], "saves": g["saves"],
             "avg_boost": g["avg_boost"], "double_commits": g["double_commits"],
             "air_time_pct": g["air_time_pct"]}
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
