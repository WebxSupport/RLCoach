"""DEV_SEED fixtures — a fully-populated fake logged-in account for redesign work.

Activated by DEV_SEED=true at app startup (web_app refuses when SECURE_COOKIES=true,
the production indicator). Inserts fixture rows only — no routes, no auth changes;
the fixed session id behaves like any normal session. Idempotent: every write is an
upsert, so it is safe to run on every boot.

Login: dev@rlcoach.local / devseed · cookie session_id=devseed-session
"""
from __future__ import annotations
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

USER_ID = "devseed-user"
SESSION_ID = "devseed-session"
EMAIL = "dev@rlcoach.local"
PASSWORD = "devseed"
EOS_ID = "devseed-eos-0001"
NAME = "DevStriker"
PLAYER_ID = "epic:DevStriker"
PLAN_ID = "devseed-plan-1"
SERIES_ID = "devseed-series-1"
DATA_DIR = Path("data/devseed")


def _iso(dt: datetime) -> str:
    return dt.isoformat()


def _p(name: str, goals: int, shots: int, saves: int, score: int, me: bool = False) -> dict:
    return {"name": name, "is_me": me, "goals": goals, "shots": shots,
            "saves": saves, "score": score}


# ── matches (summary shape mirrors web_pipeline._process_replay_sync) ──────────

def _matches(now: datetime) -> list:
    """(match_id, summary, has_analysis) — newest played first, last 5 days."""
    specs = [
        # id, hours ago, map raw, map display, mode, my_team, my, opp, dc, analyzed
        ("devseed-m1",   5, "Stadium_P",      "DFH Stadium",    "3v3", "blue",   4, 3, 11, True),
        ("devseed-m2",  26, "cs_p",           "Champions Field","2v2", "blue",   2, 3,  9, False),
        ("devseed-m3",  30, "EuroStadium_P",  "Mannfield",      "2v2", "blue",   5, 2,  6, False),
        ("devseed-m4",  50, "TrainStation_P", "Urban Central",  "2v2", "orange", 3, 1,  7, False),
        ("devseed-m5",  55, "Park_P",         "Beckwith Park",  "2v2", "blue",   1, 2, 13, False),
        ("devseed-m6",  75, "Stadium_P",      "DFH Stadium",    "2v2", "blue",   4, 2,  8, False),
        ("devseed-m7", 100, "cs_p",           "Champions Field","2v2", "orange", 2, 4, 14, False),
        ("devseed-m8", 118, "EuroStadium_P",  "Mannfield",      "2v2", "blue",   3, 2, 10, False),
    ]
    teammates = ["NovaPulse", "QuickTap"]
    opponents = ["ShadowFade", "BoostBandit", "AerialAce"]
    out = []
    for mid, hrs, map_raw, map_disp, mode, my_team, my, opp, dc, analyzed in specs:
        n = int(mode[0])
        played = now - timedelta(hours=hrs)
        win = my > opp
        result = ("W" if win else ("L" if opp > my else "D")) + f"{my}-{opp}"
        mine = [_p(NAME, max(0, my - 1), my + 2, 1, 420 + my * 90, me=True)]
        mine += [_p(teammates[i], (1 if my > i else 0), 3, 2 - (i % 2), 300 + i * 40)
                 for i in range(n - 1)]
        theirs = [_p(opponents[i], (opp if i == 0 else 0) - (opp // 2 if i == 0 and n > 1 else 0),
                     4 - i, 1 + (i % 2), 380 - i * 60) for i in range(n)]
        blue, orange = (mine, theirs) if my_team == "blue" else (theirs, mine)
        blue_score, orange_score = (my, opp) if my_team == "blue" else (opp, my)
        summary = {
            "match_id": mid,
            "guid": mid,
            "folder": mid,
            "folder_path": str(DATA_DIR / mid),
            "map": map_raw,
            "map_display": map_disp,
            "mode": mode,
            "date": played.date().isoformat(),
            "played_at": int(played.timestamp()),
            "result": result,
            "win": win,
            "blue_score": blue_score,
            "orange_score": orange_score,
            "my_team": my_team,
            "duration_s": 312 + (hrs % 5) * 9,
            "double_commits": dc,
            "players_blue": blue,
            "players_orange": orange,
        }
        out.append((mid, summary, analyzed))
    return out


# ── analyzed-match dashboard (MATCH schema from claude_analyst.py) ──────────────

def _match_obj(now: datetime) -> dict:
    return {
        "meta": {"map": "DFH Stadium", "mode": "3v3", "playlist": "Ranked Standard",
                 "date": (now - timedelta(hours=5)).date().isoformat(),
                 "durationS": 339, "teamAName": "Blue", "teamBName": "Orange"},
        "result": {"win": True, "a": 4, "b": 3},
        "teamMetrics": {"possession": {"A": 51, "B": 49}, "netCoverage": {"A": 86, "B": 82}},
        "summary": {
            "headline": "Won 4–3 on late pressure and a strong kickoff record — but two of the three concedes came from double-commits, and DevStriker spent a seventh of the match with no boost.",
            "keyFindings": [
                "Possession was a coin flip (51/49) — the win came from converting second chances, not control.",
                "2 of 3 conceded goals (88s, 204s) were double-commits leaving the net open.",
                "DevStriker won the most kickoffs on the pitch (3 of 7) and none led to a concede.",
                "Boost starvation peaked mid-match — about 14% of the game below 10 boost.",
                "ShadowFade was the most dangerous opponent: 3 goals from 5 shots, all off turnovers.",
            ],
            "topFixes": [
                {"title": "Stop joining your teammate's challenge", "detail": "When NovaPulse commits, peel to back-post instead of doubling in.", "metric": "11 double-commits · 2 open-net goals → target < 6"},
                {"title": "Route small pads on rotation", "detail": "Grab the pad line through midfield instead of detouring to corner boost.", "metric": "time starved 14% → < 8%"},
                {"title": "Pick your shots", "detail": "Five of your twelve team shots were low-value pokes that handed possession back.", "metric": "xG per shot 0.28 → 0.35"},
            ],
        },
        "kpis": [
            {"label": "Result", "value": "4–3", "sub": "Win", "tone": "good"},
            {"label": "My rating", "value": "72.4", "sub": "/ 100", "tone": "good"},
            {"label": "Double-commits", "value": "11", "sub": "2 → open-net goals", "tone": "bad"},
            {"label": "Possession", "value": "51%", "sub": "51% vs 49%", "tone": ""},
            {"label": "Net covered", "value": "86%", "sub": "both concedes in the gap", "tone": "warn"},
        ],
        "players": [
            {"name": NAME, "team": "A", "isMe": True, "role": "Second-man engine",
             "rating": {"overall": 72.4, "ATT": 78, "DEF": 64, "POS": 76, "BST": 58, "ROT": 71, "SEC": 82},
             "core": {"goals": 2, "shots": 5, "assists": 1, "saves": 2, "score": 612},
             "d": {"conv": "40%", "def": 35.2, "neut": 33.1, "off": 31.7, "avgBoost": 44.6,
                   "starved": 14.1, "zero": 14.1, "goalside": 72.4, "ballchase": 3.4,
                   "longest": 2.6, "touches": 47, "giveaways": 0, "supersonic": 11.2,
                   "airPct": 9.8, "avgRecovery": 1.1},
             "summary": "The team's most balanced player and its engine through midfield. Two goals from five shots with a goal-line save in the final minute, and the cleanest touch map on Blue. The leaks are familiar: joined NovaPulse's challenge twice with the net open behind him, and ran dry on boost about a seventh of the match — both concedes trace back to one of those two habits. Kickoff work was genuinely strong, winning three of seven outright.",
             "strengths": ["Two-way output — 2 goals, 1 assist, 2 saves", "Best kickoff record in the lobby (3 won, 0 conceded)", "Clean ball security — no giveaways punished"],
             "weaknesses": ["Joined the double-commits at 88s and 204s", "Boost-starved 14% of the match", "Shot selection dips when behind — two low-value pokes"],
             "habit": "When your teammate commits, you cover — peeling to back-post on those two plays erases both open-net concedes."},
            {"name": "NovaPulse", "team": "A", "isMe": False, "role": "First-man aggressor",
             "rating": {"overall": 63.8, "ATT": 71, "DEF": 48, "POS": 62, "BST": 52, "ROT": 55, "SEC": 74},
             "core": {"goals": 1, "shots": 4, "assists": 2, "saves": 1, "score": 498},
             "d": {"conv": "25%", "def": 30.4, "neut": 31.5, "off": 38.1, "avgBoost": 41.2,
                   "starved": 16.8, "zero": 16.8, "goalside": 66.1, "ballchase": 6.2,
                   "longest": 3.8, "touches": 52, "giveaways": 0, "supersonic": 13.4,
                   "airPct": 12.1, "avgRecovery": 1.4},
             "summary": "Creates the most chaos on Blue and racked up two assists, but initiates almost every double-commit window by challenging without cover. Worst boost economy on the team and the longest chase spells — the 204s concede started with his overcommit. Still, his pressure forced the turnovers behind two of Blue's goals.",
             "strengths": ["Two assists — creates Blue's chances", "Relentless first-man pressure", "Forced the turnovers behind two Blue goals"],
             "weaknesses": ["Initiates most double-commit windows", "Boost-starved 17% of the match", "Longest ballchase spells on the team"],
             "habit": "Challenge only with cover behind you — half of Blue's defensive scrambles start with your free challenge."},
            {"name": "QuickTap", "team": "A", "isMe": False, "role": "Anchor",
             "rating": {"overall": 57.9, "ATT": 38, "DEF": 70, "POS": 73, "BST": 61, "ROT": 68, "SEC": 60},
             "core": {"goals": 1, "shots": 3, "assists": 0, "saves": 3, "score": 455},
             "d": {"conv": "33%", "def": 48.9, "neut": 29.4, "off": 21.7, "avgBoost": 49.8,
                   "starved": 8.2, "zero": 8.2, "goalside": 78.6, "ballchase": 2.1,
                   "longest": 1.9, "touches": 41, "giveaways": 0, "supersonic": 8.7,
                   "airPct": 6.9, "avgRecovery": 1.0},
             "summary": "The stay-home presence that kept the score respectable — three saves and the most disciplined positioning on the pitch. Offers little going forward and his clears are predictable, but on a team with two aggressive players he was the right shape. The one goal came from a backboard read.",
             "strengths": ["Three saves — most on Blue", "Most disciplined rotation in the lobby", "Healthy boost reserve all match"],
             "weaknesses": ["Minimal attacking threat (3 shots)", "Predictable middle clears", "Ball-watches on far-post crosses"],
             "habit": "Clear to the corners, not the middle — two Orange chances came straight off recycled central clears."},
            {"name": "ShadowFade", "team": "B", "isMe": False, "role": "Finisher (opp. MVP)",
             "rating": {"overall": 74.6, "ATT": 88, "DEF": 55, "POS": 70, "BST": 72, "ROT": 66, "SEC": 58},
             "core": {"goals": 3, "shots": 5, "assists": 0, "saves": 1, "score": 587},
             "d": {"conv": "60%", "def": 31.8, "neut": 30.2, "off": 38.0, "avgBoost": 51.3,
                   "starved": 6.4, "zero": 6.4, "goalside": 69.8, "ballchase": 4.0,
                   "longest": 2.4, "touches": 44, "giveaways": 0, "supersonic": 12.6,
                   "airPct": 11.4, "avgRecovery": 0.9},
             "summary": "The most clinical player on the pitch — all three Orange goals, every one off a Blue mistake. Lives off counters: barely defends, keeps boost high, and punishes the first loose touch. The lesson for Blue is that he never created a chance himself; deny the turnovers and he disappears.",
             "strengths": ["3 goals from 5 shots — ruthless off turnovers", "Best boost discipline in the lobby", "Fast, low recoveries"],
             "weaknesses": ["Contributes little defensively", "All output depends on opponent mistakes", "Drifts offside when Orange defends long spells"],
             "habit": "—"},
            {"name": "BoostBandit", "team": "B", "isMe": False, "role": "Midfield scrapper",
             "rating": {"overall": 61.2, "ATT": 52, "DEF": 58, "POS": 64, "BST": 66, "ROT": 60, "SEC": 55},
             "core": {"goals": 0, "shots": 4, "assists": 2, "saves": 2, "score": 470},
             "d": {"conv": "—", "def": 36.6, "neut": 34.8, "off": 28.6, "avgBoost": 47.9,
                   "starved": 9.1, "zero": 9.1, "goalside": 71.2, "ballchase": 3.6,
                   "longest": 2.2, "touches": 49, "giveaways": 0, "supersonic": 10.3,
                   "airPct": 9.2, "avgRecovery": 1.2},
             "summary": "Orange's connector — both assists and constant 50/50 presence through midfield. Doesn't threaten the net himself but keeps possession ticking and steals boost on every entry. Beat Blue to most loose balls in the middle third.",
             "strengths": ["Two assists feeding ShadowFade", "Wins the midfield scrap", "Steals boost in attack"],
             "weaknesses": ["No direct goal threat", "Loses track of the far post", "Overplays 50/50s when behind"],
             "habit": "—"},
            {"name": "AerialAce", "team": "B", "isMe": False, "role": "High-risk third",
             "rating": {"overall": 54.7, "ATT": 47, "DEF": 49, "POS": 55, "BST": 50, "ROT": 52, "SEC": 61},
             "core": {"goals": 0, "shots": 2, "assists": 1, "saves": 2, "score": 401},
             "d": {"conv": "—", "def": 39.5, "neut": 28.9, "off": 31.6, "avgBoost": 42.7,
                   "starved": 12.9, "zero": 12.9, "goalside": 65.4, "ballchase": 5.1,
                   "longest": 3.0, "touches": 38, "giveaways": 0, "supersonic": 9.8,
                   "airPct": 16.2, "avgRecovery": 1.7},
             "summary": "Spends the most time airborne of anyone in the lobby but lands the fewest of his attempts. Two saves kept Orange in it, yet his slow recoveries after missed aerials gave Blue the extra man for two of their goals.",
             "strengths": ["Brave shot-blocking — two saves", "Aerial presence forces rushed Blue clears"],
             "weaknesses": ["Misses most aerial commits", "Slowest recoveries on the pitch", "Boost-starved at the wrong moments"],
             "habit": "—"},
        ],
        "goals": [
            {"t": 41, "team": "A", "score": [1, 0], "scorer": NAME, "assist": "NovaPulse",
             "conceded": False, "faultType": "turnover", "fault": None,
             "reason": "NovaPulse's forecheck forced a loose BoostBandit clear; DevStriker buried the half-volley far post."},
            {"t": 88, "team": "B", "score": [1, 1], "scorer": "ShadowFade", "assist": "BoostBandit",
             "conceded": True, "faultType": "dc", "fault": "DevStriker — joined the challenge",
             "reason": "Both DevStriker and NovaPulse committed to the same corner ball; BoostBandit's centre found ShadowFade alone in front of an open net."},
            {"t": 132, "team": "A", "score": [2, 1], "scorer": "QuickTap", "assist": None,
             "conceded": False, "faultType": "individual", "fault": None,
             "reason": "QuickTap read the backboard bounce off AerialAce's missed clear and tapped in at the near post."},
            {"t": 204, "team": "B", "score": [2, 2], "scorer": "ShadowFade", "assist": None,
             "conceded": True, "faultType": "dc", "fault": "Team shape — both Blue forward",
             "reason": "NovaPulse overcommitted and DevStriker followed him in; ShadowFade walked the counter into an empty half."},
            {"t": 219, "team": "A", "score": [3, 2], "scorer": "NovaPulse", "assist": NAME,
             "conceded": False, "faultType": "turnover", "fault": None,
             "reason": "Straight from kickoff pressure — DevStriker's 50/50 win popped to NovaPulse for the finish."},
            {"t": 286, "team": "B", "score": [3, 3], "scorer": "ShadowFade", "assist": "AerialAce",
             "conceded": True, "faultType": "shot", "fault": None,
             "reason": "Genuine quality — AerialAce's high cross met by a powerful ShadowFade redirect; QuickTap was set and still beaten."},
            {"t": 327, "team": "A", "score": [4, 3], "scorer": NAME, "assist": "QuickTap",
             "conceded": False, "faultType": "turnover", "fault": None,
             "reason": "QuickTap's corner clear caught BoostBandit overplaying midfield; DevStriker outpaced the recovery and slotted the winner."},
        ],
        "kickoffs": [
            {"t": 0, "result": "neutral", "concededWithinS": None},
            {"t": 41, "result": "won", "concededWithinS": None},
            {"t": 88, "result": "neutral", "concededWithinS": None},
            {"t": 132, "result": "lost", "concededWithinS": None},
            {"t": 204, "result": "won", "concededWithinS": None},
            {"t": 219, "result": "neutral", "concededWithinS": None},
            {"t": 286, "result": "won", "concededWithinS": None},
            {"t": 327, "result": "neutral", "concededWithinS": None},
        ],
        "doubleCommits": [
            {"t": 34, "d": 2}, {"t": 61, "d": 1}, {"t": 84, "d": 4}, {"t": 117, "d": 2},
            {"t": 148, "d": 1}, {"t": 176, "d": 3}, {"t": 199, "d": 5}, {"t": 240, "d": 2},
            {"t": 271, "d": 1}, {"t": 305, "d": 2}, {"t": 322, "d": 1},
        ],
        "ballchaseTimeline": {
            "labels": [0, 30, 60, 90, 120, 150, 180, 210, 240, 270],
            "series": [
                {"name": NAME, "team": "A", "values": [1.2, 3.0, 5.8, 2.1, 1.4, 2.8, 6.5, 3.0, 1.8, 2.4]},
                {"name": "NovaPulse", "team": "A", "values": [2.0, 4.4, 7.9, 5.2, 3.8, 9.6, 12.4, 6.1, 4.0, 3.2]},
                {"name": "QuickTap", "team": "A", "values": [0.4, 1.1, 0.8, 1.6, 2.0, 1.2, 0.9, 2.4, 1.5, 0.7]},
                {"name": "ShadowFade", "team": "B", "values": [1.0, 0.8, 2.2, 3.6, 1.9, 1.1, 2.8, 4.2, 2.6, 1.4]},
                {"name": "BoostBandit", "team": "B", "values": [1.8, 2.6, 3.1, 2.4, 4.0, 3.3, 2.0, 3.8, 2.9, 2.1]},
                {"name": "AerialAce", "team": "B", "values": [0.9, 1.5, 2.8, 4.4, 3.1, 5.0, 3.6, 2.2, 4.8, 3.0]},
            ],
        },
        "patterns": [
            {"category": "rotation", "severity": "critical", "title": "Joining the teammate's challenge",
             "evidence": "On both concedes from open play (88s, 204s) you pushed in alongside NovaPulse instead of peeling off — 11 double-commit windows in total.",
             "consequence": "Two open-net goals against; turned recoverable defence into 3v1 counters.",
             "fix": "One goes, one covers — when NovaPulse moves to the ball you rotate to back-post, every time.",
             "metric": "double-commits 11 → < 6"},
            {"category": "boost", "severity": "major", "title": "Boost starvation through midfield",
             "evidence": "About 14% of the match below 10 boost, average 45 — the opponents' best player sat at 51 with only 6% starved.",
             "consequence": "Arrived at three defensive scrambles too slow to challenge, including the build-up to the 286s concede.",
             "fix": "Take the small-pad line through midfield on every rotation; keep a reserve of ~30 instead of detouring for corner boost.",
             "metric": "time starved 14% → < 8%"},
            {"category": "possession", "severity": "minor", "title": "Low-value pokes when chasing the game",
             "evidence": "Five of Blue's twelve shots were speculative pokes worth under a tenth of a goal each — most from your stick.",
             "consequence": "Handed Orange free possession in the 150–210s stretch where they equalised twice.",
             "fix": "If the shot isn't on, take a touch to a teammate or to space — possession beats a hopeful poke.",
             "metric": "xG per shot 0.28 → 0.35"},
        ],
        "shooting": {
            "teamA": {"shots": 12, "goals": 4, "xg": 3.4},
            "teamB": {"shots": 11, "goals": 3, "xg": 3.1},
            "me": {"shots": 5, "goals": 2, "xg": 1.6, "finishing": "as expected"},
        },
        "rotation": {"opportunities": 26, "excellent": 11, "acceptable": 8, "poor": 5, "critical": 2,
                     "score": 67.3,
                     "events": [
                         {"t": 88, "grade": "critical", "reasons": ["pushed up into a double-commit", "ball-side rotation (took the near post)"], "support_after": 820},
                         {"t": 204, "grade": "critical", "reasons": ["team conceded within the rotation window", "didn't rotate out — stayed forward"], "support_after": 990},
                         {"t": 148, "grade": "poor", "reasons": ["rotated through the middle"], "support_after": 1540},
                         {"t": 240, "grade": "poor", "reasons": ["collapsed onto teammate (940uu — overlap)"], "support_after": 940},
                         {"t": 120, "grade": "excellent", "reasons": ["clean back-post rotation with a pad grabbed"], "support_after": 2050},
                     ]},
        "touch": {
            "me": {"total": 47, "positive": 22, "neutral": 18, "negative": 7, "giveaways": 6,
                   "challenges": 14, "challenge_wins": 7, "first_touches": 19,
                   "first_touch_positive": 10, "first_touch_negative": 4,
                   "type_counts": {"controlled": 9, "clear": 11, "challenge": 14, "shot": 8, "pass": 3, "neutral": 2}},
            "challenges": {"count": 58, "by_type": {"immediate": 39, "delayed": 19},
                           "by_outcome": {"win": 21, "neutral": 17, "loss": 20}},
            "possession": {"blue": 51, "orange": 49},
        },
        "advanced": {
            "boost": {"small_pads": 61, "big_pads": 17, "wasted_overfill": 122, "steals": 3,
                      "avg_boost": 44.6, "economy_rating": 58.4},
            "recovery": {"aerials": 21, "avg_recovery_s": 1.1, "slow_landings": 4,
                         "speed_retention_pct": 84, "recovery_dodges": 16},
        },
        "lastMan": {"last_man_pct": 31, "avg_depth_when_last": 2800, "risky_push_pct": 18,
                    "deep_pct": 58, "mid_pct": 24, "high_pct": 18},
    }


# ── coaching plan (PLAN schema from coaching_engine.py + post-processing keys) ──
# Drills + codes verbatim from training_resources.TRAINING_PACKS; videos verbatim
# from learning_resources.VIDEO_CATALOG.

def _plan(now: datetime) -> dict:
    vids = [
        ("I3vtKPgzaz4", "How to Rotate in Under 6 Minutes... ROCKET LEAGUE", "SpookyLuke", "~6 min", ["rotation", "positioning", "support"]),
        ("d9T3LSW-2zc", "Shadow Defense Tutorial - A MUST KNOW to Rank Up in Rocket League", "HK Boba", "~10 min", ["defense", "shadow_defense", "challenge"]),
        ("eK3DLp-Yjwc", "How To Manage Your Boost Like A Pro Player (Tutorial)", "SquishyMuffinz", "~15 min", ["boost"]),
        ("R3k9O-k_XC0", "How To AERIAL In Rocket League from Beginner To Advanced", "Wayton Pilkin", "~20 min", ["aerial", "recovery"]),
        ("ko-QwAwhv18", "How to Dribble From BEGINNER to ADVANCED | ROCKET LEAGUE", "SpookyLuke", "~9 min", ["dribbling", "first_touch", "possession"]),
    ]
    return {
        "focus": "Stop joining your teammate's challenge — covering back-post instead erases most of the goals you concede.",
        "headline": "You're a solid Diamond II with above-average finishing and kickoffs. What's holding you back is defensive shape: double-commits hand opponents open nets, and boost starvation makes the scrambles worse. Fix those two habits and the climb to Champion I is mostly mechanical polish.",
        "winLoss": {
            "win": {"label": "Mannfield — W5-2",
                    "worked": ["Patient second-man play — you only committed with cover, and won 7 of 12 challenges",
                               "Shot quality: 5 goals on chances worth about 3.8 expected — clinical night",
                               "Boost stayed above 40 average; you were never caught dry in defence"],
                    "leaked": ["Two double-commit windows in the third minute nearly let them back in",
                               "Middle clears under pressure went straight back to their midfielder"]},
            "loss": {"label": "Champions Field — L2-4",
                     "causes": ["Three of the four concedes started with you and your partner on the same ball",
                                "Boost-starved 16% of the match — challenges arrived a step late",
                                "Forced pokes when 2-3 down gave away possession 12 times"],
                     "kept": ["Kickoff record stayed positive (3 won, 1 lost)",
                              "You still created both goals from clean first touches"]},
        },
        "strengths": [
            {"title": "Finishing", "detail": "40% conversion across the week — comfortably above Diamond average"},
            {"title": "Kickoffs", "detail": "Won 3 of 7 in your last game without conceding off any"},
            {"title": "Ball security", "detail": "Only 7 negative touches in 47 last match — clean under pressure"},
        ],
        "weaknesses": [
            {"title": "Double-commits", "detail": "11 per game average — 2 open-net concedes in your last match alone", "priority": True},
            {"title": "Boost starvation", "detail": "14% of match time below 10 boost vs the 6-8% of players a rank up", "priority": True},
            {"title": "Shot selection when behind", "detail": "Low-value pokes hand back possession in losing positions"},
        ],
        "week": [
            {"day": "Mon", "theme": "Shooting reset", "blocks": [
                {"name": "The Ultimate Warmup", "mins": 10, "kind": "warmup"},
                {"name": "Ground Shots", "mins": 20, "kind": "skill"},
                {"name": "Ranked 2v2 + replay review", "mins": 30, "kind": "application"}]},
            {"day": "Tue", "theme": "Defensive shape", "blocks": [
                {"name": "The Ultimate Warmup", "mins": 10, "kind": "warmup"},
                {"name": "Shadow Defense", "mins": 20, "kind": "skill"},
                {"name": "Ranked 2v2 — one goes, one covers", "mins": 30, "kind": "application"}]},
            {"day": "Wed", "theme": "First touch", "blocks": [
                {"name": "The Ultimate Warmup", "mins": 10, "kind": "warmup"},
                {"name": "First Touch Boot Camp", "mins": 20, "kind": "skill"},
                {"name": "Ranked 2v2 + replay review", "mins": 30, "kind": "application"}]},
            {"day": "Thu", "theme": "Rest", "blocks": [
                {"name": "Light freeplay (optional)", "mins": 15, "kind": "rest"}]},
            {"day": "Fri", "theme": "Aerial timing", "blocks": [
                {"name": "The Ultimate Warmup", "mins": 10, "kind": "warmup"},
                {"name": "Fast Aerials", "mins": 20, "kind": "skill"},
                {"name": "Ranked 2v2 + replay review", "mins": 30, "kind": "application"}]},
            {"day": "Sat", "theme": "Put it together", "blocks": [
                {"name": "The Ultimate Warmup", "mins": 10, "kind": "warmup"},
                {"name": "Ground Shots", "mins": 15, "kind": "skill"},
                {"name": "Ranked 2v2 — track your double-commits", "mins": 35, "kind": "application"}]},
            {"day": "Sun", "theme": "Rest", "blocks": []},
        ],
        "drills": [
            {"id": "ground-shots", "name": "Ground Shots", "kind": "pack",
             "resource": "Code: 6EB1-79B2-33B8-681C",
             "goal": "30 shots, 80%+ on target, no aerial takeoffs",
             "movesMetric": "Shot conversion"},
            {"id": "shadow-defense", "name": "Shadow Defense", "kind": "pack",
             "resource": "Code: 5CCE-FB29-7B05-A0B1",
             "goal": "10 reps staying goal-side without committing early",
             "movesMetric": "Double-commits and challenge timing"},
            {"id": "fast-aerials", "name": "Fast Aerials", "kind": "pack",
             "resource": "Code: 2BF7-DC0C-3D77-3B5E",
             "goal": "15 clean fast-aerial takeoffs reaching the ball before it drops",
             "movesMetric": "Aerial timing and recovery speed"},
            {"id": "the-ultimate-warmup", "name": "The Ultimate Warmup", "kind": "pack",
             "resource": "Code: FA24-B2B7-2E8E-193B",
             "goal": "Full pack once through before every session",
             "movesMetric": "Consistency"},
            {"id": "first-touch-boot-camp", "name": "First Touch Boot Camp", "kind": "pack",
             "resource": "Code: F43A-8231-0B8F-B9FA",
             "goal": "20 controlled first touches that keep the ball within a car length",
             "movesMetric": "Possession and giveaways"},
        ],
        "tracker": {
            "targetMmr": 1015,
            "weeklyTargets": [
                {"id": "double-commits", "label": "Double-commits per game", "from": 11, "to": 6, "unit": ""},
                {"id": "challenge-wins", "label": "Challenges won", "from": 41, "to": 55, "unit": "%"},
                {"id": "boost-starved", "label": "Time boost-starved", "from": 14, "to": 8, "unit": "%"},
            ],
        },
        "meta": {
            "player": NAME,
            "platform": "epic",
            "platformLabel": "PC — Epic Games",
            "hasBakkesmod": True,
            "gamemode": "2v2",
            "currentRank": "Diamond II",
            "targetRank": "Champion I",
            "currentMmr": 915,
            "targetMmr": 1015,
            "minsPerDay": 60,
            "daysPerWeek": 5,
            "rankGap": 2,
            "generated": now.date().isoformat(),
        },
        "habits": [
            {"category": "rotation", "severity": "critical", "title": "Joining the teammate's challenge",
             "evidence": "11 double-commit windows per game; both open-play concedes in your last match came from doubling in with your partner.",
             "consequence": "Open nets — opponents scored 2 free goals last match alone.",
             "fix": "One goes, one covers. When your partner moves to the ball, your job is back-post.",
             "metric": "double-commits 11 → < 6"},
            {"category": "boost", "severity": "major", "title": "Boost starvation through midfield",
             "evidence": "14% of match time below 10 boost — players a tier up sit at 6-8%.",
             "consequence": "Late, weak challenges in defence; scrambles you should win turn into concedes.",
             "fix": "Take the small-pad line on every rotation and keep a ~30 reserve.",
             "metric": "time starved 14% → < 8%"},
            {"category": "possession", "severity": "minor", "title": "Hopeful pokes when behind",
             "evidence": "Roughly 12 giveaways per loss vs 7 per win — most from rushed touches in losing positions.",
             "consequence": "Hands opponents free counters exactly when you can least afford them.",
             "fix": "If the shot isn't on, take a touch toward a teammate or open space instead.",
             "metric": "giveaways 12 → 8"},
        ],
        "trends": [
            {"metric": "Challenges won", "win": 58, "loss": 41, "better": "high"},
            {"metric": "Giveaways per game", "win": 7, "loss": 12, "better": "low"},
            {"metric": "Rotation quality", "win": 71, "loss": 58, "better": "high"},
            {"metric": "Chance quality (xG)", "win": 1.9, "loss": 1.1, "better": "high"},
        ],
        "resources": [
            {"title": t, "creator": c, "duration": d,
             "url": f"https://www.youtube.com/watch?v={vid}",
             "thumb": f"https://i.ytimg.com/vi/{vid}/mqdefault.jpg",
             "skills": sk}
            for vid, t, c, d, sk in vids
        ],
    }


# ── series report (SERIES schema from series_analyst.py + merged aggregate) ─────

def _series(now: datetime) -> dict:
    per_game = [
        {"n": 1, "result": "W3-2", "win": True, "map": "Mannfield", "goals": 2, "shots": 6,
         "saves": 2, "avg_boost": 51.2, "double_commits": 10, "air_time_pct": 8.9,
         "support_too_close_pct": 18.4, "challenge_win_pct": 57.1, "giveaways": 7, "xg": 1.8},
        {"n": 2, "result": "L2-4", "win": False, "map": "Champions Field", "goals": 1, "shots": 7,
         "saves": 1, "avg_boost": 42.8, "double_commits": 14, "air_time_pct": 10.2,
         "support_too_close_pct": 27.9, "challenge_win_pct": 38.5, "giveaways": 13, "xg": 1.1},
        {"n": 3, "result": "W4-2", "win": True, "map": "DFH Stadium", "goals": 3, "shots": 8,
         "saves": 2, "avg_boost": 49.6, "double_commits": 8, "air_time_pct": 9.1,
         "support_too_close_pct": 16.2, "challenge_win_pct": 60.0, "giveaways": 6, "xg": 2.2},
        {"n": 4, "result": "L1-2", "win": False, "map": "Beckwith Park", "goals": 1, "shots": 5,
         "saves": 3, "avg_boost": 44.1, "double_commits": 13, "air_time_pct": 8.4,
         "support_too_close_pct": 24.6, "challenge_win_pct": 42.9, "giveaways": 11, "xg": 1.0},
        {"n": 5, "result": "W3-1", "win": True, "map": "Urban Central", "goals": 2, "shots": 6,
         "saves": 1, "avg_boost": 52.7, "double_commits": 7, "air_time_pct": 9.6,
         "support_too_close_pct": 14.8, "challenge_win_pct": 58.3, "giveaways": 8, "xg": 1.7},
        {"n": 6, "result": "W5-2", "win": True, "map": "Mannfield", "goals": 3, "shots": 9,
         "saves": 2, "avg_boost": 53.4, "double_commits": 6, "air_time_pct": 9.9,
         "support_too_close_pct": 13.1, "challenge_win_pct": 61.5, "giveaways": 6, "xg": 2.4},
    ]
    return {
        "headline": "Your wins and losses are decided by one thing: whether you and your partner take the same ball.",
        "summary": "A solid 4–2 session with a clear pattern. In wins you average 7 double-commits and win 59% of your challenges; in losses those numbers collapse to 13-14 double-commits and barely 40% of challenges won. The mechanics are already there — the gap is purely about defensive patience.",
        "winVsLoss": [
            {"metric": "Challenges won (%)", "win": 59.2, "loss": 40.7,
             "insight": "In losses you challenge late and starved of boost — winning barely 4 in 10 means every 50/50 is a coin flip against you."},
            {"metric": "Double-commits", "win": 7.8, "loss": 13.5,
             "insight": "Nearly double in losses. This is the single biggest separator in your session."},
            {"metric": "Giveaways per game", "win": 6.8, "loss": 12.0,
             "insight": "When behind, you force hopeful touches — opponents scored most of their goals off these."},
            {"metric": "Avg boost", "win": 51.7, "loss": 43.5,
             "insight": "An 8-point boost gap between your wins and losses — pad discipline collapses when you tilt."},
        ],
        "consistency": [
            {"label": "Scoring is steady", "detail": "2-3 goals in every win, never blanked — your attacking output barely varies (1.0-2.4 xG)."},
            {"label": "Defence swings wildly", "detail": "Double-commits ranged 6 → 14 per game; your worst two defensive games were both losses."},
            {"label": "Bad games aren't clustered", "detail": "Losses came in games 2 and 4 with clean wins around them — this is a habit, not fatigue."},
        ],
        "recurringHabit": {
            "title": "Doubling onto your partner's challenge",
            "detail": "Every loss featured 13+ double-commit windows and your crowding-the-teammate share jumped from ~15% in wins to ~26% in losses. The pattern repeats across all six games: the moment your partner commits, you follow instead of covering.",
        },
        "trend": "improving — your last three games were your three cleanest (6-8 double-commits, 58%+ challenges won), and the session finished with your best game.",
        "topFixes": [
            {"title": "One goes, one covers", "detail": "When your partner moves to the ball, rotate to back-post. Treat any double-commit as a mistake even if it doesn't get punished.",
             "metric": "double-commits in losses 13.5 → < 8"},
            {"title": "Keep a 30-boost reserve", "detail": "Route small pads through midfield on every rotation so challenges arrive at speed.",
             "metric": "avg boost in losses 43.5 → 50"},
            {"title": "No hopeful pokes when behind", "detail": "Down a goal, prioritise possession: touch to a teammate or to space instead of a low-percentage shot.",
             "metric": "giveaways in losses 12 → 8"},
        ],
        "meta": {"player": NAME, "gamemode": "2v2", "generated": now.date().isoformat()},
        "record": {"games": 6, "wins": 4, "losses": 2},
        "averages": {"goals": 2.0, "shots": 6.8, "saves": 1.8, "assists": 0.8, "conv": 29.4,
                     "avg_boost": 49.0, "time_zero_s": 41.2, "def_third": 38.6, "off_third": 27.9,
                     "air_time_pct": 9.4, "double_commits": 9.7, "back_post_pct": 54.2,
                     "support_too_close_pct": 19.2, "touch_positive_pct": 44.8, "giveaways": 8.5,
                     "challenge_win_pct": 53.1, "xg": 1.7, "xg_diff": 0.3, "rotation_score": 66.4,
                     "poor_rotation_pct": 21.8, "boost_economy_rating": 61.2},
        "perGame": per_game,
    }


# ── tracker state ───────────────────────────────────────────────────────────────

def _tracker(now: datetime) -> dict:
    mmrs = [880, 884, 881, 890, 896, 893, 902, 908, 905, 914, 921, 927, 933, 940]
    log = [{"date": (now - timedelta(days=len(mmrs) - 1 - i)).date().isoformat(),
            "mmr": m, "rank": "Diamond II"} for i, m in enumerate(mmrs)]
    return {
        "mmrLog": log,
        "drillsDone": {"ground-shots": True, "shadow-defense": True},
        "weeklyDone": {"double-commits": 9, "challenge-wins": 47},
        "weeklyDaysDone": {"Mon": True, "Tue": True},
        "statMetrics": ["rotation_score", "challenge_win_pct", "giveaways"],
    }


# ── metric history (keys from phrasing.METRIC_CATALOGUE, gently improving) ──────

async def _reset_metric_history(db, session_id: str, now: datetime) -> None:
    await db._db.execute("DELETE FROM metric_history WHERE session_id=?", (session_id,))
    rot, chal, give, xg = 58.0, 41.0, 13.0, 1.05
    sources = ["match", "series", "plan", "match", "series",
               "match", "plan", "series", "match", "series"]
    for i, src in enumerate(sources):
        captured = _iso(now - timedelta(days=13.5 - i * 1.45))
        metrics = {"rotation_score": round(rot, 1), "challenge_win_pct": round(chal, 1),
                   "giveaways": round(give, 1), "xg": round(xg, 2)}
        await db._db.execute(
            "INSERT INTO metric_history (session_id, eos_account_id, source, captured_at, metrics)"
            " VALUES (?,?,?,?,?)",
            (session_id, EOS_ID, src, captured, json.dumps(metrics)),
        )
        rot += 1.6
        chal += 1.5
        give -= 0.55
        xg += 0.09
    await db._db.commit()


def _write_dashboard(folder: Path, now: datetime) -> None:
    from rlcoach.claude_analyst import TEMPLATE_PATH, _inject_into_template
    html = _inject_into_template(TEMPLATE_PATH.read_text(encoding="utf-8"), _match_obj(now))
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "dashboard.html").write_text(html, encoding="utf-8")


# ── entry point ─────────────────────────────────────────────────────────────────

async def seed(db) -> None:
    now = datetime.now(timezone.utc)

    user = await db.get_user_by_email(EMAIL)
    if not user:
        await db.create_user(USER_ID, EMAIL, PASSWORD)
        user_id = USER_ID
    else:
        user_id = user["user_id"]

    session = await db.get_session_by_user_id(user_id)
    if not session:
        await db.create_session(SESSION_ID, user_id)
        session_id = SESSION_ID
    else:
        session_id = session["session_id"]
        await db.activate_session(session_id)

    # Epic "connection" — token dict shaped like web_app.epic_poll builds it,
    # with fake values and future expiries (no PsyNet call will succeed; the UI
    # degrades to its no-live-ranks states, which is expected for fixtures).
    tokens = {
        "eos_access_token": "devseed-access-token",
        "eos_refresh_token": "devseed-refresh-token",
        "eos_expires_at": _iso(now + timedelta(hours=12)),
        "eos_refresh_expires_at": _iso(now + timedelta(days=30)),
        "account_id": EOS_ID,
        "display_name": NAME,
    }
    await db.connect_epic(session_id, EOS_ID, NAME, tokens)
    await db.update_player_id(session_id, PLAYER_ID)

    await db.upsert_profile(session_id, {
        "platform": "epic",
        "gamemode": "2v2",
        "team_size": 2,
        "current_rank": "Diamond II",
        "target_rank": "Champion I",
        "mins_per_day": 60,
        "days_per_week": 5,
        "display_name": NAME,
    })

    for match_id, summary, has_analysis in _matches(now):
        folder = DATA_DIR / match_id
        folder.mkdir(parents=True, exist_ok=True)
        await db.upsert_match(match_id, session_id, str(folder), summary, has_analysis)
    _write_dashboard(DATA_DIR / "devseed-m1", now)

    await db.save_coaching_plan(PLAN_ID, session_id, json.dumps(_plan(now)),
                                ["devseed-m3", "devseed-m7"])
    pst = await db.get_plan_state(session_id)
    if not pst["active"] or pst.get("plan_id") != PLAN_ID:
        await db.apply_plan_generated(session_id, PLAN_ID)

    await db.save_series_report(SERIES_ID, session_id, json.dumps(_series(now)), 6)
    await db.save_tracker(session_id, _tracker(now))
    await _reset_metric_history(db, session_id, now)
