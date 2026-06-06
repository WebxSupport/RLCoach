"""
Coaching plan generator — structured output.

Takes player profile + 1 WIN + 1 LOSS replay analysis + live stats, and asks
Claude Sonnet 4.6 to return a structured PLAN object (JSON). The web app renders
that into an interactive training dashboard and seeds a progress tracker from it.
"""
from __future__ import annotations
import json
import logging
import re
from datetime import date
from typing import Optional

log = logging.getLogger(__name__)

MODEL = "claude-sonnet-4-6"
MAX_TOKENS = 7000

_SYSTEM = """You are an elite Rocket League coach who builds structured, data-driven training plans.
You return ONLY a single JSON object inside a ```json code block — no prose outside it.
The JSON must be valid and complete, matching the requested schema exactly."""

_PROMPT = """
# Build a structured Rocket League training plan

## Player
- Name: {player}
- Platform: {platform_label}
- Playlist to climb: {gamemode}
- Current rank: {current_rank}{mmr_str}
- Target rank: {target_rank}  (gap: {gap} tiers)
- Time budget: {mins} min/day, {days} days/week
- Duo partner: {duo}
- Freestyle interest: {freestyle}

{series_block}

## WIN replay (match.json) — illustrative single game
```json
{win_json}
```

## LOSS replay (match.json)
```json
{loss_json}
```

## Computed framework analysis (authoritative — derived from frames; do not contradict)
For each replay: the tracked player's ranked habit `patterns` (already Evidence→Consequence→Fix
with target metrics), `shooting` (xG vs goals — finishing vs chance creation), and the player's
`positioning` (coverage zones, support distance) + `touch` (giveaways, possession) summary.
### WIN
{win_analysis}
### LOSS
{loss_analysis}

## Training resources (context)
{resources}

## {catalog}

## Your task
Analyse the WIN vs the LOSS, find the 1-2 recurring weaknesses that show up in BOTH,
and build a plan that bridges {current_rank} -> {target_rank} on {gamemode}, scaled to
{mins} min/day. {platform_guidance}

Also weigh AIR vs GROUND balance — each player has an `air` field
(air_time_pct / high_air_pct / avg_height). If the user is very ground-dominant (low air %),
or over-committing to the air and missing, call it out and target it with the plan.

Return EXACTLY this JSON shape (fill every field; arrays must not be empty):

```json
{{
  "focus": "one sentence — the single highest-impact priority this week, from the replays",
  "headline": "2-3 sentences: where they are, the main thing holding them back, the path up",
  "winLoss": {{
    "win":  {{ "label": "Map — W#-#", "worked": ["2-4 specific things, cite numbers"], "leaked": ["1-3 things that still slipped"] }},
    "loss": {{ "label": "Map — L#-#", "causes": ["2-4 root causes, cite numbers"], "kept": ["1-2 things that still went well"] }}
  }},
  "strengths": [ {{ "title": "short", "detail": "one line with a number" }} ],
  "weaknesses": [ {{ "title": "short", "detail": "one line with a number", "priority": true }} ],
  "week": [
    {{ "day": "Mon", "theme": "short theme", "blocks": [ {{ "name": "task", "mins": 0, "kind": "warmup|skill|application|freestyle|rest" }} ] }}
  ],
  "drills": [
    {{ "id": "kebab-case-id", "name": "drill name", "kind": "pack|workshop|freeplay",
       "resource": "training-pack code OR 'Workshop: <name> (ID ...)' OR 'Freeplay'",
       "goal": "a concrete, measurable target", "movesMetric": "what it improves" }}
  ],
  "tracker": {{
    "targetMmr": 0,
    "weeklyTargets": [ {{ "id": "kebab-id", "label": "metric to move", "from": 0, "to": 0, "unit": "" }} ]
  }}
}}
```

Rules:
- `week` MUST have exactly 7 entries (Mon-Sun). Block minutes per active day should sum to ~{mins}.
  Use a "rest" kind for rest days (theme "Rest", blocks can be a single light task or empty).
- `drills` = 4-7 concrete items. Use REAL training-pack codes / workshop maps from the resources
  for PC; pack codes / freeplay only for console.
- CRITICAL — NEVER invent, rename, or embellish a training pack, workshop map, or pack code. Use
  ONLY entries from the ALLOWED DRILLS list above, copying the name and resource VERBATIM. If a real
  resource doesn't fit, use a `freeplay` drill instead. Made-up maps/codes will be rejected.
- IMPORTANT: every specific drill you put in a `week` block must ALSO appear in `drills`, and the
  block's `name` must be the EXACT same text as that drill's `name` (so they can be cross-linked
  day-by-day). Generic blocks like "Ranked + review" or "Warm-up freeplay" don't need a drill entry.
- `tracker.targetMmr`: estimate the MMR for {target_rank} (roughly current MMR + {gap}x30 if unknown).
- `tracker.weeklyTargets`: 2-3 measurable things from the weaknesses (e.g. double-commits 32->10).
- Be specific and honest. Tie everything to the replay numbers.
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


def _habits_from(r) -> list:
    if r is None:
        return []
    a = (getattr(r, "match_json", None) or {}).get("analysis") or {}
    return (a.get("patterns") or {}).get("patterns") or []


def _collect_habits(win_replay, loss_replay) -> list:
    """Top recurring habits across the win+loss replays (losses first), deduped."""
    rank = {"critical": 0, "major": 1, "minor": 2}
    cand = _habits_from(loss_replay) + _habits_from(win_replay)
    cand.sort(key=lambda p: rank.get((p.get("severity") or "minor").lower(), 3))
    seen, out = set(), []
    for p in cand:
        key = (p.get("title") or "").lower()
        if not key or key in seen:
            continue
        seen.add(key)
        out.append({k: p.get(k) for k in
                    ("category", "severity", "title", "evidence", "consequence", "fix", "metric")})
        if len(out) >= 5:
            break
    return out


def _collect_trends(series) -> list:
    """Win-vs-loss deltas for the new framework metrics (only where both present)."""
    if not series:
        return []
    wa = series.get("winAverages") or {}
    la = series.get("lossAverages") or {}
    specs = [
        ("rotation_score", "Rotation score", "high"),
        ("poor_rotation_pct", "Poor rotations %", "low"),
        ("challenge_win_pct", "Challenge win %", "high"),
        ("support_too_close_pct", "Support too close %", "low"),
        ("back_post_pct", "Back-post coverage %", "high"),
        ("touch_positive_pct", "Positive touches %", "high"),
        ("giveaways", "Giveaways / game", "low"),
        ("xg", "Expected goals", "high"),
    ]
    out = []
    for key, label, better in specs:
        wv, lv = wa.get(key), la.get(key)
        if wv is None or lv is None:
            continue
        out.append({"metric": label, "win": wv, "loss": lv, "better": better})
    return out[:5]


def generate_coaching_plan(
    profile: dict,
    win_replay,
    loss_replay,
    stats: Optional[dict],
    api_key: str,
    series: Optional[dict] = None,
) -> dict:
    """Call Claude and return a validated PLAN dict (meta is filled deterministically)."""
    import anthropic
    from rlcoach.training_resources import (
        PLATFORM_OPTIONS, rank_gap as calc_gap, format_resources_for_prompt,
        format_drill_catalog, reconcile_drills,
    )

    platform = profile.get("platform", "steam")
    plat = next((p for p in PLATFORM_OPTIONS if p["value"] == platform), PLATFORM_OPTIONS[0])
    has_bm = plat["has_bakkesmod"]
    platform_guidance = (
        "Use training-pack codes, Steam Workshop maps and BakkesMod where useful."
        if has_bm else
        "Console player: use ONLY official in-game training packs (give codes) and freeplay — NO workshop/BakkesMod."
    )

    current_rank = profile.get("current_rank") or (stats or {}).get("rank") or "Diamond I"
    target_rank = profile.get("target_rank") or "Champion I"
    gap = calc_gap(current_rank, target_rank)
    gamemode = profile.get("gamemode", "2v2")
    mins = profile.get("mins_per_day", 60)
    days = profile.get("days_per_week", 5)
    duo = profile.get("duo_partner") or "None"
    freestyle = "Yes" if profile.get("freestyle") else "No"
    player = profile.get("display_name") or "Player"
    cur_mmr = (stats or {}).get("mmr_estimate")
    mmr_str = f" (~{cur_mmr} MMR)" if cur_mmr else ""

    def _rj(r):
        if r is None:
            return '{"error":"no replay available"}'
        return json.dumps(r.match_json, ensure_ascii=False)[:7000]

    def _analysis_brief(r):
        """Compact, guaranteed-included slice of the persisted framework analysis
        for the tracked player (the full block is truncated away by _rj)."""
        if r is None:
            return "(no replay)"
        a = (getattr(r, "match_json", None) or {}).get("analysis") or {}
        if not a:
            return "(no computed analysis — older match)"
        def _me(section):
            return next((v for v in (a.get(section, {}) or {}).values()
                         if isinstance(v, dict) and v.get("is_me")), None)
        pats = (a.get("patterns") or {}).get("patterns", [])
        sh = a.get("shooting") or {}
        out = {
            "patterns": [{k: p.get(k) for k in ("title", "severity", "evidence", "consequence", "fix", "metric")}
                         for p in pats],
            "shooting": {"team": sh.get("team"),
                         "me": next((v for v in (sh.get("per_player") or {}).values() if v.get("is_me")), None)},
            "positioning_me": _me("positioning"),
            "touch_me": _me("touch"),
        }
        return json.dumps(out, ensure_ascii=False)[:4500]

    # Long-term trends across many games (preferred signal over single matches)
    if series and series.get("games", 0) >= 3:
        series_block = (
            f"## LONG-TERM TRENDS — last {series['games']} ranked {gamemode} games "
            f"({series.get('wins',0)}W-{series.get('losses',0)}L)\n"
            "Base the plan PRIMARILY on these multi-game patterns — especially where the player's\n"
            "WIN averages differ from their LOSS averages (that gap is what actually decides games).\n"
            "Use the single win/loss replays below only as concrete illustrations.\n"
            "```json\n"
            + json.dumps({k: series[k] for k in ("averages", "winAverages", "lossAverages", "perGame")
                          if k in series}, ensure_ascii=False)[:5000]
            + "\n```\n"
        )
    else:
        series_block = ("## LONG-TERM TRENDS\n(Not enough games yet — base the plan on the win/loss "
                        "replays below.)\n")

    prompt = _PROMPT.format(
        player=player, platform_label=plat["label"], gamemode=gamemode,
        current_rank=current_rank, target_rank=target_rank, gap=gap, mmr_str=mmr_str,
        mins=mins, days=days, duo=duo, freestyle=freestyle,
        series_block=series_block,
        win_json=_rj(win_replay), loss_json=_rj(loss_replay),
        win_analysis=_analysis_brief(win_replay), loss_analysis=_analysis_brief(loss_replay),
        resources=format_resources_for_prompt(platform, current_rank),
        catalog=format_drill_catalog(platform),
        platform_guidance=platform_guidance,
    )

    client = anthropic.Anthropic(api_key=api_key)
    log.info("Generating structured coaching plan via %s...", MODEL)
    msg = client.messages.create(
        model=MODEL, max_tokens=MAX_TOKENS, system=_SYSTEM,
        messages=[{"role": "user", "content": prompt}],
    )
    plan = _extract_json(msg.content[0].text)
    if plan is None:
        raise ValueError("Could not parse the coaching plan JSON from Claude")

    # Validate drills against the real catalog — strip/normalise any hallucinations
    plan["drills"] = reconcile_drills(plan.get("drills"), platform)

    est_target_mmr = (plan.get("tracker") or {}).get("targetMmr") or (
        (cur_mmr + gap * 30) if cur_mmr else None
    )
    plan["meta"] = {
        "player": player,
        "platform": platform,
        "platformLabel": plat["label"],
        "hasBakkesmod": has_bm,
        "gamemode": gamemode,
        "currentRank": current_rank,
        "targetRank": target_rank,
        "currentMmr": cur_mmr,
        "targetMmr": est_target_mmr,
        "minsPerDay": mins,
        "daysPerWeek": days,
        "rankGap": gap,
        "generated": date.today().isoformat(),
    }
    plan.setdefault("tracker", {})
    plan["tracker"]["targetMmr"] = est_target_mmr

    # Deterministic visuals for the plan's Habits panel (computed, not model-authored)
    plan["habits"] = _collect_habits(win_replay, loss_replay)
    plan["trends"] = _collect_trends(series)

    # Curated tutorial videos matched to the player's habits + weaknesses + focus
    try:
        from rlcoach.learning_resources import select_resources
        plan["resources"] = select_resources(
            habits=plan["habits"], weaknesses=plan.get("weaknesses"),
            focus=plan.get("focus", ""), drills=plan.get("drills"))
    except Exception as e:
        log.info("resource selection skipped: %s", e)
        plan["resources"] = []

    # Start the weekly plan on the day it's generated (not always Monday). The model
    # returns a 7-day progression; we anchor day 1 to today and label the rest forward.
    try:
        _DOW = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
        ti = date.today().weekday()
        for i, d in enumerate(plan.get("week") or []):
            if isinstance(d, dict):
                d["day"] = _DOW[(ti + i) % 7]
    except Exception:
        pass
    return plan
