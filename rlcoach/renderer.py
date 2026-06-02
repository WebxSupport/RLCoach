"""
FR5 — Top-down 2D PNG renderer.

RL field:  X ±4096 (width),  Y ±5120 (length)
Blue goal at Y ≈ -5120 (bottom of image)
Orange goal at Y ≈ +5120 (top of image)

Produces one PNG per flagged moment (or a 3-frame strip if extra_snapshots present).
"""
import logging
from pathlib import Path
from typing import Optional

import numpy as np

log = logging.getLogger(__name__)

FIELD_X = 4096.0
FIELD_Y = 5120.0
GOAL_WIDTH = 893.0
GOAL_DEPTH = 250.0

# Palette
C_BG      = "#0d1b2a"
C_FIELD   = "#0a2540"
C_LINE    = "#1e4a72"
C_THIRDS  = "#1a6b3a"
C_BLUE    = "#4fa3e0"
C_ORANGE  = "#e07a1f"
C_BALL    = "#f5f5f5"
C_TEXT    = "#cccccc"


def _world_to_ax(ax, x: float, y: float):
    """RL world coords → axes data coords (unchanged — we set ax limits to RL units)."""
    return x, y


def _render_frame(ax, snap: dict, title: str = ""):
    """Draw one top-down frame on the given matplotlib Axes."""
    import matplotlib.patches as mpatches

    ax.set_facecolor(C_FIELD)
    ax.set_xlim(-FIELD_X, FIELD_X)
    ax.set_ylim(-FIELD_Y - GOAL_DEPTH - 50, FIELD_Y + GOAL_DEPTH + 50)
    ax.set_aspect("equal")
    ax.set_xticks([])
    ax.set_yticks([])

    # Field border
    border = mpatches.Rectangle((-FIELD_X, -FIELD_Y), 2 * FIELD_X, 2 * FIELD_Y,
                                  fill=False, edgecolor=C_LINE, lw=2, zorder=1)
    ax.add_patch(border)

    # Midfield line + center circle
    ax.axhline(0, color=C_LINE, lw=1.2, zorder=1)
    circle = mpatches.Circle((0, 0), 820, fill=False, edgecolor=C_LINE, lw=1.2, zorder=1)
    ax.add_patch(circle)

    # Third lines
    for y_pos in (-FIELD_Y / 3, FIELD_Y / 3):
        ax.axhline(y_pos, color=C_THIRDS, lw=0.9, ls="--", alpha=0.6, zorder=1)

    # Goals
    blue_goal = mpatches.Rectangle((-GOAL_WIDTH, -FIELD_Y - GOAL_DEPTH),
                                    2 * GOAL_WIDTH, GOAL_DEPTH,
                                    facecolor="#0e2a4e", edgecolor=C_BLUE, lw=2, zorder=2)
    orange_goal = mpatches.Rectangle((-GOAL_WIDTH, FIELD_Y),
                                      2 * GOAL_WIDTH, GOAL_DEPTH,
                                      facecolor="#4e2a0e", edgecolor=C_ORANGE, lw=2, zorder=2)
    ax.add_patch(blue_goal)
    ax.add_patch(orange_goal)
    ax.text(0, -FIELD_Y - GOAL_DEPTH / 2, "BLUE GOAL", color=C_BLUE,
            fontsize=5, ha="center", va="center", zorder=3)
    ax.text(0, FIELD_Y + GOAL_DEPTH / 2, "ORANGE GOAL", color=C_ORANGE,
            fontsize=5, ha="center", va="center", zorder=3)

    # Ball
    ball = snap.get("ball", {})
    bx, by = ball.get("x", 0.0), ball.get("y", 0.0)
    bvx, bvy = ball.get("vx", 0.0), ball.get("vy", 0.0)
    bc = mpatches.Circle((bx, by), 92, color=C_BALL, zorder=5)
    ax.add_patch(bc)
    speed = (bvx ** 2 + bvy ** 2) ** 0.5
    if speed > 200:
        scale = min(speed * 0.12, 900.0)
        ax.annotate("", xy=(bx + bvx / speed * scale, by + bvy / speed * scale),
                    xytext=(bx, by),
                    arrowprops=dict(arrowstyle="->", color="#ffffffaa", lw=1.5), zorder=6)

    # Players
    for name, data in snap.items():
        if name == "ball":
            continue
        px, py = data.get("x", 0.0), data.get("y", 0.0)
        pvx, pvy = data.get("vx", 0.0), data.get("vy", 0.0)
        yaw = data.get("yaw", 0.0)
        color = C_ORANGE if data.get("is_orange") else C_BLUE

        car = mpatches.Circle((px, py), 130, color=color, zorder=4, alpha=0.9)
        ax.add_patch(car)

        # Facing arrow (yaw)
        if not np.isnan(yaw):
            dx, dy = np.cos(yaw) * 300, np.sin(yaw) * 300
            ax.annotate("", xy=(px + dx, py + dy), xytext=(px, py),
                        arrowprops=dict(arrowstyle="-|>", color=color, lw=2), zorder=5)

        # Velocity arrow (subtle)
        pspeed = (pvx ** 2 + pvy ** 2) ** 0.5
        if pspeed > 300:
            vscale = min(pspeed * 0.08, 600.0)
            ax.annotate("", xy=(px + pvx / pspeed * vscale, py + pvy / pspeed * vscale),
                        xytext=(px, py),
                        arrowprops=dict(arrowstyle="->", color="#aaaaaa77", lw=1), zorder=5)

        label = name[:10]
        ax.text(px, py + 200, label, color=color, fontsize=4.5,
                ha="center", va="bottom", fontweight="bold", zorder=7)

    if title:
        ax.set_title(title, color=C_TEXT, fontsize=6.5, pad=3)


def render_moment(snapshot: dict, output_path: Path,
                  title: str = "",
                  extra_snapshots: Optional[list] = None) -> bool:
    """
    Render a moment to a PNG.
    If extra_snapshots = [(t, snap), ...], renders a horizontal strip.
    Returns True on success.
    """
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        frames = [(None, snapshot)]
        if extra_snapshots:
            frames = [(t, s) for t, s in extra_snapshots if s]
        n = len(frames)

        fig, axes = plt.subplots(1, n, figsize=(3.5 * n, 5), dpi=100,
                                  facecolor=C_BG,
                                  gridspec_kw={"wspace": 0.05})
        if n == 1:
            axes = [axes]

        for ax, (t, snap) in zip(axes, frames):
            frame_title = f"{title} @ {t:.1f}s" if t is not None else title
            _render_frame(ax, snap, frame_title)

        output_path.parent.mkdir(parents=True, exist_ok=True)
        fig.savefig(str(output_path), bbox_inches="tight", facecolor=fig.get_facecolor(), dpi=100)
        plt.close(fig)
        return True

    except Exception as e:
        log.error("Render failed → %s: %s", output_path.name, e)
        return False
