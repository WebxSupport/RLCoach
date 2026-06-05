"""
Claude Sonnet 4.6 coaching analyst.

Takes pre-computed match data + extended metrics and produces:
  1. A filled MATCH object (JSON) to inject into the HTML dashboard template.
  2. A complete HTML dashboard string ready to save as dashboard.html.

Claude does NOT have access to raw frame data — it receives structured aggregates.
All heavy computation happens in extended_metrics.py before this module is called.
"""
from __future__ import annotations
import json
import logging
import re
from pathlib import Path
from typing import Optional

log = logging.getLogger(__name__)

MODEL = "claude-sonnet-4-6"
MAX_TOKENS = 8192
TEMPLATE_PATH = Path(__file__).parent.parent / "static" / "dashboard_template.html"

# ── prompt building ────────────────────────────────────────────────────────────

_SYSTEM = """You are a Grand Champion-level Rocket League coach and data analyst.
You receive pre-computed match telemetry and produce a structured coaching analysis.
Return ONLY a single JSON code block (```json ... ```) containing the MATCH object.
No commentary outside the code block. The JSON must be valid and complete."""

_PROMPT_TEMPLATE = """
# Rocket League Match Analysis

## Pre-Computed Match Data

### match.json (structured summary)
```json
{match_json}
```

### Extended frame metrics
```json
{extended_json}
```

## Your Task

Produce a thorough, evidence-based coaching analysis using the data above.
Every claim must trace back to the numbers — cite metrics, timestamps, players by name.

### Coaching framework (apply these as the rubric)
- **Rotation**: One goes, one covers. When teammate commits, you hold back-post.
  The commit test: "If I lose this, is the net open?" If yes → shadow/delay.
- **Ballchase Index thresholds**: <5% disciplined · 5-10% loose · >10% chronic.
  A high index that coincides with goals conceded is the priority fix.
- **Boost economy**: Starvation >12% is a red flag. Route small pads on rotation.
- **Ball security**: Dangerous giveaways (own-half touch straight to opponent) feed counters.
- **Net coverage**: Concedes cluster in the coverage gaps, not evenly.
- **Kickoffs**: Second man should hold back unless confident; over-cheating opens counter.
- **Air vs ground**: each player has `air` (air_time_pct / high_air_pct / avg_height). Flag a player
  who is too ground-dominant (rarely contests in the air, low air %) OR over-committing to the air
  and whiffing. Compare the user to the lobby — being out-aerialled is a common rank ceiling.

### Extra analysis lenses (CARL2-style — apply where the data supports it)
- **Turnovers & follow-ups**: dangerous giveaways feeding the opponent (use the giveaway/touch data);
  note whether the user follows up their own shots or abandons them.
- **Pre-goal sequence**: for each conceded goal use the goal-window data (double_commit_pct,
  nearest_defender_dist, net_open, ball_speed) to reconstruct the 6s before it — was it shape,
  a turnover, a lost challenge, or a genuinely good shot?
- **Outlier detection**: explicitly call out the single biggest statistical outlier (good or bad)
  in the user's game vs the rest of the lobby — that's usually the highest-leverage takeaway.
- **Possession & pressure**: tie possession % and net-coverage gaps to where goals actually happened.

### Fault taxonomy for conceded goals (assign exactly ONE primary cause)
- `dc` — Double-commit / open net (both defenders forward, net undefended)
- `turnover` — Giveaway handed the opponent the goal
- `individual` — Defender was there, got beaten by a good touch / mechanical play
- `shot` — Well-positioned defender beaten by genuine shot quality (no fault)

### Player rating formula (clamp each component 0-100, then weighted sum)
ATT  = clamp(16*goals + 9*assists + 0.3*conv_pct + 1.5*shots, 0, 100)
DEF  = clamp(40 + 11*saves - 9*goals_at_fault, 0, 100)
POS  = clamp(1.05 * goalside_pct, 0, 100)
BST  = clamp(100 - 3.2*starve_pct + 1.2*(avgBoost-45), 0, 100)
ROT  = clamp(100 - 9*ballchase_index - 8*shared_dc_penalty, 0, 100)
SEC  = clamp(100 - 200*(giveaway_proxy/max(touches,1)), 0, 100)
overall = 0.22*ATT + 0.18*DEF + 0.15*POS + 0.15*BST + 0.18*ROT + 0.12*SEC

Use touch_proxy for touches. Use 0 for giveaway_proxy (touch detection is limited).
shared_dc_penalty = (double_commit_events_involving_player) / 3.

## Required MATCH Object Schema

Return a JSON code block with EXACTLY this structure (all fields required):

```json
{{
  "meta": {{
    "map": "string — clean map name",
    "mode": "string — e.g. 2v2",
    "playlist": "string",
    "date": "YYYY-MM-DD",
    "durationS": number,
    "teamAName": "Blue",
    "teamBName": "Orange"
  }},
  "result": {{ "win": boolean, "a": number, "b": number }},
  "teamMetrics": {{
    "possession": {{ "A": number, "B": number }},
    "netCoverage": {{ "A": number, "B": number }}
  }},
  "summary": {{
    "headline": "string ≤200 chars — single biggest reason win/loss + top issue",
    "keyFindings": ["string", "string", "string", "string", "string"],
    "topFixes": [
      {{ "title": "string", "detail": "string", "metric": "string — current vs target" }},
      {{ "title": "string", "detail": "string", "metric": "string" }},
      {{ "title": "string", "detail": "string", "metric": "string" }}
    ]
  }},
  "kpis": [
    {{ "label": "Result", "value": "A-B", "sub": "Win or Loss", "tone": "good or bad" }},
    {{ "label": "My rating", "value": "##.#", "sub": "/ 100", "tone": "good" }},
    {{ "label": "Double-commits", "value": "##", "sub": "N → open-net goals", "tone": "bad or warn" }},
    {{ "label": "Possession", "value": "##%", "sub": "A% vs B%", "tone": "" }},
    {{ "label": "Net covered", "value": "##%", "sub": "one-line note", "tone": "warn or good" }}
  ],
  "players": [
    {{
      "name": "string",
      "team": "A or B",
      "isMe": boolean,
      "role": "string — 2-3 word label",
      "rating": {{
        "overall": number,
        "ATT": number, "DEF": number, "POS": number,
        "BST": number, "ROT": number, "SEC": number
      }},
      "core": {{
        "goals": number, "shots": number, "assists": number,
        "saves": number, "score": number
      }},
      "d": {{
        "conv": "##% or —",
        "def": number, "neut": number, "off": number,
        "avgBoost": number, "starved": number, "zero": number,
        "goalside": number,
        "ballchase": number, "longest": number,
        "touches": number, "giveaways": number
      }},
      "summary": "string — 4-6 sentences: identity, 3-5 strengths+weaknesses with numbers, single habit",
      "strengths": ["string", "string", "string"],
      "weaknesses": ["string", "string", "string"],
      "habit": "string — single most impactful habit change"
    }}
  ],
  "goals": [
    {{
      "t": number,
      "team": "A or B",
      "score": [number, number],
      "scorer": "string",
      "assist": "string or null",
      "conceded": boolean,
      "faultType": "dc | turnover | individual | shot",
      "fault": "string or null — name the player at fault, or null if no fault",
      "reason": "string — one detailed sentence explaining the goal"
    }}
  ],
  "kickoffs": [
    {{ "t": number, "result": "won | lost | neutral", "concededWithinS": number_or_null }}
  ],
  "doubleCommits": [
    {{ "t": number, "d": number }}
  ],
  "ballchaseTimeline": {{
    "labels": [0, 30, 60, 90, 120, 150, 180, 210, 240, 270],
    "series": [
      {{
        "name": "string",
        "team": "A or B",
        "values": [number, number, number, number, number, number, number, number, number, number]
      }}
    ]
  }}
}}
```

### Additional notes
- Map team A = the tracked player's team (isMe=true player), team B = opponents.
- For `d.zero`: set to same value as `d.starved` (time_at_zero in seconds as pct equivalent).
- For `d.giveaways`: use 0 (raw touch detection unavailable; SEC formula handles this).
- For goals: `t` is match_seconds = 300 - seconds_remaining at the goal frame (from match.json moments or goal events).
- `score` array is [team_A_cumulative, team_B_cumulative] at that point.
- Double-commits: use the double_commit_events list from match.json; each entry needs t (start time) and d (duration_s).
- Ballchase timeline: 10 values per player, one per 30-second bucket 0-270s. Use extended metrics data where available; estimate from ballchase index if per-30s not in data.
- Be honest about opponents; explicitly say what the highest-rated player does that the user's team doesn't.
"""


# ── Claude call ────────────────────────────────────────────────────────────────

def _extract_json(text: str) -> Optional[dict]:
    """Extract the first JSON code block from Claude's response."""
    # Try fenced block first
    m = re.search(r"```json\s*([\s\S]+?)\s*```", text, re.IGNORECASE)
    if m:
        try:
            return json.loads(m.group(1))
        except json.JSONDecodeError as e:
            log.warning("JSON parse error in fenced block: %s", e)

    # Fallback: try to find the outermost { ... }
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


def _inject_into_template(template_html: str, match_obj: dict) -> str:
    """Replace the MATCH object in the template with the Claude-generated one."""
    marker_start = "const MATCH = {"
    marker_end = "/* ============================  END OF EDITABLE DATA  ================================= */"

    si = template_html.find(marker_start)
    ei = template_html.find(marker_end)
    if si == -1 or ei == -1:
        raise ValueError("Could not find MATCH markers in template")

    before = template_html[:si]
    after = template_html[ei:]  # includes the marker itself
    injected = json.dumps(match_obj, indent=2, ensure_ascii=False)
    return before + f"const MATCH = {injected};\n" + after


def analyse_match(
    match_json: dict,
    extended_metrics: dict,
    api_key: str,
) -> str:
    """
    Call Claude Sonnet 4.6 to analyse the match.
    Returns a complete HTML dashboard string.
    Raises on failure.
    """
    import anthropic

    template_html = TEMPLATE_PATH.read_text(encoding="utf-8")

    prompt = _PROMPT_TEMPLATE.format(
        match_json=json.dumps(match_json, indent=2, ensure_ascii=False),
        extended_json=json.dumps(extended_metrics, indent=2, ensure_ascii=False),
    )

    client = anthropic.Anthropic(api_key=api_key)
    log.info("Calling Claude %s for match analysis…", MODEL)

    message = client.messages.create(
        model=MODEL,
        max_tokens=MAX_TOKENS,
        system=_SYSTEM,
        messages=[{"role": "user", "content": prompt}],
    )

    response_text = message.content[0].text
    log.info("Claude response: %d chars, stop=%s", len(response_text), message.stop_reason)

    match_obj = _extract_json(response_text)
    if match_obj is None:
        raise ValueError("Could not extract valid JSON from Claude response")

    html = _inject_into_template(template_html, match_obj)
    return html
