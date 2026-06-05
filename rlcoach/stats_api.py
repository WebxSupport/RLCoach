"""
Player stats / rank fetching via PsyNet Skills API.

Source priority:
  1. PsyNet Skills API (via the authenticated RPC connection)
  2. Caller falls back to self-reported rank if this returns nothing

PsyNet playlist codes:
  10 = Ranked Duel (1v1)
  11 = Ranked Doubles (2v2)
  13 = Ranked Standard (3v3)
"""
from __future__ import annotations
import logging
from typing import Optional

log = logging.getLogger(__name__)

_TIER_NAMES = {
    0:  "Unranked",
    1:  "Bronze I",   2:  "Bronze II",   3:  "Bronze III",
    4:  "Silver I",   5:  "Silver II",   6:  "Silver III",
    7:  "Gold I",     8:  "Gold II",     9:  "Gold III",
    10: "Platinum I", 11: "Platinum II", 12: "Platinum III",
    13: "Diamond I",  14: "Diamond II",  15: "Diamond III",
    16: "Champion I", 17: "Champion II", 18: "Champion III",
    19: "Grand Champion I", 20: "Grand Champion II", 21: "Grand Champion III",
    22: "Supersonic Legend",
}

# Rank label → SVG filename in static/rank-icons/
RANK_ICON: dict[str, str] = {
    "Unranked":           "Unranked.svg",
    "Bronze I":           "b1.svg",  "Bronze II":           "b2.svg",  "Bronze III":           "b3.svg",
    "Silver I":           "s1.svg",  "Silver II":           "s2.svg",  "Silver III":           "s3.svg",
    "Gold I":             "g1.svg",  "Gold II":             "g2.svg",  "Gold III":             "g3.svg",
    "Platinum I":         "p1.svg",  "Platinum II":         "p2.svg",  "Platinum III":         "p3.svg",
    "Diamond I":          "d1.svg",  "Diamond II":          "d2.svg",  "Diamond III":          "d3.svg",
    "Champion I":         "c1.svg",  "Champion II":         "c2.svg",  "Champion III":         "c3.svg",
    "Grand Champion I":   "gc.svg",  "Grand Champion II":   "gc.svg",  "Grand Champion III":   "gc.svg",
    "Supersonic Legend":  "gc.svg",
}

_DIV_NAMES = {0: "I", 1: "II", 2: "III", 3: "IV"}

PLAYLIST_CODE: dict[str, int] = {
    "1v1": 10,
    "2v2": 11,
    "3v3": 13,
    "hoops": 27,
    "rumble": 28,
    "dropshot": 29,
    "snowday": 30,
}

PLAYLIST_LABEL: dict[int, str] = {v: k for k, v in PLAYLIST_CODE.items()}
CORE_PLAYLISTS = {10: "1v1", 11: "2v2", 13: "3v3"}


def tier_to_rank(tier: int) -> str:
    return _TIER_NAMES.get(tier, f"Rank {tier}")


def rank_icon_url(rank: str) -> str:
    """Return the /static/rank-icons/<file> URL for a rank label."""
    return "/static/rank-icons/" + RANK_ICON.get(rank, "Unranked.svg")


def _to_float(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _parse_entry(entry: dict) -> Optional[dict]:
    tier = entry.get("Tier", 0)
    division = entry.get("Division", 0)

    # Log the FULL entry once so the exact MMR field can be confirmed from
    # `docker compose logs | grep "skill entry"`.
    log.info("PsyNet skill entry: %s", entry)

    # 1) If any field is already a display-range rating (~100–3500), use it AS-IS.
    #    PsyNet's per-playlist `Skill`/`MMR`/`Rating` is the real number — do NOT scale it.
    mmr = 0
    for field in ("MMR", "Rating", "Skill", "SkillRating"):
        v = _to_float(entry.get(field))
        if v is not None and 100 <= v <= 4000:
            mmr = int(round(v))
            break

    # 2) Otherwise convert the TrueSkill mean: displayed rating ≈ mu × 20.
    if not mmr:
        mu = _to_float(entry.get("Mu"))
        if mu and mu > 0:
            mmr = max(0, round(mu * 20))

    mmr = max(0, int(mmr))
    rank = tier_to_rank(tier)
    return {
        "rank": rank,
        "tier": tier,
        "division": _DIV_NAMES.get(division, str(division + 1)),
        "mmr_estimate": mmr,
        "matches_played": entry.get("MatchesPlayed", 0),
        "icon": RANK_ICON.get(rank, "Unranked.svg"),
        "icon_url": rank_icon_url(rank),
        "source": "psynet_api",
    }


def _parse_skills_raw(raw: dict) -> dict[str, dict]:
    """Parse the full PsyNet skills response into {playlist_label: entry}."""
    skills_list = (
        raw.get("PlayerSkills") or
        raw.get("Skills") or
        raw.get("SkillRating") or
        []
    )
    results: dict[str, dict] = {}
    for entry in skills_list:
        pid = int(entry.get("Playlist") or entry.get("PlaylistId") or 0)
        if pid not in CORE_PLAYLISTS:
            continue
        label = CORE_PLAYLISTS[pid]
        parsed = _parse_entry(entry)
        if parsed and parsed["tier"] > 0:
            results[label] = parsed
    return results


async def _call_psynet_skills(
    access_token: str, account_id: str, display_name: str
) -> Optional[dict]:
    """Open a PsyNet connection and call the Skills API."""
    from rlapi.client import create_client
    client = await create_client(access_token, account_id, display_name)
    try:
        return await client.get_player_skills(timeout=8.0)
    finally:
        try:
            await client.close()
        except Exception:
            pass


async def fetch_all_ranks(
    access_token: str,
    account_id: str,
    display_name: str,
) -> dict[str, dict]:
    """
    Fetch rank/MMR for all core playlists (1v1, 2v2, 3v3).
    Returns {playlist_label: {rank, tier, icon, icon_url, mmr_estimate, ...}}
    or {} if the API is unavailable.
    """
    try:
        raw = await _call_psynet_skills(access_token, account_id, display_name)
        if raw:
            results = _parse_skills_raw(raw)
            log.info("PsyNet ranks fetched: %s", {k: v["rank"] for k, v in results.items()})
            return results
    except Exception as e:
        log.info("fetch_all_ranks failed (%s) — will use self-reported rank", e)
    return {}


async def fetch_player_stats(
    access_token: str,
    account_id: str,
    display_name: str,
    playlist_label: str,
) -> dict:
    """
    Fetch rank/stats for a single playlist.
    Returns a stats dict with source="psynet_api" or source="unavailable".
    """
    all_ranks = await fetch_all_ranks(access_token, account_id, display_name)
    label = playlist_label.lower().replace(" ", "")
    match = all_ranks.get(label) or all_ranks.get(playlist_label.lower())
    if match:
        return match
    return {"rank": None, "source": "unavailable"}
