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
#
# All codes verified against the r/RocketLeagueSchool master list, the kirfyK
# Ultimate Training Program, and the published routines of SunlessKhan, Thanovic,
# Wayton Pilkin, Musty, Poquito, and Kevpert.
#
#   code="…"      → verified 16-char in-game code (Main Menu → Training → Custom → Browse → Enter Code)
#   default=True  → built-in Psyonix pack (Free Play → Training → <name>)
TRAINING_PACKS = {
    "shooting": [
        {"name": "Ground Shots",               "creator": "Poquito",            "code": "6EB1-79B2-33B8-681C"},
        {"name": "Wall Shots",                  "creator": "Poquito",            "code": "9F6D-4387-4C57-2E4B"},
        {"name": "Shooting Consistency",        "creator": "Wayprotein | A&M",  "code": "4912-A5C9-9A56-555D"},
        {"name": "Shots You Shouldn't Miss",    "creator": "RLC | Fickle Platypus", "code": "42BF-686D-E047-574B"},
        {"name": "Powershot Practice",          "creator": "Skogur",             "code": "C9E4-0F05-B71A-C322"},
        {"name": "Half-Volley Shots",           "creator": "Rob Da Car",         "code": "B0F8-0116-C10B-45F0"},
        {"name": "Power Shots Pack",            "creator": "Grifflicious",       "code": "5972-C9A0-7045-379E"},
        {"name": "Striker — All-Star",          "default": True},
    ],
    "aerials": [
        {"name": "Aerial Shots — Pass",         "creator": "Poquito",            "code": "C7E0-9E0B-B739-A899"},
        {"name": "Aerial Shots — Redirects",    "creator": "Poquito",            "code": "8D93-C997-0ACD-8416"},
        {"name": "Kevpert Aerial Car Control",  "creator": "Kevpert",            "code": "A3E1-92C2-8757-4195"},
        {"name": "Backboard Therapy",           "creator": "Wayprotein | A&M",  "code": "D7F8-FD53-98D1-DAFE"},
        {"name": "Double Tap Playground",       "creator": "Wayprotein | A&M",  "code": "CAFC-FB3E-3C0F-B8F1"},
        {"name": "Double Jump Aerials",         "creator": "Doomsee",            "code": "F269-B159-0BAC-AC2E"},
        {"name": "Aerial off Wall",             "creator": "Wheelchair {LFflegs}","code": "5BFE-60D6-0D59-79F2"},
        {"name": "Fast Aerials",                "creator": "IcyyMike",           "code": "2BF7-DC0C-3D77-3B5E"},
        {"name": "Aerial — All-Star",           "default": True},
        # Wayton Pilkin 5-stage aerial progression
        {"name": "Wayton Aerials Level 1 — How to Aerial",   "creator": "Waytoney", "code": "AE34-6C1E-8CCD-D8A5"},
        {"name": "Wayton Aerials Level 2 — Reading the Ball","creator": "Waytoney", "code": "876E-1C19-0086-8232"},
        {"name": "Wayton Aerials Level 3 — High Aerials",    "creator": "Waytoney", "code": "76CD-1B72-20D9-53DC"},
        {"name": "Wayton Aerials Level 4 — Angles",          "creator": "Waytoney", "code": "04A6-F117-971F-3625"},
        {"name": "Wayton Aerials Level 5 — Sudden Aerials",  "creator": "Waytoney", "code": "F001-A333-AAEB-2786"},
    ],
    "saves_defense": [
        {"name": "Uncomfortable Saves",         "creator": "unknown",            "code": "5CB2-6D82-1B54-47B7"},
        {"name": "Shadow Defense",              "creator": "Orangepie",          "code": "5CCE-FB29-7B05-A0B1"},
        {"name": "Diamond Defense",             "creator": "LLexis",             "code": "CEBB-085B-D05D-920B"},
        {"name": "Defense Needed for Diamond",  "creator": "CBELL",              "code": "2195-C0DC-6CAB-B547"},
        {"name": "Protein Wall Clears",         "creator": "Wayprotein",         "code": "0A7E-C7C8-DE7C-28CA"},
        {"name": "Saves",                       "creator": "Poquito",            "code": "2E23-ABD5-20C6-DBD4"},
        {"name": "Defensive Backboard Reads",   "creator": "Nathan",             "code": "DABC-E5BB-F347-A7BC"},
        {"name": "Overhead Goalie 2",           "creator": "Thanovic",           "code": "17F2-309A-8FA5-13BE"},
        {"name": "Goalie — All-Star",           "default": True},
    ],
    "dribbling": [
        {"name": "First Touch Boot Camp",       "creator": "Poquito",            "code": "F43A-8231-0B8F-B9FA"},
        {"name": "First Touch Prac",            "creator": "Ostyn",              "code": "4B9D-F3A8-DF18-5EC1"},
        {"name": "Catch and Dribble",           "creator": "T.TV/Barnayyyyy",   "code": "86B0-EC72-7185-844C"},
        {"name": "Catch and Dribble — Hard",    "creator": "Lazord",             "code": "772F-E563-3F9F-0EC8"},
        {"name": "Biddle's Catches",            "creator": "DN | Biddles",       "code": "3EA9-533B-4329-67B3"},
        {"name": "Drift Catch Training",        "creator": "King Ranny",         "code": "2258-FBD1-2CAE-0246"},
        {"name": "Mawzy Flick",                 "creator": "Grifflicious",       "code": "733F-17F2-025E-DCBE"},
    ],
    "speed_recovery": [
        {"name": "Musty Speedflip Kickoff Test","creator": "Musty",              "code": "A503-264C-A7EB-D282"},
        {"name": "Recovery Training",           "creator": "Slykau",             "code": "DA42-75B1-0469-8A0F"},
        {"name": "Speedflip Catches",           "creator": "Lazord",             "code": "20E9-AEAF-E135-0CA7"},
        {"name": "Air & Wall Dribbles",         "creator": "Jakerl / TheJRobinson", "code": "9D87-258C-3C05-6FA9"},
        {"name": "Ceiling Shots",               "creator": "Wayprotein | A&M",  "code": "AFC9-2CCC-95EC-D9D4"},
        {"name": "Flip Reset Training",         "creator": "Grifflicious",       "code": "1E87-21E8-D5A4-2179"},
        {"name": "Basic Air Dribbles",          "creator": "Wayton",             "code": "1F27-4030-7FDE-B4D5"},
        {"name": "Kickoff",                     "creator": "kirfyK",             "code": "2F25-C7AD-8E03-19BC"},
    ],
    "warmup": [
        {"name": "The Ultimate Warmup",         "creator": "Hinata",             "code": "FA24-B2B7-2E8E-193B"},
        {"name": "Gold",                        "creator": "Thanovic",           "code": "CA9B-FF51-1348-C574"},
        {"name": "Biddle's Consistency",        "creator": "Biddles",            "code": "55C9-36FE-613D-7F12"},
        {"name": "Plat to Diamond",             "creator": "Inexorable",         "code": "88AD-945E-212F-EF18"},
        {"name": "Complete Warm-Up x SpookLuke","creator": "Poquito",            "code": "A2D5-7908-A70B-EDA9"},
        {"name": "Diamond Pack",                "creator": "Psyonix",            "code": "853D-A180-A66D-8137"},
    ],
}


def _pack_resource(p: dict) -> str:
    """How the user loads a training pack — code, built-in, or browser search."""
    if p.get("code"):
        return f"Code: {p['code']}"
    if p.get("default"):
        return f"Free Play → Training → {p['name']}"
    c = p.get("creator")
    return f"Training browser: search \"{p['name']}\"" + (f" by {c}" if c else "")


# ── Workshop maps (PC/BakkesMod only) ─────────────────────────────────────────
# Sourced from r/RocketLeagueSchool master list and the SunlessKhan / kirfyK routines.
# All maps have real, named authors. steam_workshop_id provided where verified.
# Without an ID, load via BakkesMod → Workshop → search by map name.

WORKSHOP_MAPS = {
    "aerial_rings": [
        {"name": "Lethamyr's Giant Rings Map", "author": "Leth",
         "steam_workshop_id": "1565535901",
         "use": "The original Rings map — every aerial control axis. Widely called the best workshop map ever made"},
        {"name": "Rings Reverse", "author": "Lethamyr",
         "steam_workshop_id": "1572824364",
         "use": "Backwards rings — pure air-direction and car-rotation control"},
        {"name": "Rings Mega", "author": "Lethamyr",
         "steam_workshop_id": "1600575985",
         "use": "Comprehensive rings (width + height) — best daily aerial warm-up"},
        {"name": "Speed Jump: Rings 1", "author": "dmc",
         "use": "Timed Rings course — adds a pace challenge to aerial control"},
        {"name": "Speed Jump: Rings 2", "author": "dmc",
         "use": "Continuation of Speed Jump Rings — harder routes"},
    ],
    "ball_control": [
        {"name": "Dribbling Challenge 2", "author": "Lethamyr",
         "steam_workshop_id": "1489736853",
         "use": "Lethamyr's dribble obstacle course — foundational close ball control"},
        {"name": "Dribbling Challenge #2", "author": "French Fries",
         "use": "The community staple ground-dribble challenge — used by everyone from Gold to GC"},
        {"name": "Dribbling Challenge 1.2", "author": "French Fries",
         "use": "The original tiered dribbling challenge — entry point for ground control"},
        {"name": "Noob Dribble", "author": "dmc",
         "use": "Beginner-friendly intro to keeping the ball on the car"},
    ],
    "air_dribble": [
        {"name": "Air Dribble Challenge", "author": "Gidek",
         "use": "The canonical tiered air-dribble map — works through progressively harder scenarios"},
        {"name": "Air Dribble Hoops", "author": "tjbrother",
         "use": "Air-dribbling through hoops — adds spatial precision to the mechanic"},
    ],
    "movement_speed": [
        {"name": "Speed Jump 2", "author": "dmc",
         "use": "The second-generation Speed Jump precision-flight course"},
        {"name": "Speed Jump: Trials 1", "author": "dmc",
         "use": "Timed precision flight trials — car control at speed"},
        {"name": "Hornet's Nest", "author": "dmc",
         "use": "Advanced recovery training in a chaotic environment — recommended by SSL-mechanic guides"},
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
        "weekly_drill": "Freeplay dribbling (5 min) → Powershot Practice (Skogur, Code: C9E4-0F05-B71A-C322) → Goalie All-Star",
    },
    "Gold–Platinum": {
        "priorities": ["Boost pad routing on rotation", "Aerial introduction (low aerials)", "One-goes-one-covers rotation basics", "Reading deflections"],
        "avoid": ["Double-committing with teammate", "Clearing straight up the middle"],
        "weekly_drill": "Lethamyr's Giant Rings Map (workshop) + Wayton Aerials Level 1 (Code: AE34-6C1E-8CCD-D8A5) + Uncomfortable Saves (Code: 5CB2-6D82-1B54-47B7)",
    },
    "Diamond": {
        "priorities": ["Double-commit elimination", "Boost economy discipline (average ≥ 45)", "50/50 reads and fakes", "Wide rotation paths"],
        "avoid": ["Jumping into challenges without a backup plan", "Ball-watching from the back"],
        "weekly_drill": "Rings Mega (workshop) + Dribbling Challenge #2 (French Fries, workshop) + Aerial Shots — Redirects (Poquito, Code: 8D93-C997-0ACD-8416)",
    },
    "Champion": {
        "priorities": ["Advanced rotation (third-man cover)", "Recovery after hitting the ball", "Mid-air redirect decisions", "Fake challenges"],
        "avoid": ["Passive 'waiting' — GC-level opponents punish passive play", "Predictable shot directions"],
        "weekly_drill": "Musty Speedflip Kickoff Test (Code: A503-264C-A7EB-D282) + Double Tap Playground (Code: CAFC-FB3E-3C0F-B8F1) + Biddle's Consistency (Code: 55C9-36FE-613D-7F12)",
    },
    "Grand Champion+": {
        "priorities": ["Fast aerials off any surface", "Pressure and stall timing", "Advanced rotation reads", "Demo and bump strategy"],
        "avoid": ["Unnecessary 50/50s with shape already good", "Over-rotating"],
        "weekly_drill": "The Ultimate Warmup (Code: FA24-B2B7-2E8E-193B) + Air Dribble Challenge (workshop) + full matches with replay review",
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
                        "kind": "pack", "resource": _pack_resource(p)})
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
            lines.append(f"- {p['name']} — {_pack_resource(p)}")
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
