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

## WIN replay (match.json)
```json
{win_json}
```

## LOSS replay (match.json)
```json
{loss_json}
```

## Training resources you may reference
{resources}

## Your task
Analyse the WIN vs the LOSS, find the 1-2 recurring weaknesses that show up in BOTH,
and build a plan that bridges {current_rank} -> {target_rank} on {gamemode}, scaled to
{mins} min/day. {platform_guidance}

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


def generate_coaching_plan(
    profile: dict,
    win_replay,
    loss_replay,
    stats: Optional[dict],
    api_key: str,
) -> dict:
    """Call Claude and return a validated PLAN dict (meta is filled deterministically)."""
    import anthropic
    from rlcoach.training_resources import (
        PLATFORM_OPTIONS, rank_gap as calc_gap, format_resources_for_prompt,
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

    prompt = _PROMPT.format(
        player=player, platform_label=plat["label"], gamemode=gamemode,
        current_rank=current_rank, target_rank=target_rank, gap=gap, mmr_str=mmr_str,
        mins=mins, days=days, duo=duo, freestyle=freestyle,
        win_json=_rj(win_replay), loss_json=_rj(loss_replay),
        resources=format_resources_for_prompt(platform, current_rank),
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
    return plan
