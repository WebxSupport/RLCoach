"""
Advanced execution metrics (the framework's "Mechanical Execution" layer):

  - Boost economy:    small vs large pads, boost wasted (overfill), steal proxy,
                      and an economy rating.
  - Mechanical recovery: landings anchored on "action ends" — time to regain
                      ground control after an aerial, speed retention, dodge/
                      half-flip usage, and slow-landing count.

Both are heuristics over the frame data (boost 0–255 normalised; pos_z rests at
~17, aerials run to ~2000; jump/dodge/handbrake flags are available). Values are
comparative coaching signal, not lab-grade.
"""
from __future__ import annotations

import logging
import numpy as np

from .metrics import _col, _game_times, _gameplay_mask, _is_me

log = logging.getLogger(__name__)

# boost
SMALL_PAD = 12.0
PICKUP_NOISE = 3.0      # boost rise below this/frame = noise, ignore
BIG_GAIN = 40.0        # a single pickup gaining more than this = big pad
# recovery
AIR_Z = 120.0          # above this off the floor = airborne
COMMIT_Z = 250.0       # a segment peaking above this = a committed aerial (not a hop/bump)
GROUND_Z = 50.0        # at/below this = on the ground
CONTROL_SPEED = 700.0  # ground speed indicating regained momentum
SLOW_LANDING_S = 1.5
MIN_AIR_S = 0.4        # ignore tiny hops shorter than this


def _norm_boost(b):
    if b is None:
        return None
    finite = b[~np.isnan(b)]
    if finite.size and finite.max() > 100:
        return b / 255.0 * 100.0
    return b


# ── boost economy ───────────────────────────────────────────────────────────────

def compute_boost_economy(parsed, my_player_id: str) -> dict:
    df = parsed.frame_df
    if df is None or len(df) == 0:
        return {}
    dur = parsed.duration_s or 0.0
    gm = _gameplay_mask(df, dur)
    out = {"per_player": {}}
    for p in parsed.players:
        b = _col(df, p.name, "boost")
        if b is None:
            continue
        b = _norm_boost(b)[gm]
        y = _col(df, p.name, "pos_y")
        y = y[gm] if y is not None else None
        valid = ~np.isnan(b)
        if valid.sum() < 5:
            continue
        bv = b.copy()
        # forward-fill NaNs so diffs are clean
        idx = np.where(valid)[0]
        bv = np.interp(np.arange(len(bv)), idx, bv[idx])

        d = np.diff(bv)
        small = big = 0
        wasted = 0.0
        steals = 0
        i = 0
        n = len(d)
        is_orange = p.is_orange
        while i < n:
            if d[i] > PICKUP_NOISE:
                j = i
                gain = 0.0
                start_val = bv[i]
                while j < n and d[j] > PICKUP_NOISE:
                    gain += d[j]
                    j += 1
                end_val = bv[min(j, len(bv) - 1)]
                big_pad = gain > BIG_GAIN or (end_val >= 95 and gain > 25)
                if big_pad:
                    big += 1
                    wasted += max(0.0, start_val + 100.0 - 100.0)  # the pre-existing boost a 100-pad overwrote
                    if y is not None:
                        yy = y[min(j, len(y) - 1)]
                        if not np.isnan(yy) and ((yy < 0) if is_orange else (yy > 0)):
                            steals += 1   # big pad grabbed in the attacking half = denial/steal proxy
                else:
                    small += 1
                    wasted += max(0.0, start_val + SMALL_PAD - 100.0)
                i = j
            else:
                i += 1

        avg_boost = round(float(bv.mean()), 1)
        # economy rating: reward small-pad routing + healthy average, penalise waste + big-pad dependence
        total_pads = small + big
        small_share = (small / total_pads) if total_pads else 0.0
        econ = 50 + 0.5 * (avg_boost - 45) + 25 * small_share - 0.05 * wasted - 1.5 * max(0, big - small)
        out["per_player"][p.name] = {
            "is_me": _is_me(p.platform_id, my_player_id),
            "team": p.team,
            "small_pads": small,
            "big_pads": big,
            "wasted_overfill": round(wasted, 0),
            "steals": steals,
            "avg_boost": avg_boost,
            "economy_rating": round(float(np.clip(econ, 0, 100)), 1),
        }
    return out


# ── mechanical recovery ──────────────────────────────────────────────────────────

def compute_mechanical_recovery(parsed, my_player_id: str) -> dict:
    """
    For each aerial (sustained time off the floor), measure how long after
    touchdown the car regains ground control (grounded + moving), plus speed
    retention and dodge usage. Distinct from metrics._recovery (time-to-own-half).
    """
    df = parsed.frame_df
    if df is None or len(df) == 0:
        return {}
    times = _game_times(df)
    out = {"per_player": {}}
    for p in parsed.players:
        z = _col(df, p.name, "pos_z")
        vx = _col(df, p.name, "vel_x"); vy = _col(df, p.name, "vel_y")
        if z is None or vx is None or vy is None:
            continue
        vz = _col(df, p.name, "vel_z")
        dodge = _col(df, p.name, "dodge_active")
        spd = np.sqrt(np.nan_to_num(vx) ** 2 + np.nan_to_num(vy) ** 2 + (np.nan_to_num(vz) ** 2 if vz is not None else 0))
        airborne = np.nan_to_num(z) > AIR_Z

        recov_times, retentions, slow = [], [], 0
        dodges_in_recovery = 0
        n = len(z)
        i = 1
        while i < n:
            # start of an aerial
            if airborne[i] and not airborne[i - 1]:
                start = i
                j = i
                while j < n and airborne[j]:
                    j += 1
                air_dur = times[min(j, n - 1)] - times[start]
                peak_z = float(np.nanmax(z[start:max(start + 1, j)]))
                if air_dur >= MIN_AIR_S and peak_z > COMMIT_Z:   # committed aerial only
                    # touchdown at j; find when grounded + moving with control
                    land = j
                    spd_at_land = float(spd[min(land, n - 1)])
                    k = land
                    limit = min(n, land + int(5 * 30))  # up to ~5s
                    while k < limit:
                        if z[k] <= GROUND_Z and spd[k] >= CONTROL_SPEED:
                            break
                        k += 1
                    rec = times[min(k, n - 1)] - times[min(land, n - 1)]
                    if rec >= 0:
                        recov_times.append(rec)
                        if rec >= SLOW_LANDING_S:
                            slow += 1
                        spd_after = float(spd[min(k, n - 1)])
                        if spd_at_land > 100:
                            retentions.append(min(1.5, spd_after / spd_at_land))
                        if dodge is not None and np.nansum(dodge[land:min(k + 1, n)]) > 0:
                            dodges_in_recovery += 1
                i = max(j, i + 1)
            else:
                i += 1

        if not recov_times:
            continue
        out["per_player"][p.name] = {
            "is_me": _is_me(p.platform_id, my_player_id),
            "team": p.team,
            "aerials": len(recov_times),
            "avg_recovery_s": round(float(np.mean(recov_times)), 2),
            "slow_landings": slow,
            "speed_retention_pct": round(float(np.mean(retentions) * 100), 0) if retentions else None,
            "recovery_dodges": dodges_in_recovery,
        }
    return out


def compute_advanced(parsed, my_player_id: str) -> dict:
    """Bundle the advanced execution metrics into one dict."""
    out = {}
    try:
        out["boost_economy"] = compute_boost_economy(parsed, my_player_id)
    except Exception as e:
        log.debug("boost_economy failed: %s", e)
    try:
        out["mechanical_recovery"] = compute_mechanical_recovery(parsed, my_player_id)
    except Exception as e:
        log.debug("mechanical_recovery failed: %s", e)
    return out
