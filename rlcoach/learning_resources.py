"""
Curated YouTube learning resources — popular, well-regarded RL tutorials mapped
to the skills/mechanics that show up in a player's weekly plan.

Title + creator are verified via YouTube's oEmbed endpoint (accurate attribution).
Durations are curated approximations ("~N min") — exact runtimes aren't reliably
fetchable, and these are evergreen videos; edit freely. `select_resources()` picks
the most relevant clips from the player's habits + weaknesses + plan focus + drills.

Coverage spans the full mechanic tree so any drill/skill in a plan maps to a clip:
fundamentals (rotation, positioning, game sense, boost, kickoffs, defending,
goalkeeping, shadow defense), core mechanics (fast aerial, air roll/car control,
dribbling, first touch, shooting, power, half-flip, wave dash, speed flip),
and advanced (air dribble, flicks, wall play, ceiling shots, redirects, flip
resets), plus warm-up routine.
"""
from __future__ import annotations

# Each entry: verified title + creator (oEmbed), the skills it teaches, an
# approximate runtime, and the YouTube id (thumbnail/link derived from it).
VIDEO_CATALOG = [
    # ── fundamentals / game sense ────────────────────────────────────────────
    {"id": "I3vtKPgzaz4", "title": "How to Rotate in Under 6 Minutes... ROCKET LEAGUE",
     "creator": "SpookyLuke", "duration": "~6 min", "skills": ["rotation", "positioning", "support"]},
    {"id": "OrrQQEHJ9Lc", "title": "The BEST Way to Learn GAME SENSE in Rocket League",
     "creator": "HorizonRL", "duration": "~12 min", "skills": ["game_sense", "positioning", "rotation"]},
    {"id": "eK3DLp-Yjwc", "title": "How To Manage Your Boost Like A Pro Player (Tutorial)",
     "creator": "SquishyMuffinz", "duration": "~15 min", "skills": ["boost"]},
    {"id": "nF68ltp01o0", "title": "Rocket League Academy - Kickoff",
     "creator": "Rocket League Academy", "duration": "~11 min", "skills": ["kickoff"]},
    {"id": "s3U6nRqXjiY", "title": "The BEST Rocket League Warmup Routine... No BS (2023)",
     "creator": "Dice", "duration": "~9 min", "skills": ["warmup", "training"]},
    # ── defending ────────────────────────────────────────────────────────────
    {"id": "d9T3LSW-2zc", "title": "Shadow Defense Tutorial - A MUST KNOW to Rank Up in Rocket League",
     "creator": "HK Boba", "duration": "~10 min", "skills": ["defense", "shadow_defense", "challenge"]},
    {"id": "Omk31pxWP-E", "title": "Advanced Goalkeeping | Rocket League Tutorial",
     "creator": "Kevpert", "duration": "~10 min", "skills": ["defense", "goalkeeping", "saves"]},
    # ── recovery / speed ──────────────────────────────────────────────────────
    {"id": "Y9__nS1FQeE", "title": "HOW TO HALF FLIP TUTORIAL! Fastest Way To Turn Around And Recover",
     "creator": "MizuRL", "duration": "~7 min", "skills": ["recovery", "half_flip"]},
    {"id": "_DSiejDocYw", "title": "How to WAVEDASH Rocket League",
     "creator": "slyk", "duration": "~4 min", "skills": ["recovery", "wavedash", "speed"]},
    {"id": "adTqmQlMRV0", "title": "How to SPEEDFLIP in Under 4 Minutes... ROCKET LEAGUE",
     "creator": "SpookyLuke", "duration": "~4 min", "skills": ["kickoff", "speed_flip", "recovery"]},
    # ── ball control / attacking ──────────────────────────────────────────────
    {"id": "ko-QwAwhv18", "title": "How to Dribble From BEGINNER to ADVANCED | ROCKET LEAGUE",
     "creator": "SpookyLuke", "duration": "~9 min", "skills": ["dribbling", "first_touch", "possession"]},
    {"id": "7KBxoXvrluw", "title": "How to Shoot With Power and Accuracy in Rocket League",
     "creator": "Virge", "duration": "~13 min", "skills": ["shooting", "first_touch"]},
    {"id": "96tNxK5vTsQ", "title": "MUSTY FLICK TUTORIAL | Learn How To Do The Flick No One Expects",
     "creator": "amustycow", "duration": "~8 min", "skills": ["flick", "dribbling", "shooting"]},
    {"id": "Ivyv0V9GFXA", "title": "How to Hit Redirects - Rocket League Tutorial",
     "creator": "Lofty_TM", "duration": "~9 min", "skills": ["redirect", "shooting", "aerial"]},
    # ── aerials / air control ─────────────────────────────────────────────────
    {"id": "R3k9O-k_XC0", "title": "How To AERIAL In Rocket League from Beginner To Advanced",
     "creator": "Wayton Pilkin", "duration": "~20 min", "skills": ["aerial", "recovery"]},
    {"id": "bYveY7WuDo0", "title": "How To PERFECT Your Aerial Car Control | Directional Air Roll Tutorial (PRO TIPS)",
     "creator": "SquishyMuffinz", "duration": "~12 min", "skills": ["aerial", "air_control", "air_dribble"]},
    {"id": "hxC9boyXEDI", "title": "How To AIR DRIBBLE In UNDER 5 Minutes... ROCKET LEAGUE (2024)",
     "creator": "SpookyLuke", "duration": "~5 min", "skills": ["air_dribble", "dribbling", "aerial"]},
    {"id": "QUbufQ55qOg", "title": "How to Improve Your Wall Play! | Learn to Play Rocket League",
     "creator": "Grifflicious", "duration": "~10 min", "skills": ["wall_play", "positioning"]},
    {"id": "PkIupX66sF8", "title": "Beginner to Advanced Rocket League Ceiling Shot Tutorial",
     "creator": "Thanovic", "duration": "~12 min", "skills": ["ceiling_shot", "aerial"]},
    {"id": "9C5w8mzy6q4", "title": "How To FLIP RESET In Rocket League from Beginner To Advanced",
     "creator": "Wayton Pilkin", "duration": "~18 min", "skills": ["flip_reset", "aerial", "air_dribble"]},
]

# pattern.category → skill tags
_CATEGORY_TAGS = {
    "rotation": ["rotation", "game_sense"],
    "positioning": ["rotation", "positioning", "game_sense"],
    "possession": ["dribbling", "first_touch", "flick"],
    "challenge": ["shadow_defense", "defense"],
    "boost": ["boost"],
    "defense": ["shadow_defense", "defense", "goalkeeping", "recovery"],
}

# keyword (substring, lowercase) → skill tag, scanned over weakness/focus/drill text
_KEYWORD_TAGS = [
    ("speed flip", "speed_flip"), ("speedflip", "speed_flip"), ("speed-flip", "speed_flip"),
    ("wave dash", "wavedash"), ("wavedash", "wavedash"),
    ("half flip", "half_flip"), ("half-flip", "half_flip"),
    ("flip reset", "flip_reset"),
    ("air dribble", "air_dribble"),
    ("air roll", "air_control"), ("air-roll", "air_control"), ("car control", "air_control"),
    ("aerial control", "air_control"), ("aerial", "aerial"),
    ("ceiling", "ceiling_shot"), ("redirect", "redirect"),
    ("musty", "flick"), ("flick", "flick"), ("45", "flick"),
    ("wall", "wall_play"),
    ("recover", "recovery"), ("reset into", "recovery"), ("landing", "recovery"),
    ("rotat", "rotation"), ("back post", "rotation"), ("back-post", "rotation"),
    ("support", "rotation"), ("overcommit", "rotation"), ("ball-side", "rotation"),
    ("ball side", "rotation"), ("position", "positioning"),
    ("game sense", "game_sense"), ("gamesense", "game_sense"), ("decision", "game_sense"),
    ("awareness", "game_sense"), ("reads", "game_sense"),
    ("challeng", "shadow_defense"), ("50/50", "shadow_defense"), ("shadow", "shadow_defense"),
    ("defend", "defense"), ("defens", "defense"), ("last man", "defense"), ("last-man", "defense"),
    ("save", "goalkeeping"), ("goalie", "goalkeeping"), ("goalkeep", "goalkeeping"), ("net", "goalkeeping"),
    ("boost", "boost"), ("starv", "boost"), ("pad", "boost"),
    ("first touch", "first_touch"), ("first-touch", "first_touch"),
    ("dribbl", "dribbling"), ("ball control", "dribbling"), ("giveaway", "dribbling"),
    ("shot", "shooting"), ("shoot", "shooting"), ("finish", "shooting"), ("xg", "shooting"),
    ("power", "shooting"), ("accuracy", "shooting"),
    ("kickoff", "kickoff"), ("kick-off", "kickoff"),
    ("warm", "warmup"), ("routine", "warmup"), ("training pack", "training"), ("freeplay", "training"),
]


def _tags_from_text(text: str) -> set:
    t = (text or "").lower()
    return {tag for kw, tag in _KEYWORD_TAGS if kw in t}


def select_resources(habits: list = None, weaknesses: list = None,
                     focus: str = "", drills: list = None, max_n: int = 8) -> list:
    """
    Pick the most relevant tutorials for this player's plan.

    Signals (weighted): habit categories (strongest) > weakness text > plan drills
    > focus line. Videos are ranked by how many of those tags they teach. Falls
    back to core fundamentals if nothing matches.
    """
    weight: dict = {}

    def _add(tags, w):
        for tag in tags:
            weight[tag] = weight.get(tag, 0) + w

    for h in (habits or []):
        _add(_CATEGORY_TAGS.get((h.get("category") or "").lower(), []), 3)
    for w in (weaknesses or []):
        txt = w if isinstance(w, str) else (w.get("title", "") + " " + w.get("detail", ""))
        _add(_tags_from_text(txt), 2)
    for d in (drills or []):
        txt = " ".join(str(d.get(k, "")) for k in ("name", "movesMetric", "goal", "resource")) \
            if isinstance(d, dict) else str(d)
        _add(_tags_from_text(txt), 3)   # a drill is an explicit "teach me this"
    _add(_tags_from_text(focus), 1)

    if not weight:
        weight = {"rotation": 1, "boost": 1, "shooting": 1, "game_sense": 1}

    scored = []
    for v in VIDEO_CATALOG:
        s = sum(weight.get(tag, 0) for tag in v["skills"])
        s += weight.get(v["skills"][0], 0)   # double-weight the video's PRIMARY skill (what it's really about)
        if s > 0:
            scored.append((s, v))
    scored.sort(key=lambda x: x[0], reverse=True)

    out, seen = [], set()
    for _, v in scored:
        if v["id"] in seen:
            continue
        seen.add(v["id"])
        out.append({
            "title": v["title"], "creator": v["creator"], "duration": v["duration"],
            "url": f"https://www.youtube.com/watch?v={v['id']}",
            "thumb": f"https://i.ytimg.com/vi/{v['id']}/mqdefault.jpg",
            "skills": v["skills"],
        })
        if len(out) >= max_n:
            break
    return out
