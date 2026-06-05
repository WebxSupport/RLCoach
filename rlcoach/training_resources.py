"""
Curated training resources reference for the coaching engine.

Included in the Claude prompt so it can cite specific resources.
Platform-split: PC gets workshop maps + BakkesMod; console gets training packs only.
"""

# ── Rank tiers ─────────────────────────────────────────────────────────────────

RANK_LADDER = [
    "Unranked",
    "Bronze I", "Bronze II", "Bronze III",
    "Silver I", "Silver II", "Silver III",
    "Gold I", "Gold II", "Gold III",
    "Platinum I", "Platinum II", "Platinum III",
    "Diamond I", "Diamond II", "Diamond III",
    "Champion I", "Champion II", "Champion III",
    "Grand Champion I", "Grand Champion II", "Grand Champion III",
    "Supersonic Legend",
]

# Map rank label → 0-based index for gap calculation
RANK_INDEX = {r: i for i, r in enumerate(RANK_LADDER)}

PLAYLIST_OPTIONS = [
    {"label": "Ranked Doubles (2v2)", "value": "2v2", "team_size": 2},
    {"label": "Ranked Standard (3v3)", "value": "3v3", "team_size": 3},
    {"label": "Ranked Duel (1v1)",     "value": "1v1", "team_size": 1},
]

PLATFORM_OPTIONS = [
    {"label": "PC — Steam",          "value": "steam",  "has_bakkesmod": True},
    {"label": "PC — Epic Games",     "value": "epic",   "has_bakkesmod": True},
    {"label": "PlayStation",         "value": "psn",    "has_bakkesmod": False},
    {"label": "Xbox",                "value": "xbl",    "has_bakkesmod": False},
    {"label": "Nintendo Switch",     "value": "switch", "has_bakkesmod": False},
]

# ── Training packs (all platforms) ────────────────────────────────────────────

# Real community training packs with verified codes
TRAINING_PACKS = {
    "fundamentals": [
        {"name": "Beginner - Ground Shots",        "code": "A0F1-E30E-EF91-5A96"},
        {"name": "Intermediate - Dribbling",       "code": "D4E3-A0E1-5E82-8D22"},
        {"name": "Wall Reads",                     "code": "4EB4-23B9-C2CD-6A0E"},
        {"name": "Shooting — Finishing",           "code": "6A40-8A4E-9949-B59E"},
    ],
    "mechanics": [
        {"name": "Aerial - Beginner",              "code": "B8EC-3D09-ED1A-0F7D"},
        {"name": "Aerial - Intermediate",          "code": "A-B2D6-A8E6-3FB4"},
        {"name": "Musty Flick Practice",           "code": "B9BE-5EA1-A89E-A282"},
    ],
    "defense": [
        {"name": "Save Scenarios",                 "code": "9836-BEFE-95C1-CAB6"},
        {"name": "Goalkeeping",                    "code": "18A5-F044-EEF5-D0A0"},
    ],
    "passing": [
        {"name": "Passing & Bumps — Duos",         "code": "4A4A-EAB0-8CA2-C3A2"},
    ],
}

# ── Workshop maps (PC/BakkesMod only) ─────────────────────────────────────────

WORKSHOP_MAPS = {
    "aerial": [
        {"name": "Rings Map",               "author": "Lethamyr",    "steam_workshop_id": "1565535901",
         "use": "Fly through rings — foundational aerial control and car positioning in the air"},
        {"name": "AIR — Aerial Training",   "author": "Various",
         "use": "Structured aerial challenge progression from basic to advanced"},
        {"name": "Rings Reverse",           "author": "Lethamyr",    "steam_workshop_id": "1572824364",
         "use": "Back-to-basics aerial direction control; fly backwards through rings"},
    ],
    "ball_control": [
        {"name": "Dribble Challenge 2",     "author": "Lethamyr",    "steam_workshop_id": "1489736853",
         "use": "Dribble the ball through obstacle courses — best map for close ball control"},
        {"name": "Dribble Course",          "author": "Various",
         "use": "Gates and ramps for intermediate dribbling"},
        {"name": "KBM Obstacle Course",     "author": "KBM",
         "use": "Precise mechanical movement with tight ball control"},
    ],
    "fundamentals": [
        {"name": "Ground Zero",             "author": "Gelo",
         "use": "Ground mechanics fundamentals — boost usage, positioning, speed"},
        {"name": "Rings Mega",              "author": "Lethamyr",    "steam_workshop_id": "1600575985",
         "use": "Comprehensive aerial rings — width + height variation; great for daily warm-up"},
    ],
    "speed": [
        {"name": "Musty's Ring Map",        "author": "Musty",
         "use": "High-speed aerial rings; develops boost efficiency at pace"},
        {"name": "Speed Jump Course",       "author": "Various",
         "use": "Speed-flip practice in a controlled environment"},
    ],
    "mechanics": [
        {"name": "Obstacle Challenge",      "author": "Various",
         "use": "Precise car control — ceiling shots, wall pops, advanced mechanics"},
        {"name": "Kuxir Dribble",          "author": "Various",
         "use": "Flick scenarios on the ground and low aerials"},
    ],
}

# ── BakkesMod plugins (PC only) ───────────────────────────────────────────────

BAKKESMOD_PLUGINS = [
    {"name": "Mechanics Trainer",   "use": "Structured drills for speed flips, wave dashes, and recoveries"},
    {"name": "Alpha Console",       "use": "Custom training sequences and shot packs"},
    {"name": "DribbleTracker",      "use": "Tracks dribble stats in freeplay — how long you hold without dropping"},
    {"name": "RocketPlugin",        "use": "Enables workshop maps and custom modes including aerial-only training"},
    {"name": "Training Pack Creator", "use": "Build your own packs from in-game scenarios you find difficult"},
]

# ── Rank-tier focus areas ─────────────────────────────────────────────────────

TIER_SKILLS = {
    "Bronze–Silver": {
        "priorities": ["Consistent shooting on target", "Boost management basics (avoid zero)", "Not following the ball blindly", "Basic kickoffs"],
        "avoid": ["Aerials — not needed yet; ground play first", "Over-committing"],
        "weekly_drill": "5 minutes freeplay dribbling before every session",
    },
    "Gold–Platinum": {
        "priorities": ["Boost pad routing on rotation", "Aerial introduction (low aerials)", "One-goes-one-covers rotation basics", "Reading deflections"],
        "avoid": ["Double-committing with teammate", "Clearing straight up the middle"],
        "weekly_drill": "10 min rings map + 5 min freeplay aerials",
    },
    "Diamond": {
        "priorities": ["Double-commit elimination", "Boost economy discipline (average ≥ 45)", "50/50 reads and fakes", "Wide rotation paths"],
        "avoid": ["Jumping into challenges without a backup plan", "Ball-watching from the back"],
        "weekly_drill": "Rings + dribble challenge 2 + 1 concept training pack daily",
    },
    "Champion": {
        "priorities": ["Advanced rotation (third-man cover)", "Recovery after hitting the ball", "Mid-air redirect decisions", "Fake challenges"],
        "avoid": ["Passive 'waiting' — GC-level opponents punish passive play", "Predictable shot directions"],
        "weekly_drill": "Speed-flip training + workshop aerial map + replay review",
    },
    "Grand Champion+": {
        "priorities": ["Fast aerials off any surface", "Pressure and stall timing", "Advanced rotation reads", "Demo and bump strategy"],
        "avoid": ["Unnecessary 50/50s with shape already good", "Over-rotating"],
        "weekly_drill": "Custom training → mechanics → full matches with replay review",
    },
}


def get_tier_label(rank: str) -> str:
    """Map a rank string to the TIER_SKILLS key."""
    r = rank.lower()
    if "bronze" in r or "silver" in r:
        return "Bronze–Silver"
    if "gold" in r or "platinum" in r:
        return "Gold–Platinum"
    if "diamond" in r:
        return "Diamond"
    if "champion i" in r or "champion ii" in r or "champion iii" in r:
        return "Champion"
    return "Grand Champion+"


def rank_gap(current: str, target: str) -> int:
    """Number of rank tiers between current and target (0 = same rank)."""
    ci = RANK_INDEX.get(current, 0)
    ti = RANK_INDEX.get(target, 0)
    return max(0, ti - ci)


import re as _re


def _slug(s: str) -> str:
    return _re.sub(r"[^a-z0-9]+", "-", (s or "").lower()).strip("-")


def _norm(s: str) -> str:
    return _re.sub(r"[^a-z0-9]", "", (s or "").lower())


# Generic freeplay / non-resource routines that are always allowed (no fake codes)
_FREEPLAY_DRILLS = [
    "Freeplay dribbling", "Freeplay aerial control", "Freeplay shooting",
    "Freeplay recoveries", "Replay review", "Custom training (your own pack)",
]


def allowed_drills(platform: str) -> list:
    """
    The ONLY drills the coach may reference — built from the verified catalog.
    Every entry has a real training-pack code or a real workshop map (PC only).
    Returns [{id, name, kind, resource}].
    """
    has_bm = platform.lower() in ("steam", "epic")
    out = []
    for _, packs in TRAINING_PACKS.items():
        for p in packs:
            out.append({"id": _slug(p["name"]), "name": p["name"],
                        "kind": "pack", "resource": p["code"]})
    if has_bm:
        for _, maps in WORKSHOP_MAPS.items():
            for m in maps:
                sid = m.get("steam_workshop_id", "")
                res = f"Workshop: {m['name']}" + (f" (ID {sid})" if sid else "")
                out.append({"id": _slug(m["name"]), "name": m["name"],
                            "kind": "workshop", "resource": res})
    for fp in _FREEPLAY_DRILLS:
        out.append({"id": _slug(fp), "name": fp, "kind": "freeplay", "resource": "Freeplay"})
    return out


def format_drill_catalog(platform: str) -> str:
    """A numbered, exact list of allowed drills for the prompt."""
    lines = ["ALLOWED DRILLS — you may ONLY use these. Copy the name + resource EXACTLY:"]
    for d in allowed_drills(platform):
        tag = {"pack": "[Training Pack]", "workshop": "[Workshop]", "freeplay": "[Freeplay]"}.get(d["kind"], "")
        lines.append(f"- {d['name']} {tag} → {d['resource']}")
    return "\n".join(lines)


def reconcile_drills(drills: list, platform: str) -> list:
    """
    Validate AI-produced drills against the verified catalog. Real drills are
    normalised to their authoritative name + resource (so embellished names like
    'Ground Zero Boost Routing' snap back to 'Ground Zero'); invented packs /
    workshop maps with no catalog match are dropped. Generic freeplay is kept.
    Claude-provided goal / movesMetric are preserved.
    """
    catalog = allowed_drills(platform)
    norms = [(_norm(c["name"]), c) for c in catalog]
    out, seen = [], set()
    for d in (drills or []):
        nn = _norm(d.get("name", ""))
        match = None
        if nn:
            for cn, c in norms:          # exact first
                if cn == nn:
                    match = c
                    break
            if not match:                # then containment either way
                for cn, c in norms:
                    if cn and (cn in nn or nn in cn):
                        match = c
                        break
        if match:
            if match["id"] in seen:
                continue
            seen.add(match["id"])
            out.append({"id": match["id"], "name": match["name"], "kind": match["kind"],
                        "resource": match["resource"], "goal": d.get("goal", ""),
                        "movesMetric": d.get("movesMetric", "")})
        elif d.get("kind") == "freeplay" or "freeplay" in (d.get("resource", "") or "").lower():
            key = _norm(d.get("name", ""))
            if key and key not in seen:
                seen.add(key)
                out.append({"id": _slug(d.get("name", "freeplay")), "name": d.get("name", "Freeplay"),
                            "kind": "freeplay", "resource": "Freeplay",
                            "goal": d.get("goal", ""), "movesMetric": d.get("movesMetric", "")})
        # else: hallucinated pack/workshop → dropped
    return out


def format_resources_for_prompt(platform: str, current_rank: str) -> str:
    """Return a concise resources block to include in the Claude prompt."""
    has_bakkesmod = platform.lower() in ("steam", "epic")
    tier = get_tier_label(current_rank or "Diamond I")
    skills = TIER_SKILLS.get(tier, TIER_SKILLS["Diamond"])
    lines = [f"**Platform:** {'PC — BakkesMod and Steam Workshop AVAILABLE' if has_bakkesmod else 'Console — official training packs ONLY (no workshop maps or BakkesMod)'}"]
    lines.append(f"\n**Tier focus ({tier}):**")
    lines.append("Priorities: " + " · ".join(skills["priorities"]))
    lines.append("Avoid: " + " · ".join(skills["avoid"]))
    lines.append(f"Daily anchor drill: {skills['weekly_drill']}")
    lines.append("\n**Training Packs (all platforms):**")
    for cat, packs in TRAINING_PACKS.items():
        for p in packs:
            lines.append(f"- {p['name']} — code: `{p['code']}`")
    if has_bakkesmod:
        lines.append("\n**Workshop Maps (PC only — load via BakkesMod → Workshop Maps):**")
        for cat, maps in WORKSHOP_MAPS.items():
            for m in maps:
                steam_id = m.get("steam_workshop_id", "")
                id_str = f" (Workshop ID: {steam_id})" if steam_id else ""
                lines.append(f"- **{m['name']}** by {m['author']}{id_str} — {m['use']}")
        lines.append("\n**BakkesMod plugins to install:**")
        for p in BAKKESMOD_PLUGINS:
            lines.append(f"- **{p['name']}** — {p['use']}")
    return "\n".join(lines)
