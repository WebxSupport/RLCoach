"""
Curated YouTube learning resources — popular, well-regarded RL tutorials mapped
to the skills/mechanics that show up in a player's weekly plan.

Title + creator are verified via YouTube's oEmbed endpoint (accurate attribution).
Durations are curated approximations ("~N min") — exact runtimes aren't reliably
fetchable, and these are evergreen videos; edit freely. `select_resources()` picks
the most relevant clips from the player's habits + weaknesses + plan focus.
"""
from __future__ import annotations

# Each entry: verified title + creator (via oEmbed), the skills it teaches, and an
# approximate runtime. `id` is the YouTube video id (thumbnail/link derived from it).
VIDEO_CATALOG = [
    {"id": "I3vtKPgzaz4", "title": "How to Rotate in Under 6 Minutes... ROCKET LEAGUE",
     "creator": "SpookyLuke", "duration": "~6 min",
     "skills": ["rotation", "positioning", "support"]},
    {"id": "R3k9O-k_XC0", "title": "How To AERIAL In Rocket League from Beginner To Advanced",
     "creator": "Wayton Pilkin", "duration": "~20 min",
     "skills": ["aerial", "recovery"]},
    {"id": "hxC9boyXEDI", "title": "How To AIR DRIBBLE In UNDER 5 Minutes... ROCKET LEAGUE (2024)",
     "creator": "SpookyLuke", "duration": "~5 min",
     "skills": ["air_dribble", "dribbling", "aerial"]},
    {"id": "nF68ltp01o0", "title": "Rocket League Academy - Kickoff",
     "creator": "Rocket League Academy", "duration": "~11 min",
     "skills": ["kickoff"]},
    {"id": "d9T3LSW-2zc", "title": "Shadow Defense Tutorial - A MUST KNOW to Rank Up in Rocket League",
     "creator": "HK Boba", "duration": "~10 min",
     "skills": ["defense", "shadow_defense", "challenge"]},
    {"id": "Y9__nS1FQeE", "title": "HOW TO HALF FLIP TUTORIAL! Fastest Way To Turn Around And Recover",
     "creator": "MizuRL", "duration": "~7 min",
     "skills": ["recovery", "half_flip"]},
    {"id": "7KBxoXvrluw", "title": "How to Shoot With Power and Accuracy in Rocket League",
     "creator": "Virge", "duration": "~13 min",
     "skills": ["shooting", "first_touch"]},
    {"id": "eK3DLp-Yjwc", "title": "How To Manage Your Boost Like A Pro Player (Tutorial)",
     "creator": "SquishyMuffinz", "duration": "~15 min",
     "skills": ["boost"]},
    {"id": "ko-QwAwhv18", "title": "How to Dribble From BEGINNER to ADVANCED | ROCKET LEAGUE",
     "creator": "SpookyLuke", "duration": "~9 min",
     "skills": ["dribbling", "first_touch", "possession"]},
]

# pattern.category → skill tags
_CATEGORY_TAGS = {
    "rotation": ["rotation"],
    "positioning": ["rotation", "positioning"],
    "possession": ["dribbling", "first_touch"],
    "challenge": ["shadow_defense", "defense"],
    "boost": ["boost"],
    "defense": ["shadow_defense", "defense", "recovery"],
}

# keyword (substring, lowercase) → skill tag, scanned over weakness/focus/drill text
_KEYWORD_TAGS = [
    ("air dribble", "air_dribble"), ("aerial", "aerial"), ("half flip", "half_flip"),
    ("recover", "recovery"), ("reset", "recovery"), ("landing", "recovery"),
    ("rotat", "rotation"), ("back post", "rotation"), ("back-post", "rotation"),
    ("support", "rotation"), ("overcommit", "rotation"), ("ball-side", "rotation"),
    ("ball side", "rotation"), ("position", "positioning"),
    ("challeng", "shadow_defense"), ("50/50", "shadow_defense"), ("shadow", "shadow_defense"),
    ("defend", "defense"), ("defens", "defense"), ("last man", "defense"), ("last-man", "defense"),
    ("boost", "boost"), ("starv", "boost"), ("pad", "boost"),
    ("first touch", "first_touch"), ("first-touch", "first_touch"),
    ("dribbl", "dribbling"), ("ball control", "dribbling"), ("giveaway", "dribbling"),
    ("shot", "shooting"), ("shoot", "shooting"), ("finish", "shooting"), ("xg", "shooting"),
    ("kickoff", "kickoff"), ("kick-off", "kickoff"),
]


def _tags_from_text(text: str) -> set:
    t = (text or "").lower()
    return {tag for kw, tag in _KEYWORD_TAGS if kw in t}


def select_resources(habits: list = None, weaknesses: list = None,
                     focus: str = "", max_n: int = 5) -> list:
    """
    Pick the most relevant tutorials for this player's plan.

    Tags are gathered from the detected habit categories (strongest signal) and
    from keyword-scanning the weakness/focus text, then videos are ranked by how
    many of those tags they teach. Falls back to core fundamentals if nothing matches.
    """
    weight: dict = {}
    for h in (habits or []):
        for tag in _CATEGORY_TAGS.get((h.get("category") or "").lower(), []):
            weight[tag] = weight.get(tag, 0) + 3   # habits are the priority
    for w in (weaknesses or []):
        txt = w if isinstance(w, str) else (w.get("title", "") + " " + w.get("detail", ""))
        for tag in _tags_from_text(txt):
            weight[tag] = weight.get(tag, 0) + 2
    for tag in _tags_from_text(focus):
        weight[tag] = weight.get(tag, 0) + 1

    if not weight:
        weight = {"rotation": 1, "boost": 1, "shooting": 1}   # sensible fundamentals

    scored = []
    for v in VIDEO_CATALOG:
        s = sum(weight.get(tag, 0) for tag in v["skills"])
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
