"""
Plain-English phrasing helpers.

The analysis framework works in Rocket League "unreal units" (uu), but players —
especially newer ones — don't think in uu. Everything that reaches a user should
read in plain English: distances as a fraction of the pitch, internal metric
field names as readable labels.

Pitch is 10240uu goal-to-goal, 8192uu wide. We express distances as a fraction of
the goal-to-goal length because "a third of the pitch" is the most intuitive scale
for positioning/support talk.
"""
from __future__ import annotations

from typing import Optional

FIELD_LENGTH = 10240.0   # uu, goal-to-goal
FIELD_HALF = 5120.0      # uu, midfield to one goal

# Common, intuitive fractions of the pitch. Nearest-match keeps phrasing readable
# (no "0.27 of the pitch" or odd sixths).
_FRACTIONS = [
    (1 / 10, "a tenth of the pitch"),
    (1 / 5, "a fifth of the pitch"),
    (1 / 4, "a quarter of the pitch"),
    (1 / 3, "a third of the pitch"),
    (1 / 2, "half the pitch"),
    (2 / 3, "two-thirds of the pitch"),
    (3 / 4, "three-quarters of the pitch"),
    (1.0, "the length of the pitch"),
]


def field_fraction(uu: Optional[float], lead: str = "about ") -> str:
    """A distance in uu as a plain-English fraction of the pitch.

    e.g. 1900 -> "about a fifth of the pitch", 3000 -> "about a third of the pitch".
    Returns "" for None so callers can drop it cleanly.
    """
    if uu is None:
        return ""
    f = abs(float(uu)) / FIELD_LENGTH
    if f < 0.05:
        return "almost no gap"
    label = min(_FRACTIONS, key=lambda t: abs(t[0] - f))[1]
    return f"{lead}{label}"


# The ideal second-man support band (positioning.SUPPORT_MIN..MAX, ~1800-2500uu)
# said in plain English once, so prose and diagrams agree.
SUPPORT_GAP_PHRASE = "a passing-lane gap (about a fifth of the pitch)"


def depth_phrase(uu: Optional[float]) -> str:
    """How far up-field a last man has pushed, measured from their own goal."""
    if uu is None:
        return ""
    f = abs(float(uu)) / FIELD_LENGTH
    if f >= 0.55:
        return "past the halfway line"
    if f >= 0.42:
        return "near the halfway line"
    return f"{field_fraction(uu)} up-field"


# Internal metric field-name -> readable label. Used to defensively relabel
# anything that could otherwise surface a raw key, and to feed plain labels into
# the AI prompts so the model never echoes the field names back to users.
FRIENDLY_METRIC = {
    "rotation_score": "Rotation score",
    "poor_rotation_pct": "Poor rotations",
    "critical_errors": "Critical rotation errors",
    "challenge_win_pct": "Challenges won",
    "support_too_close_pct": "Crowding your teammate",
    "support_too_far_pct": "Supporting too far back",
    "back_post_pct": "Back-post coverage",
    "near_post_pct": "Near-post coverage",
    "own_half_pct": "Time in your own half",
    "last_man_risky_pct": "Risky last-man pushes",
    "last_man_high_pct": "Caught high as last man",
    "touch_positive_pct": "Clean, positive touches",
    "first_touch_pos_pct": "Controlled first touches",
    "giveaways": "Giveaways",
    "xg": "Expected goals (chance quality)",
    "xg_diff": "Finishing vs chance quality",
    "boost_economy_rating": "Boost economy",
    "boost_wasted": "Boost wasted to overfill",
    "mech_recovery_s": "Time to reset after a touch",
    "avg_boost": "Average boost held",
    "conv": "Shot conversion",
}


def friendly_metric(key: str) -> str:
    """Readable label for an internal metric key (falls back to a de-snaked key)."""
    return FRIENDLY_METRIC.get(key) or key.replace("_", " ").replace(" pct", " %").strip().capitalize()


# Metrics the player can track over time on the My Stats page. `better` says which
# direction is improvement (for colouring trend lines); `unit` is for axis labels.
METRIC_CATALOGUE = [
    {"key": "rotation_score",       "unit": "/100", "better": "high"},
    {"key": "poor_rotation_pct",    "unit": "%",    "better": "low"},
    {"key": "challenge_win_pct",    "unit": "%",    "better": "high"},
    {"key": "touch_positive_pct",   "unit": "%",    "better": "high"},
    {"key": "first_touch_pos_pct",  "unit": "%",    "better": "high"},
    {"key": "giveaways",            "unit": "",     "better": "low"},
    {"key": "xg",                   "unit": "",     "better": "high"},
    {"key": "xg_diff",              "unit": "",     "better": "high"},
    {"key": "boost_economy_rating", "unit": "/100", "better": "high"},
    {"key": "boost_wasted",         "unit": "",     "better": "low"},
    {"key": "support_too_far_pct",  "unit": "%",    "better": "low"},
    {"key": "support_too_close_pct","unit": "%",    "better": "low"},
    {"key": "back_post_pct",        "unit": "%",    "better": "high"},
    {"key": "near_post_pct",        "unit": "%",    "better": "low"},
    {"key": "own_half_pct",         "unit": "%",    "better": "high"},
    {"key": "last_man_risky_pct",   "unit": "%",    "better": "low"},
    {"key": "last_man_high_pct",    "unit": "%",    "better": "low"},
    {"key": "mech_recovery_s",      "unit": "s",    "better": "low"},
]


def metric_catalogue() -> list:
    """Catalogue of trackable metrics with readable labels, for the My Stats picker."""
    return [{"key": m["key"], "label": friendly_metric(m["key"]),
             "unit": m["unit"], "better": m["better"]} for m in METRIC_CATALOGUE]
