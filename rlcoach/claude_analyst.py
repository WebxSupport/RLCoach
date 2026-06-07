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
No commentary outside the code block. The JSON must be valid and complete.

PLAIN-ENGLISH VOICE — every word the player reads must be plain English:
- NEVER print raw unreal-units distances like "2700uu" or "1800-2500uu". Say distances as a
  fraction of the pitch instead ("about a third of the pitch upfield", "a passing-lane gap"),
  or qualitatively ("too far to follow up", "right on top of his teammate").
- NEVER expose internal field/metric names (e.g. support_too_far_pct, challenge_win_pct,
  own_half_pct, last_man_pct). Use natural phrases: "you supported too far back 60% of the time",
  "you won 2 of 15 challenges", "you were the last defender about half the match".
- Percentages, counts, goals, MMR and timestamps are fine as-is. Keep it readable, not jargon."""

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
- **Speed**: each player has `speed` (supersonic_pct / boost_speed_pct / cruise_pct / slow_pct / avg_speed).
  Elite players spend >20% of live play at supersonic. A player spending >40% slow is likely over-dribbling
  or not maintaining speed on rotations. Compare supersonic_pct across the lobby.
- **Recovery**: each player has `recovery` (avg_recovery_s / slow_recoveries). After a hit, taking
  >2.5s to return to the defensive half suggests chasing the ball rather than rotating. Slow recoveries
  (>3s threshold) cluster around double-commit events — check if the timing correlates.

### Extra analysis lenses (CARL2-style — apply where the data supports it)
- **Turnovers & follow-ups**: dangerous giveaways feeding the opponent (use the giveaway/touch data);
  note whether the user follows up their own shots or abandons them.
- **Pre-goal sequence**: for each conceded goal use the goal-window data (double_commit_pct,
  nearest_defender_dist, net_open, ball_speed) to reconstruct the 6s before it — was it shape,
  a turnover, a lost challenge, or a genuinely good shot?
- **Outlier detection**: explicitly call out the single biggest statistical outlier (good or bad)
  in the user's game vs the rest of the lobby — that's usually the highest-leverage takeaway.
- **Possession & pressure**: tie possession % and net-coverage gaps to where goals actually happened.

### Pre-computed framework analysis (match.json → "analysis")
The match.json above may contain an "analysis" object — use it as ground truth:
- `positioning` — per-player coverage zones (near/back post, goal line, midfield, backboard),
  support-distance distribution (too close/optimal/too far vs the ideal passing-lane gap),
  distance-to-play, and last-man (time as last defender, risky pushes).
- `touch` — touch quality (controlled/pass/shot/clear/challenge/panic + positive/neutral/negative),
  possession chains with end reasons, challenge win/loss, per-player giveaways.
- `shooting` — per-shot xG and per-player shots/goals/xG/conversion + a finishing verdict
  (clinical / as expected / cold). xG ≫ goals = a FINISHING problem; few/low-xG shots = a
  CHANCE-CREATION problem. Say which.
- `patterns` — the tracked player's ranked habits, each ALREADY in Evidence→Pattern→Consequence→Fix
  form with a target metric. These are the highest-leverage findings.
Your `summary.topFixes`, `keyFindings`, and each player's `weaknesses`/`habit` MUST be grounded in
`analysis.patterns` and the positioning/touch/shooting numbers. Cite the real figures; do not invent
issues the data doesn't support.

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
        "touches": number, "giveaways": number,
        "supersonic": number,
        "airPct": number,
        "avgRecovery": number
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
  }},
  "patterns": [
    {{
      "category": "rotation | positioning | possession | challenge | boost | defense",
      "severity": "critical | major | minor",
      "title": "string — short habit name",
      "evidence": "string — the numbers that prove it",
      "consequence": "string — what it cost THIS match",
      "fix": "string — the concrete behavioural change",
      "metric": "string — current → target"
    }}
  ],
  "shooting": {{
    "teamA": {{ "shots": number, "goals": number, "xg": number }},
    "teamB": {{ "shots": number, "goals": number, "xg": number }},
    "me": {{ "shots": number, "goals": number, "xg": number, "finishing": "clinical | as expected | cold" }}
  }}
}}
```

### Additional notes
- Map team A = the tracked player's team (isMe=true player), team B = opponents.
- For `d.zero`: set to same value as `d.starved` (time_at_zero in seconds as pct equivalent).
- For `d.giveaways`: use 0 (raw touch detection unavailable; SEC formula handles this).
- For `d.supersonic`: take from match.json players[i].speed.supersonic_pct; use 0 if absent.
- For `d.airPct`: take from match.json players[i].air.air_time_pct; use 0 if absent.
- For `d.avgRecovery`: take from match.json players[i].recovery.avg_recovery_s; use 0 if absent.
- For goals: `t` is match_seconds = 300 - seconds_remaining at the goal frame (from match.json moments or goal events).
- `score` array is [team_A_cumulative, team_B_cumulative] at that point.
- Double-commits: use the double_commit_events list from match.json; each entry needs t (start time) and d (duration_s).
- Ballchase timeline: 10 values per player, one per 30-second bucket 0-270s. Use extended metrics data where available; estimate from ballchase index if per-30s not in data.
- Be honest about opponents; explicitly say what the highest-rated player does that the user's team doesn't.
- For `patterns`: take the tracked player's ranked habits from `analysis.patterns` (refine the wording, keep the figures and the Evidence→Consequence→Fix structure). 3–6 items, highest-impact first.
- For `shooting`: from `analysis.shooting` (team A = tracked player's team; "me" = isMe player).
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
    base_dir=None,
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

    # Merge computed (non-AI) visuals: positioning heatmaps
    if isinstance(extended_metrics, dict) and extended_metrics.get("field_maps"):
        match_obj["fieldMaps"] = extended_metrics["field_maps"]

    # Inject the computed framework analysis DETERMINISTICALLY (like fieldMaps) so the
    # Habits + Shooting panels always populate from real numbers — never depend on the
    # model echoing them back. Falls back to whatever the model produced if absent.
    _inject_analysis_panels(match_obj, match_json, base_dir)

    html = _inject_into_template(template_html, match_obj)
    return html


def _inject_analysis_panels(match_obj: dict, match_json: dict, base_dir=None) -> None:
    """Map match_json['analysis'] (positioning/touch/shooting/patterns) into the
    MATCH object shapes the dashboard template expects (patterns[], shooting{})."""
    analysis = (match_json or {}).get("analysis") or {}
    if not analysis:
        return

    pats = (analysis.get("patterns") or {}).get("patterns")
    if pats:
        from .renderer import diagram_data_uri
        out_pats = []
        for p in pats:
            entry = {k: p.get(k) for k in
                     ("category", "severity", "title", "evidence", "consequence", "fix", "metric")}
            uri = diagram_data_uri(base_dir, p.get("diagram_path"))
            if uri:
                entry["diagram"] = uri
            out_pats.append(entry)
        match_obj["patterns"] = out_pats

    rot = analysis.get("rotation")
    if rot and rot.get("opportunities"):
        match_obj["rotation"] = rot

    sh = analysis.get("shooting") or {}
    team = sh.get("team") or {}
    if team:
        my_team = (match_json.get("result") or {}).get("player_team", "blue")
        opp = "orange" if my_team == "blue" else "blue"
        me_sh = next((v for v in (sh.get("per_player") or {}).values()
                      if isinstance(v, dict) and v.get("is_me")), None)
        match_obj["shooting"] = {
            "teamA": team.get(my_team, {}),
            "teamB": team.get(opp, {}),
            "me": ({"shots": me_sh.get("shots"), "goals": me_sh.get("goals"),
                    "xg": me_sh.get("xg"), "finishing": me_sh.get("finishing")}
                   if me_sh else {}),
        }

    def _me_of(section):
        return next((v for v in (section or {}).values()
                     if isinstance(v, dict) and v.get("is_me")), None)

    # Touch quality + challenges (tracked player + match-level)
    t = analysis.get("touch") or {}
    if t:
        match_obj["touch"] = {
            "me": _me_of(t.get("per_player")),
            "challenges": t.get("challenges"),
            "possession": t.get("team_possession"),
            "possessions": t.get("possessions"),
        }

    # Advanced execution: boost economy + mechanical recovery (tracked player)
    adv = analysis.get("advanced") or {}
    be = _me_of((adv.get("boost_economy") or {}).get("per_player"))
    mr = _me_of((adv.get("mechanical_recovery") or {}).get("per_player"))
    if be or mr:
        match_obj["advanced"] = {"boost": be, "recovery": mr}

    # Defensive depth (tracked player's last-man profile)
    me_pos = _me_of(analysis.get("positioning"))
    if me_pos and me_pos.get("last_man"):
        match_obj["lastMan"] = me_pos["last_man"]
