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

from .phrasing import depth_phrase, field_fraction

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
C_BAD     = "#e23b3b"   # actual position when it's a mistake
C_GOOD    = "#33c46b"   # ideal / target position
C_IDEAL_BAND = "#33c46b"  # support-band annulus fill


def _world_to_ax(ax, x: float, y: float):
    """RL world coords → axes data coords (unchanged — we set ax limits to RL units)."""
    return x, y


def _draw_pitch(ax):
    """Draw the empty top-down pitch (border, midline, thirds, goals) on an Axes."""
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


def _render_frame(ax, snap: dict, title: str = ""):
    """Draw one top-down frame on the given matplotlib Axes."""
    import matplotlib.patches as mpatches

    _draw_pitch(ax)

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


# ── Annotated "actual vs ideal" distance diagrams ───────────────────────────────
#
# These answer the coaching question "where were you, and where SHOULD you have
# been?" by drawing the player's actual position, the ideal target, the distance
# between them, and a correction arrow.

def _car(ax, x, y, color, label=None, alpha=0.95, r=130, z=4):
    import matplotlib.patches as mpatches
    ax.add_patch(mpatches.Circle((x, y), r, color=color, zorder=z, alpha=alpha))
    if label:
        ax.text(x, y + 230, label, color=color, fontsize=5.5, ha="center",
                va="bottom", fontweight="bold", zorder=z + 3)


def _ghost(ax, x, y, color, label=None, r=130, z=4):
    """A hollow dashed marker = where the player SHOULD have been."""
    import matplotlib.patches as mpatches
    ax.add_patch(mpatches.Circle((x, y), r, fill=False, edgecolor=color,
                                 lw=2.0, ls=(0, (4, 3)), zorder=z, alpha=0.95))
    if label:
        ax.text(x, y - 320, label, color=color, fontsize=5.0, ha="center",
                va="top", fontweight="bold", zorder=z + 3)


def render_support_distance(moment: dict, output_path: Path,
                            player_name: str = "You",
                            is_orange: bool = False) -> bool:
    """
    Diagram a support-distance mistake.

    Draws the possessing teammate with the ball, the ideal support band
    (1800-2500uu annulus around the possessor), the player's ACTUAL position
    (red), and a dashed ghost at the nearest in-band target with a correction
    arrow + distance labels.

    `moment` is a SupportMoment-shaped dict:
      {t, dist, kind, actual:[x,y], teammate:[x,y], ball:[x,y], ideal_lo, ideal_hi}
    """
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        import matplotlib.patches as mpatches

        team_color = C_ORANGE if is_orange else C_BLUE
        tx, ty = moment["teammate"]
        ax_, ay_ = moment["actual"]
        bx, by = moment.get("ball", [tx, ty])
        lo = float(moment.get("ideal_lo", 1800.0))
        hi = float(moment.get("ideal_hi", 2500.0))
        kind = moment.get("kind", "too_far")
        dist = float(moment.get("dist", 0.0))

        fig, ax = plt.subplots(figsize=(4.2, 5.2), dpi=110, facecolor=C_BG)
        _draw_pitch(ax)

        # Ideal support band (annulus around the possessor).
        ax.add_patch(mpatches.Wedge((tx, ty), hi, 0, 360, width=hi - lo,
                                    facecolor=C_IDEAL_BAND, alpha=0.16,
                                    edgecolor=C_GOOD, lw=1.0, zorder=2))
        ax.text(tx, ty + hi + 120, "ideal support zone\n(a passing-lane gap)",
                color=C_GOOD, fontsize=5.0, ha="center", va="bottom", zorder=6)

        # Possessor + ball.
        _car(ax, tx, ty, team_color, label=f"{player_name}'s teammate", z=4)
        ax.add_patch(mpatches.Circle((bx, by), 92, color=C_BALL, zorder=5))

        # Correction ghost: snap actual onto the nearest band edge along the
        # possessor→actual direction.
        vx, vy = ax_ - tx, ay_ - ty
        d = (vx ** 2 + vy ** 2) ** 0.5 or 1.0
        ux, uy = vx / d, vy / d
        target_d = lo if kind == "too_close" else hi
        gx, gy = tx + ux * target_d, ty + uy * target_d

        # Distance line possessor → actual.
        ax.plot([tx, ax_], [ty, ay_], color=C_BAD, lw=1.3, ls=":", zorder=3)
        ax.text((tx + ax_) / 2, (ty + ay_) / 2, field_fraction(dist),
                color=C_BAD, fontsize=5.5, ha="center", va="center",
                fontweight="bold", zorder=7,
                bbox=dict(boxstyle="round,pad=0.15", fc=C_BG, ec=C_BAD, lw=0.6))

        # Correction arrow actual → ghost.
        ax.annotate("", xy=(gx, gy), xytext=(ax_, ay_),
                    arrowprops=dict(arrowstyle="-|>", color=C_GOOD, lw=1.8), zorder=6)

        _car(ax, ax_, ay_, C_BAD, label=f"{player_name} (actual)", z=5)
        _ghost(ax, gx, gy, C_GOOD, label="move here", z=5)

        verdict = "TOO CLOSE — double-commit risk" if kind == "too_close" else "TOO FAR — no follow-up"
        ax.set_title(f"Support distance @ {moment.get('t', 0):.1f}s — {verdict}",
                     color=C_TEXT, fontsize=7, pad=4)

        output_path.parent.mkdir(parents=True, exist_ok=True)
        fig.savefig(str(output_path), bbox_inches="tight", facecolor=fig.get_facecolor(), dpi=110)
        plt.close(fig)
        return True
    except Exception as e:
        log.error("Support-distance render failed → %s: %s", output_path.name, e)
        return False


def render_last_man(moment: dict, output_path: Path,
                    player_name: str = "You",
                    is_orange: bool = False) -> bool:
    """
    Diagram a risky last-man push: the player is the deepest defender yet is up
    the field, leaving the net exposed. Shows actual position, the ball, the
    open net, and a ghost at a safe back-post recovery spot.

    `moment` is a LastManMoment-shaped dict: {t, depth, actual:[x,y], ball:[x,y]}
    """
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        import matplotlib.patches as mpatches

        team_color = C_ORANGE if is_orange else C_BLUE
        own_goal_y = FIELD_Y if is_orange else -FIELD_Y
        ax_, ay_ = moment["actual"]
        bx, by = moment.get("ball", [0.0, 0.0])

        fig, ax = plt.subplots(figsize=(4.2, 5.2), dpi=110, facecolor=C_BG)
        _draw_pitch(ax)

        # Highlight the exposed net.
        ax.add_patch(mpatches.Rectangle(
            (-GOAL_WIDTH, own_goal_y - (GOAL_DEPTH if is_orange else 0)),
            2 * GOAL_WIDTH, GOAL_DEPTH, facecolor=C_BAD, alpha=0.35, zorder=2))
        ax.text(0, own_goal_y * 0.86, "NET EXPOSED", color=C_BAD, fontsize=6,
                ha="center", va="center", fontweight="bold", zorder=6)

        # Ball.
        ax.add_patch(mpatches.Circle((bx, by), 92, color=C_BALL, zorder=5))

        # Safe recovery ghost: back-post, goal-side, in own third.
        gx = -900.0 if bx > 0 else 900.0   # opposite post to the ball
        gy = own_goal_y + (-1500.0 if is_orange else 1500.0)
        ax.annotate("", xy=(gx, gy), xytext=(ax_, ay_),
                    arrowprops=dict(arrowstyle="-|>", color=C_GOOD, lw=1.8), zorder=6)

        _car(ax, ax_, ay_, C_BAD, label=f"{player_name} (last man, pushed up)", z=5)
        _ghost(ax, gx, gy, C_GOOD, label="cover back post", z=5)

        ax.set_title(f"Risky last-man push @ {moment.get('t', 0):.1f}s "
                     f"(pushed up {depth_phrase(moment.get('depth', 0))})",
                     color=C_TEXT, fontsize=7, pad=4)

        output_path.parent.mkdir(parents=True, exist_ok=True)
        fig.savefig(str(output_path), bbox_inches="tight", facecolor=fig.get_facecolor(), dpi=110)
        plt.close(fig)
        return True
    except Exception as e:
        log.error("Last-man render failed → %s: %s", output_path.name, e)
        return False


def render_coverage_zones(coverage: dict, output_path: Path,
                          player_name: str = "You",
                          is_orange: bool = False) -> bool:
    """
    Shade the five defensive-coverage zones on the player's own half and label
    each with the share of own-half time spent there. Back post (the target) is
    outlined green; near post / backboard (the leak zones) are outlined red.

    `coverage` is a CoverageZones-shaped dict:
      {near_post_pct, back_post_pct, goal_line_pct, midfield_pct, backboard_pct, own_half_pct}
    """
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        import matplotlib.patches as mpatches

        from .positioning import ZONE_DEEP, ZONE_MID, ZONE_WIDE_X

        own_goal_y = FIELD_Y if is_orange else -FIELD_Y
        sgn = -1.0 if is_orange else 1.0   # +1 blue: own half is negative-Y going toward midfield up (+)

        fig, ax = plt.subplots(figsize=(4.2, 5.2), dpi=110, facecolor=C_BG)
        _draw_pitch(ax)

        # y-coordinates of the band boundaries, measured from own goal inward.
        def band_y(d):
            return own_goal_y + sgn * d

        y_goal = own_goal_y
        y_deep = band_y(ZONE_DEEP)
        y_mid = band_y(ZONE_MID)
        y_half = 0.0

        def add_zone(y_lo, y_hi, x_lo, x_hi, pct, name, tone):
            ylo, yhi = sorted([y_lo, y_hi])
            edge = {"good": C_GOOD, "bad": C_BAD, "neutral": C_LINE}[tone]
            fill = {"good": C_GOOD, "bad": C_BAD, "neutral": C_THIRDS}[tone]
            ax.add_patch(mpatches.Rectangle((x_lo, ylo), x_hi - x_lo, yhi - ylo,
                                            facecolor=fill, alpha=0.10 + 0.30 * min(pct / 100.0, 1.0),
                                            edgecolor=edge, lw=1.2, zorder=2))
            ax.text((x_lo + x_hi) / 2, (ylo + yhi) / 2, f"{name}\n{pct:.0f}%",
                    color=C_TEXT, fontsize=5.2, ha="center", va="center",
                    fontweight="bold", zorder=6)

        # Goal-line (central deep) + backboard (wide deep)
        add_zone(y_goal, y_deep, -ZONE_WIDE_X, ZONE_WIDE_X, coverage.get("goal_line_pct", 0), "goal line", "neutral")
        add_zone(y_goal, y_deep, -FIELD_X, -ZONE_WIDE_X, coverage.get("backboard_pct", 0) / 2, "backboard", "bad")
        add_zone(y_goal, y_deep, ZONE_WIDE_X, FIELD_X, coverage.get("backboard_pct", 0) / 2, "backboard", "bad")
        # Post band: near (ball-side) vs back (away) — show both halves; near=bad, back=good
        add_zone(y_deep, y_mid, 0, FIELD_X, coverage.get("near_post_pct", 0), "near post", "bad")
        add_zone(y_deep, y_mid, -FIELD_X, 0, coverage.get("back_post_pct", 0), "back post", "good")
        # Midfield (high in own half)
        add_zone(y_mid, y_half, -FIELD_X, FIELD_X, coverage.get("midfield_pct", 0), "midfield", "neutral")

        ax.set_title(f"{player_name} — defensive coverage "
                     f"({coverage.get('own_half_pct', 0):.0f}% of play in own half)",
                     color=C_TEXT, fontsize=7, pad=4)

        output_path.parent.mkdir(parents=True, exist_ok=True)
        fig.savefig(str(output_path), bbox_inches="tight", facecolor=fig.get_facecolor(), dpi=110)
        plt.close(fig)
        return True
    except Exception as e:
        log.error("Coverage-zones render failed → %s: %s", output_path.name, e)
        return False


# ── Shared wiring: render a diagram per positioning habit ────────────────────────

def render_pattern_diagrams(analysis: dict, moments_dir: Path, is_orange: bool) -> None:
    """Render an "actual vs ideal" field diagram for every positioning habit that
    has one (support / coverage / last-man) and stamp the relative PNG path onto
    each pattern dict as `diagram_path`.

    Works purely from the persisted analysis dict (the support/last-man worst
    moments serialise into match.json), so the fetch and coaching pipelines share
    one code path. Mutates `analysis` in place; call before write_match_json.
    """
    try:
        pats = (analysis.get("patterns") or {}).get("patterns") or []
        if not pats:
            return
        pos_all = analysis.get("positioning") or {}
        me_name, me_pos = next(
            ((k, v) for k, v in pos_all.items() if isinstance(v, dict) and v.get("is_me")),
            (None, None))
        if not me_pos:
            return
        support_moments = (me_pos.get("support") or {}).get("worst_moments") or []
        risky_moments = (me_pos.get("last_man") or {}).get("risky_moments") or []
        coverage = me_pos.get("coverage") or {}
        for idx, pat in enumerate(pats):
            dtype = pat.get("diagram")
            rel = None
            try:
                if dtype == "coverage" and coverage:
                    png = moments_dir / f"pattern_{idx}_coverage.png"
                    if render_coverage_zones(coverage, png, me_name, is_orange):
                        rel = f"moments/{png.name}"
                elif dtype == "support" and support_moments:
                    png = moments_dir / f"pattern_{idx}_support.png"
                    if render_support_distance(support_moments[0], png, me_name, is_orange):
                        rel = f"moments/{png.name}"
                elif dtype == "lastman" and risky_moments:
                    png = moments_dir / f"pattern_{idx}_lastman.png"
                    if render_last_man(risky_moments[0], png, me_name, is_orange):
                        rel = f"moments/{png.name}"
            except Exception as e:
                log.debug("pattern diagram %d failed: %s", idx, e)
            pat["diagram_path"] = rel
    except Exception as e:
        log.warning("render_pattern_diagrams failed: %s", e)


def diagram_data_uri(base_dir, rel_path: Optional[str]) -> Optional[str]:
    """Read a rendered PNG under `base_dir` and return a base64 data URI so it can
    be inlined into a self-contained dashboard (no extra image endpoint needed).
    Returns None if the path is missing or unreadable."""
    if not rel_path or not base_dir:
        return None
    try:
        import base64
        p = Path(base_dir) / rel_path
        if not p.exists():
            return None
        return "data:image/png;base64," + base64.b64encode(p.read_bytes()).decode("ascii")
    except Exception as e:
        log.debug("diagram inline failed for %s: %s", rel_path, e)
        return None
