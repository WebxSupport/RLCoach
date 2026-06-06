"""
Unified analysis aggregator.

One entry point that runs every metric layer against a ParsedReplay and returns
both the raw result objects (for diagram rendering) and a single JSON-ready dict
(for persistence into match.json and for the Claude prompt).

    metrics        — core per-player + team metrics (positioning thirds, boost, recovery, speed)
    extended       — frame aggregates (possession, net coverage, ballchase, goal windows)
    positioning    — coverage zones, support distance, distance-to-play, last-man
    touch          — touch quality, possession outcomes, challenges
    shooting       — per-shot xG, finishing
    patterns       — ranked Evidence→Pattern→Consequence→Fix habits (tracked player)

Both the web and desktop pipelines should call analyze_all() so they stay in sync.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

log = logging.getLogger(__name__)


@dataclass
class FullAnalysis:
    metrics: object              # MatchMetrics
    extended: dict
    positioning: list            # list[PlayerPositioning]
    touch: object                # TouchAnalysis
    shooting: object             # ShootingReport
    patterns: object             # PatternReport (tracked player)

    def to_dict(self, include_touches: bool = False, include_shots: bool = True) -> dict:
        from .positioning import positioning_to_dict
        from .touch_analysis import touch_analysis_to_dict
        from .shooting import shooting_to_dict
        from .patterns import patterns_to_dict
        return {
            "positioning": positioning_to_dict(self.positioning),
            "touch": touch_analysis_to_dict(self.touch, include_touches=include_touches),
            "shooting": shooting_to_dict(self.shooting, include_shots=include_shots),
            "patterns": patterns_to_dict(self.patterns),
            "extended": self.extended or {},
        }


def analyze_all(parsed, my_player_id: str, *,
                metrics=None, rank_tier: Optional[str] = None) -> FullAnalysis:
    """
    Run all metric layers. `metrics` may be passed in to avoid recomputation
    (the pipeline already computes it); everything else is derived here.
    Each layer is guarded so one failure never sinks the whole analysis.
    """
    from .metrics import compute_metrics
    from .positioning import compute_positioning
    from .touch_analysis import compute_touch_analysis
    from .shooting import compute_shooting
    from .patterns import compute_patterns
    from .extended_metrics import compute_extended_metrics

    if metrics is None:
        metrics = compute_metrics(parsed, my_player_id)

    def _safe(fn, default, label):
        try:
            return fn()
        except Exception as e:
            log.warning("analyze_all: %s failed: %s", label, e)
            return default

    extended = _safe(
        lambda: compute_extended_metrics(parsed.frame_df, parsed, my_player_id, parsed.duration_s),
        {}, "extended_metrics")
    positioning = _safe(lambda: compute_positioning(parsed, my_player_id), [], "positioning")
    touch = _safe(lambda: compute_touch_analysis(parsed, my_player_id), None, "touch_analysis")
    shooting = _safe(lambda: compute_shooting(parsed, my_player_id), None, "shooting")
    patterns = _safe(
        lambda: compute_patterns(parsed, my_player_id, positioning=positioning, touch=touch,
                                 metrics=metrics, extended=extended, rank_tier=rank_tier),
        None, "patterns")

    return FullAnalysis(
        metrics=metrics, extended=extended, positioning=positioning,
        touch=touch, shooting=shooting, patterns=patterns,
    )
