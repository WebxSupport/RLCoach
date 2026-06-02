"""
Coaching plan generator.

Takes player profile + 1 WIN + 1 LOSS replay analysis → calls Claude Sonnet 4.6
→ produces coaching.md (a personalised, platform-aware, rank-scaled training plan).
"""
from __future__ import annotations
import json
import logging
from datetime import date
from pathlib import Path
from typing import Optional

log = logging.getLogger(__name__)

MODEL = "claude-sonnet-4-6"
MAX_TOKENS = 6000

_SYSTEM = """You are an expert Rocket League coach. You produce personalised, data-driven coaching plans.
Return ONLY the coaching.md markdown document. No preamble, no code blocks around it — just raw markdown."""

_PROMPT_TEMPLATE = """
# Generate a Personalised Rocket League Coaching Plan

## Player Profile
- **Gamer tag / display name:** {display_name}
- **Platform:** {platform_label}
- **Training availability:** {mins_per_day} minutes/day, {days_per_week} days/week
- **Ranked playlist to climb:** {gamemode}
- **Current rank:** {current_rank}
- **Target rank:** {target_rank}
- **Rank gap:** {rank_gap} tiers
- **Duo partner:** {duo_partner}
- **Freestyle / tricks interest:** {freestyle}

## Current Stats
{stats_section}

## WIN Replay Analysis
**{win_map} — {win_result} — {win_duration}s**
```json
{win_json}
```

## LOSS Replay Analysis
**{loss_map} — {loss_result} — {loss_duration}s**
```json
{loss_json}
```

## Training Resources Available
{resources_section}

---

## Your Task

Analyse the two replays (WIN vs LOSS) and produce a **coaching.md** document.

### Analysis requirements
1. **Win vs loss comparison:** What did the player do better in the win? What collapsed in the loss?
2. **Identify 1-2 primary recurring weaknesses** that appear in BOTH replays — these become the week's priority.
3. **Identify 1-2 genuine strengths** so the plan builds on them.
4. Focus specifically on the **{gamemode}** playlist context (rotation roles, spacing, communication if duo).

### Plan requirements
- **7-day split** with daily blocks that sum to exactly {mins_per_day} minutes.
- **Scale content to the rank gap:** a {rank_gap}-tier gap means {rank_guidance}.
- **This week's focus** must be derived directly from the replay weaknesses, not generic advice.
- **Every day** should have a specific drill/task, not "play ranked games" alone.
- **Platform awareness:** {platform_guidance}
- If duo partner is set ({duo_partner}), include one joint session per week focused on communication and staggered challenges.
- If freestyle is enabled, include one lighter technical/creative session.

### Output format — produce this exact markdown structure:

```
# RL Coaching Plan — {display_name} → {target_rank}
Generated: {today} | Playlist: {gamemode} | Budget: {mins_per_day} min/day, {days_per_week} days

## This Week's Priority
> [One-sentence priority derived from replay patterns — specific, not generic]

---

## 1. Current Stats
| Playlist | Rank | MMR | Source |
|----------|------|-----|--------|
| {gamemode} | [rank] | [mmr or N/A] | [source] |

---

## 2. Replay Analysis

### Win — {win_map} ({win_result})
**What worked:**
- [3-4 specific bullet points with data citations]

**What still leaked:**
- [2-3 specific bullet points]

### Loss — {loss_map} ({loss_result})
**Root causes:**
- [3-4 specific bullet points with data citations from the replay JSON]

**Under pressure your strongest habit was:**
- [1 line]

### Recurring patterns (appear in both replays)
1. **[Pattern 1]** — [evidence from both replays, specific metrics]
2. **[Pattern 2 if applicable]** — [evidence]

---

## 3. 7-Day Training Plan ({mins_per_day} min/day)

| Day | Theme | Blocks (times sum to {mins_per_day} min) |
|-----|-------|------------------------------------------|
| Mon | [theme] | [block 1 Xmin] · [block 2 Xmin] · [block 3 Xmin] |
| Tue | [theme] | ... |
| Wed | [theme] | ... |
| Thu | [theme] | ... |
| Fri | [theme] | ... |
| Sat | [theme] | ... |
| Sun | [theme] | ... |

### Drill Details

**[Drill Name]** (Day X, Y min)
- What: [specific description]
- Resource: [training pack code / workshop map / freeplay challenge]
- Track: [measurable outcome — e.g. "complete rings map without touching walls 3 times"]

[Repeat for each unique drill in the plan]

---

## 4. Progress Tracking
- **This week's number to move:** [the one metric — e.g. "reduce double-commits from N to < N/2"]
- **Weekly MMR check:** note your MMR each Sunday
- **Replay review:** after each session block that includes ranked play, watch one replay focusing solely on [the week's priority]

---

## 5. Next Generation Triggers
Re-generate this plan when:
- You reach {target_rank} in {gamemode}
- You've played 15+ ranked games since this plan was made
- One of the recurring patterns has clearly improved (use that as a strength next time)
```
"""


def _build_stats_section(profile: dict, stats: Optional[dict]) -> str:
    if stats and stats.get("rank"):
        return (
            f"| {profile.get('gamemode','2v2')} | {stats['rank']} | "
            f"{stats.get('mmr_estimate', 'N/A')} | "
            f"{stats.get('source','psynet_api')} |"
        )
    rank = profile.get("current_rank") or "Unknown"
    return f"| {profile.get('gamemode','2v2')} | {rank} | N/A | self-reported |"


def _rank_gap_guidance(gap: int) -> str:
    if gap <= 3:
        return "small gap — polish existing skills, reduce mistakes, consistency over ceiling"
    if gap <= 8:
        return "moderate gap — one new mechanic per two weeks max, focus on decisions and rotation"
    return "large gap — fundamentals and decisions dominate, keep mechanics aspirational but not the daily focus"


def generate_coaching_plan(
    profile: dict,
    win_replay: Optional["SelectedReplay"],
    loss_replay: Optional["SelectedReplay"],
    stats: Optional[dict],
    api_key: str,
) -> str:
    """
    Call Claude Sonnet 4.6 to generate coaching.md.
    Returns the markdown string.
    """
    import anthropic
    from rlcoach.training_resources import (
        PLATFORM_OPTIONS, rank_gap as calc_gap, format_resources_for_prompt
    )

    platform = profile.get("platform", "steam")
    plat_info = next((p for p in PLATFORM_OPTIONS if p["value"] == platform), PLATFORM_OPTIONS[0])
    has_bakkesmod = plat_info["has_bakkesmod"]
    platform_guidance = (
        "Use training pack codes AND workshop maps AND BakkesMod plugins as appropriate."
        if has_bakkesmod else
        "Console player — use ONLY official in-game training packs (include pack codes). "
        "NO workshop maps, NO BakkesMod. Replace any PC-only resource with a freeplay challenge."
    )

    current_rank = profile.get("current_rank") or "Diamond I"
    target_rank = profile.get("target_rank") or "Champion I"
    gap = calc_gap(current_rank, target_rank)
    gamemode = profile.get("gamemode", "2v2")
    mins = profile.get("mins_per_day", 60)
    days = profile.get("days_per_week", 5)
    duo = profile.get("duo_partner") or "None"
    freestyle = "Yes" if profile.get("freestyle") else "No"
    display_name = profile.get("display_name") or "Player"

    def _replay_json_str(r: Optional["SelectedReplay"]) -> str:
        if r is None:
            return '{"error": "No replay available"}'
        return json.dumps(r.match_json, indent=2, ensure_ascii=False)[:8000]

    win_map = win_replay.map_display if win_replay else "N/A"
    win_result = win_replay.result_str if win_replay else "N/A"
    win_dur = str(round(win_replay.duration_s)) if win_replay else "N/A"
    loss_map = loss_replay.map_display if loss_replay else "N/A"
    loss_result = loss_replay.result_str if loss_replay else "N/A"
    loss_dur = str(round(loss_replay.duration_s)) if loss_replay else "N/A"

    resources = format_resources_for_prompt(platform, current_rank)
    stats_section = _build_stats_section(profile, stats)

    prompt = _PROMPT_TEMPLATE.format(
        display_name=display_name,
        platform_label=plat_info["label"],
        mins_per_day=mins,
        days_per_week=days,
        gamemode=gamemode,
        current_rank=current_rank,
        target_rank=target_rank,
        rank_gap=gap,
        duo_partner=duo,
        freestyle=freestyle,
        stats_section=stats_section,
        win_map=win_map,
        win_result=win_result,
        win_duration=win_dur,
        win_json=_replay_json_str(win_replay),
        loss_map=loss_map,
        loss_result=loss_result,
        loss_duration=loss_dur,
        loss_json=_replay_json_str(loss_replay),
        resources_section=resources,
        rank_guidance=_rank_gap_guidance(gap),
        platform_guidance=platform_guidance,
        today=date.today().isoformat(),
    )

    client = anthropic.Anthropic(api_key=api_key)
    log.info("Calling Claude %s to generate coaching plan…", MODEL)

    message = client.messages.create(
        model=MODEL,
        max_tokens=MAX_TOKENS,
        system=_SYSTEM,
        messages=[{"role": "user", "content": prompt}],
    )

    plan_md = message.content[0].text
    log.info("Coaching plan generated: %d chars", len(plan_md))
    return plan_md
