"""
FR6 — Write match.json (complete structured analysis) and match.md (LLM-friendly summary).
"""
import json
import logging
import re
from pathlib import Path

from .parser import ParsedReplay
from .metrics import MatchMetrics
from .events import Moment

log = logging.getLogger(__name__)

# ── Map name helpers ───────────────────────────────────────────────────────────

# Strip the trailing arena-type designator that Psyonix appends to every map name:
#   _P      — standard Soccar arena
#   _GRS_P  — grass/Farmstead variant
# We keep variant tags (Rainy, Dusk, Day, Lux …) because they're meaningful.
_ARENA_SUFFIX = re.compile(r"(_GRS)?_[Pp]$")


def _clean_map_name(raw: str) -> str:
    """
    Return a human-readable map name.

    Examples
    --------
    'Park_Rainy_P'       -> 'Park Rainy'
    'CHN_Stadium_Day_P'  -> 'CHN Stadium Day'
    'Farm_GRS_P'         -> 'Farm'
    'UtopiaStadium_Lux_P'-> 'UtopiaStadium Lux'
    'cs_p'               -> 'cs'
    'mall_day_p'         -> 'mall day'
    """
    name = _ARENA_SUFFIX.sub("", (raw or "Unknown").strip())
    return name.replace("_", " ").strip()


# ── Serialisation ─────────────────────────────────────────────────────────────

def _serialise(obj):
    """Recursively turn dataclass objects into plain dicts, skipping DataFrames."""
    if hasattr(obj, "__dataclass_fields__"):
        result = {}
        for f_name in obj.__dataclass_fields__:
            v = getattr(obj, f_name)
            if hasattr(v, "to_parquet"):   # DataFrame — skip
                continue
            result[f_name] = _serialise(v)
        return result
    if isinstance(obj, list):
        return [_serialise(i) for i in obj]
    if isinstance(obj, dict):
        return {k: _serialise(v) for k, v in obj.items()}
    if isinstance(obj, Path):
        return str(obj)
    return obj


# ── Writers ───────────────────────────────────────────────────────────────────

def write_match_json(parsed: ParsedReplay, metrics: MatchMetrics,
                     moments: list, output_dir: Path,
                     analysis: dict = None):

    # Determine result from the tracked player's perspective
    me_pm = next((pm for pm in metrics.players if pm.is_me), None)
    me_team = me_pm.team if me_pm else "blue"
    player_won = (
        parsed.orange_score > parsed.blue_score
        if me_team == "orange"
        else parsed.blue_score > parsed.orange_score
    )

    data = {
        "match_id":   parsed.match_id,
        "date":       parsed.date,
        "map":        parsed.map_name,
        "map_display": _clean_map_name(parsed.map_name),
        "mode":       parsed.playlist,        # "2v2", "3v3", etc.
        "playlist":   parsed.playlist,        # kept for back-compat
        "result": {
            "blue_score":  parsed.blue_score,
            "orange_score": parsed.orange_score,
            "win":         player_won,         # True = tracked player won
            "player_team": me_team,
        },
        "duration_s": round(parsed.duration_s, 1),
        "me": next(
            ({"name": pm.name, "platform_id": pm.platform_id}
             for pm in metrics.players if pm.is_me),
            None,
        ),
        "players": [_serialise(pm) for pm in metrics.players],
        "team_metrics": {
            "double_commit_events": [_serialise(dc) for dc in metrics.double_commit_events],
            "kickoff_outcomes":     [_serialise(ko) for ko in metrics.kickoff_outcomes],
            "possession_chains":    metrics.possession_chains,
        },
        "moments": [
            {"t": m.t, "type": m.type, "diagram": m.diagram, "note": m.note}
            for m in moments
        ],
        "warnings": metrics.warnings,
    }

    # Full framework analysis (positioning / touch / shooting / patterns / extended).
    # Computed from the full-fidelity ParsedReplay at fetch time and persisted so
    # the on-demand AI step + coaching reader don't have to reconstruct it.
    if analysis:
        data["analysis"] = analysis

    path = output_dir / "match.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, default=str)
    log.info("Wrote %s", path)


def write_match_md(parsed: ParsedReplay, metrics: MatchMetrics,
                   moments: list, output_dir: Path):

    me = next((pm for pm in metrics.players if pm.is_me), None)

    # Result from tracked player's perspective
    me_team = me.team if me else "blue"
    player_won = (
        parsed.orange_score > parsed.blue_score
        if me_team == "orange"
        else parsed.blue_score > parsed.orange_score
    )
    is_draw = parsed.blue_score == parsed.orange_score

    if me_team == "orange":
        my_score, opp_score = parsed.orange_score, parsed.blue_score
    else:
        my_score, opp_score = parsed.blue_score, parsed.orange_score

    score_str = f"{my_score}-{opp_score}"
    win_str   = "**WIN**" if player_won else ("**DRAW**" if is_draw else "**LOSS**")

    map_display = _clean_map_name(parsed.map_name)
    mode        = parsed.playlist   # "2v2", "3v3", etc.

    lines = [
        f"# Match Report — {map_display} — {mode}",
        "",
        f"**Date:** {parsed.date}  |  **Mode:** {mode}  |  "
        f"**Result:** {win_str} {score_str}  |  **Duration:** {parsed.duration_s:.0f}s",
        "",
        "---",
        "",
    ]

    # ── My stats ──────────────────────────────────────────────────────────────
    if me:
        pos   = me.positioning
        boost = me.boost
        rec   = me.recovery
        lines += [
            f"## My Performance — {me.name} ({me.team})",
            "",
            "| Metric | Value |",
            "|--------|-------|",
            f"| Goals | {me.core.get('goals', '?')} |",
            f"| Shots | {me.core.get('shots', '?')} |",
            f"| Assists | {me.core.get('assists', '?')} |",
            f"| Saves | {me.core.get('saves', '?')} |",
            f"| Score | {me.core.get('score', '?')} |",
        ]
        if pos:
            lines += [
                f"| Def third % | **{pos.def_third_pct}%** |",
                f"| Neut third % | {pos.neut_third_pct}% |",
                f"| Off third % | {pos.off_third_pct}% |",
            ]
        if boost:
            lines += [
                f"| Avg boost | {boost.avg_boost} |",
                f"| Time at 0 boost | {boost.time_zero_s}s |",
            ]
        if rec:
            lines += [
                f"| Avg recovery | {rec.avg_recovery_s}s |",
                f"| Slow recoveries | {rec.slow_recoveries} |",
            ]
        lines.append("")

    # ── All players ───────────────────────────────────────────────────────────
    lines += [
        "## All Players",
        "",
        "| Player | Team | G | Sh | Sv | Score | Def% | Off% |",
        "|--------|------|---|----|----|-------|------|------|",
    ]
    for pm in metrics.players:
        pos = pm.positioning
        dp  = f"{pos.def_third_pct}%" if pos else "—"
        op  = f"{pos.off_third_pct}%" if pos else "—"
        flag = " *(me)*" if pm.is_me else ""
        lines.append(
            f"| {pm.name}{flag} | {pm.team} | {pm.core.get('goals','?')} | "
            f"{pm.core.get('shots','?')} | {pm.core.get('saves','?')} | "
            f"{pm.core.get('score','?')} | {dp} | {op} |"
        )
    lines.append("")

    # ── Team metrics ──────────────────────────────────────────────────────────
    if metrics.double_commit_events:
        lines += [
            f"## Double-Commit Events ({len(metrics.double_commit_events)} total)",
            "",
            "| Time | Duration |",
            "|------|----------|",
        ]
        for dc in metrics.double_commit_events:
            lines.append(f"| {dc.t:.1f}s | {dc.duration_s:.1f}s |")
        lines.append("")

    ko_lost = [k for k in metrics.kickoff_outcomes if k.result == "lost"]
    if metrics.kickoff_outcomes:
        ko_won = sum(1 for k in metrics.kickoff_outcomes if k.result == "won")
        ko_neu = sum(1 for k in metrics.kickoff_outcomes if k.result == "neutral")
        lines += [
            f"## Kickoffs  (won {ko_won} / lost {len(ko_lost)} / neutral {ko_neu})",
            "",
        ]
        if ko_lost:
            lines += ["**Lost kickoffs:**", ""]
            for k in ko_lost:
                concede = f" — conceded in {k.conceded_within_s:.1f}s" if k.conceded_within_s else ""
                lines.append(f"- {k.t:.1f}s{concede}")
            lines.append("")

    # ── Key moments / diagrams ────────────────────────────────────────────────
    if moments:
        lines += [
            "## Key Moments — Diagrams",
            "",
            "Upload the `moments/` folder alongside this file for diagram references.",
            "",
            "| # | Time | Type | Note |",
            "|---|------|------|------|",
        ]
        for i, m in enumerate(moments, 1):
            diag = f" `{m.diagram}`" if m.diagram else ""
            lines.append(f"| {i} | {m.t:.1f}s | {m.type} | {m.note[:90]}{diag} |")
        lines.append("")

    # ── Warnings ─────────────────────────────────────────────────────────────
    if metrics.warnings:
        lines += ["## Parse / Metric Warnings", ""]
        for w in metrics.warnings:
            lines.append(f"- {w}")
        lines.append("")

    path = output_dir / "match.md"
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    log.info("Wrote %s", path)
