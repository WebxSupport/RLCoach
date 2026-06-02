"""
Replay parser — wraps sprocket_carball (maintained carball fork) behind a
clean interface. To swap backends replace _parse_with_carball without
touching anything in metrics, events, or digest.

RL coordinate system:
  X: ±4096 (width), Y: ±5120 (length), Z: 0–2044 (height)
  Blue defends Y ≈ -5120, Orange defends Y ≈ +5120.
"""
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import pandas as pd

log = logging.getLogger(__name__)


# ── Data structures ────────────────────────────────────────────────────────────

@dataclass
class PlayerMeta:
    name: str
    platform_id: str   # "steam:76561198xxxxxx"
    team: str          # "blue" | "orange"
    is_orange: bool
    goals: int = 0
    shots: int = 0
    assists: int = 0
    saves: int = 0
    score: int = 0


@dataclass
class GoalEvent:
    frame: int
    time_s: float
    scorer_name: str
    scoring_team: str  # "blue" | "orange"


@dataclass
class HitEvent:
    frame: int
    time_s: float
    player_name: str
    is_shot: bool = False
    is_save: bool = False
    is_goal: bool = False
    team: Optional[str] = None  # filled in by metrics layer


@dataclass
class DemoEvent:
    frame: int
    time_s: float
    attacker_name: str
    victim_name: str


@dataclass
class ParsedReplay:
    match_id: str
    map_name: str
    date: str           # ISO-8601
    playlist: str
    duration_s: float
    fps: float
    team_size: int
    blue_score: int
    orange_score: int
    players: list = field(default_factory=list)   # list[PlayerMeta]
    goals: list = field(default_factory=list)     # list[GoalEvent]
    hits: list = field(default_factory=list)      # list[HitEvent]
    demos: list = field(default_factory=list)     # list[DemoEvent]
    frame_df: Optional[pd.DataFrame] = None
    warnings: list = field(default_factory=list)


# ── carball backend ────────────────────────────────────────────────────────────

def _platform_id_str(player_id_proto) -> str:
    try:
        platform = str(player_id_proto.platform).lower().replace("platform.", "")
        return f"{platform}:{player_id_proto.id}"
    except Exception:
        return str(player_id_proto)


def _parse_with_carball(replay_path: Path, match_id: str) -> ParsedReplay:
    try:
        import carball
    except ImportError:
        raise RuntimeError("No carball package found. Run: pip install sprocket_carball")

    # sprocket_carball (PyPI) installs as the 'carball' module and exposes
    # analyze_replay_file() rather than analyze_replay().
    try:
        manager = carball.analyze_replay_file(str(replay_path))
    except AttributeError:
        # Older API shape fallback
        from carball.json_parser.game import Game
        from carball.analysis.analysis_manager import AnalysisManager
        game = Game()
        game.initialize(replay_path=str(replay_path))
        manager = AnalysisManager(game=game)
        manager.create_analysis()

    proto = manager.get_proto()
    df: pd.DataFrame = manager.get_data_frame()

    # ── Metadata ──────────────────────────────────────────────────────────────
    meta = proto.game_metadata
    map_name = getattr(meta, "map", "Unknown") or "Unknown"
    date_str = str(getattr(meta, "date", "")) or ""
    playlist = str(getattr(meta, "playlist", "")) or ""

    blue_score = orange_score = 0
    for team in proto.teams:
        if team.is_orange:
            orange_score = team.score
        else:
            blue_score = team.score

    if df is not None and len(df) > 0:
        duration_s = float(df.index[-1])
        fps = len(df) / duration_s if duration_s > 0 else 30.0
    else:
        duration_s = 0.0
        fps = 30.0

    # ── Players ───────────────────────────────────────────────────────────────
    players = []
    for p in proto.players:
        pid = _platform_id_str(p.id)
        team = "orange" if p.is_orange else "blue"
        core = p.stats.core
        players.append(PlayerMeta(
            name=p.name,
            platform_id=pid,
            team=team,
            is_orange=p.is_orange,
            goals=core.goals,
            shots=core.shots,
            assists=core.assists,
            saves=core.saves,
            score=core.score,
        ))

    # ── Goals ─────────────────────────────────────────────────────────────────
    frame_times = df.index.to_numpy() if df is not None and len(df) > 0 else []
    goals = []
    for g in proto.game_stats.goal:
        fn = g.frame_number
        t = float(frame_times[fn]) if fn < len(frame_times) else fn / fps
        scoring_team = "orange" if g.team_scoring == 1 else "blue"
        goals.append(GoalEvent(
            frame=fn,
            time_s=t,
            scorer_name=getattr(g.scorer, "name", "Unknown"),
            scoring_team=scoring_team,
        ))

    # ── Hits ──────────────────────────────────────────────────────────────────
    hits = []
    for h in proto.game_stats.hit:
        fn = h.frame_number
        t = float(frame_times[fn]) if fn < len(frame_times) else fn / fps
        hits.append(HitEvent(
            frame=fn,
            time_s=t,
            player_name=getattr(h.player, "name", "Unknown"),
            is_shot=bool(getattr(h, "shot", False)),
            is_save=bool(getattr(h, "save", False)),
            is_goal=bool(getattr(h, "goal", False)),
        ))

    # ── Demos ─────────────────────────────────────────────────────────────────
    demos = []
    for d in proto.game_stats.demo:
        fn = d.frame_number
        t = float(frame_times[fn]) if fn < len(frame_times) else fn / fps
        demos.append(DemoEvent(
            frame=fn,
            time_s=t,
            attacker_name=getattr(d.attacker, "name", "Unknown"),
            victim_name=getattr(d.victim, "name", "Unknown"),
        ))

    warnings = []
    if df is None or len(df) == 0:
        warnings.append("frame_df is empty — position metrics unavailable")

    # Derive match type ("2v2", "3v3", etc.) if playlist proto field is empty/unknown
    team_size = max(1, len(players) // 2)
    if not playlist or playlist.lower() in ("unknown", ""):
        playlist = f"{team_size}v{team_size}"

    return ParsedReplay(
        match_id=match_id,
        map_name=map_name,
        date=date_str,
        playlist=playlist,
        duration_s=duration_s,
        fps=fps,
        team_size=max(1, len(players) // 2),
        blue_score=blue_score,
        orange_score=orange_score,
        players=players,
        goals=goals,
        hits=hits,
        demos=demos,
        frame_df=df,
        warnings=warnings,
    )


# ── rrrocket fallback ──────────────────────────────────────────────────────────

def _find_rrrocket() -> Optional[str]:
    """Return the rrrocket binary path (Windows .exe or Linux), respecting RRROCKET_PATH env var."""
    import os
    override = os.environ.get("RRROCKET_PATH", "").strip()
    if override:
        return override if Path(override).exists() else None
    base = Path(__file__).parent.parent
    for pattern in [
        "rrrocket_bin/**/rrrocket.exe",   # Windows
        "rrrocket_bin/**/rrrocket",        # Linux (musl/glibc)
        "rrrocket_bin/rrrocket",
        "rrrocket.exe",
        "rrrocket",
    ]:
        for p in base.glob(pattern):
            if p.is_file():
                return str(p)
    return None


def _platform_id_from_rrrocket(player: dict) -> str:
    platform_value = player.get("Platform", {}).get("value", "")
    online_id = player.get("OnlineID", "")
    pid_fields = player.get("PlayerID", {}).get("fields", {})
    epic_id = pid_fields.get("EpicAccountId", "")

    if "Steam" in platform_value:
        return f"steam:{online_id}"
    if "Epic" in platform_value and epic_id:
        return f"epic:{epic_id}"
    if "Dingo" in platform_value:          # Xbox
        return f"xbl:{online_id}"
    if "PS4" in platform_value or "PS5" in platform_value:
        return f"ps4:{online_id}"
    if "Switch" in platform_value:
        return f"switch:{online_id}"
    return f"unknown:{online_id}"


def _patch_carball_compat():
    """
    Runtime monkey-patches for carball compatibility with pandas 3.x and numpy 2.x.
    Applied once per process; no installed files are modified.
    """
    # 1. Boost-pad events use fillna(method=) removed in pandas 2.1
    try:
        from carball.analysis.events.event_creator import EventsCreator
        if not hasattr(EventsCreator, "_boost_patched"):
            EventsCreator.create_boostpad_events = lambda self, *a, **kw: None
            EventsCreator._boost_patched = True
    except Exception:
        pass

    # 4. CarHandler crashes with KeyError when non-standard game modes (Breakout,
    #    Heatseeker, etc.) use a different PRI TypeName that PlayerHandler skips.
    try:
        from carball.json_parser.actor.car import CarHandler
        if not hasattr(CarHandler, '_patched'):
            _orig_car = CarHandler.update

            def _safe_car(self, actor, frame_number, time, delta):
                try:
                    _orig_car(self, actor, frame_number, time, delta)
                except KeyError:
                    pass

            CarHandler.update = _safe_car
            CarHandler._patched = True
    except Exception:
        pass

    # 5. RL 2026+ changed boost from plain Byte (ReplicatedBoostAmount) to a struct
    #    (ReplicatedBoost → {boost_amount, grant_count, ...}).
    #    Carball still looks for the old key and defaults to 0 → all-zero boost column.
    #    Runtime shim: copy the new struct's boost_amount into the old key before the
    #    original handler reads it.
    try:
        from carball.json_parser.actor.boost import BoostHandler
        BOOST_OLD = 'TAGame.CarComponent_Boost_TA:ReplicatedBoostAmount'
        BOOST_NEW = 'TAGame.CarComponent_Boost_TA:ReplicatedBoost'

        if not hasattr(BoostHandler, '_fmt_patched'):
            _orig_boost = BoostHandler.update

            def _boost_update(self, actor, frame_number, time, delta):
                rb = actor.get(BOOST_NEW)
                if isinstance(rb, dict) and 'boost_amount' in rb:
                    actor[BOOST_OLD] = rb['boost_amount']
                _orig_boost(self, actor, frame_number, time, delta)

            BoostHandler.update = _boost_update
            BoostHandler._fmt_patched = True
    except Exception:
        pass

    # 6. Game.parse_all_data crashes with KeyError(N) when a demo or Dropshot
    #    damage event references a player actor ID that was never registered in
    #    player_actor_id_player_dict.  This happens when a player disconnects
    #    before their actor is fully set up (seen on ShatterShot 3v3 replays).
    #
    #    The crash happens AFTER self.ball and self.frames are already built
    #    (lines 230-233 in game.py), so we can safely swallow it and return
    #    with empty demos/dropshot — the DataFrame is still usable.
    try:
        from carball.json_parser.game import Game
        if not hasattr(Game, '_parse_all_patched'):
            _orig_parse_all = Game.parse_all_data

            def _safe_parse_all(self, all_data, clean_player_names=True):
                try:
                    _orig_parse_all(self, all_data, clean_player_names)
                except KeyError as _e:
                    # Only suppress if ball+frames were already built —
                    # that means the crash is in the demos/dropshot section.
                    ball_ready   = getattr(self, 'ball',   None) is not None
                    frames_ready = getattr(self, 'frames', None) is not None
                    if not (ball_ready and frames_ready):
                        raise  # Error is before ball/frames — don't hide it
                    log.debug("parse_all_data: skipping unregistered player "
                              "actor %s (demos/dropshot) — ball+frames intact", _e)
                    # Ensure attributes expected by downstream carball code are set
                    if not getattr(self, 'demos', None):
                        self.demos = []
                    if not getattr(self, 'parties', None):
                        self.parties = all_data.get('parties', {})
                    if not getattr(self, 'dropshot', None):
                        self.dropshot = {'damage_events': []}

            Game.parse_all_data = _safe_parse_all
            Game._parse_all_patched = True
    except Exception:
        pass

    # 2. np.save/np.load drop fix_imports in numpy 2.x
    try:
        import numpy as _real_np
        from carball.analysis.utils import numpy_manager, pandas_manager

        _orig_np_save = _real_np.save
        _orig_np_load = _real_np.load

        def _safe_save(file, arr, **kw):
            kw.pop("fix_imports", None)
            _orig_np_save(file, arr, **kw)

        def _safe_load(file, **kw):
            kw.pop("fix_imports", None)
            return _orig_np_load(file, **kw)

        numpy_manager.np.save = _safe_save
        numpy_manager.np.load = _safe_load
        pandas_manager.np.save = _safe_save
    except Exception:
        pass


def _carball_from_rrrocket_json(rr_json: dict):
    """
    Feed rrrocket --network-parse JSON into carball's frame parser.
    Returns a per-frame DataFrame with ball/player positions, or None on failure.
    """
    try:
        _patch_carball_compat()

        from carball.json_parser.game import Game
        from carball.analysis.analysis_manager import AnalysisManager

        game = Game()
        game.initialize(loaded_json=rr_json)
        manager = AnalysisManager(game=game)
        manager.create_analysis()
        return manager.get_data_frame()
    except Exception as e:
        log.warning("carball frame parse failed: %s", e)
        return None


def _parse_with_rrrocket(replay_path: Path, match_id: str) -> ParsedReplay:
    import subprocess, json as _json

    rrrocket = _find_rrrocket()
    if rrrocket is None:
        raise RuntimeError("rrrocket.exe not found")

    # --network-parse gives full per-frame actor data (ball/car positions)
    result = subprocess.run(
        [rrrocket, "-n", str(replay_path)],
        capture_output=True, timeout=60
    )
    if result.returncode != 0:
        raise RuntimeError(f"rrrocket failed: {result.stderr.decode()[:200]}")

    data = _json.loads(result.stdout.decode("utf-8-sig"))
    props = data.get("properties", {})

    # Metadata
    map_name     = str(props.get("MapName", "Unknown"))
    date_str     = str(props.get("Date", "")).split(" ")[0]  # 'YYYY-MM-DD HH-MM-SS' → 'YYYY-MM-DD'
    fps          = float(props.get("RecordFPS", 30.0))
    duration     = float(props.get("TotalSecondsPlayed", 0.0))
    team_size    = int(props.get("TeamSize", 2))
    blue_score   = int(props.get("Team0Score", 0))
    orange_score = int(props.get("Team1Score", 0))

    # Players — fix encoding: rrrocket outputs UTF-8, ensure we decode correctly
    players = []
    for p in props.get("PlayerStats", []):
        is_orange = int(p.get("Team", 0)) == 1
        raw_name = p.get("Name", "Unknown")
        # Guard against double-encoded latin-1 names (e.g. "XiÃ¥o" → "Xiåo")
        try:
            name = raw_name.encode("latin-1").decode("utf-8")
        except (UnicodeEncodeError, UnicodeDecodeError):
            name = raw_name
        players.append(PlayerMeta(
            name=name,
            platform_id=_platform_id_from_rrrocket(p),
            team="orange" if is_orange else "blue",
            is_orange=is_orange,
            goals=int(p.get("Goals", 0)),
            shots=int(p.get("Shots", 0)),
            assists=int(p.get("Assists", 0)),
            saves=int(p.get("Saves", 0)),
            score=int(p.get("Score", 0)),
        ))

    # Goals — initially timed as frame / fps (raw, includes pre-match overhead)
    goals = []
    for g in props.get("Goals", []):
        frame = int(g.get("frame", 0))
        goals.append(GoalEvent(
            frame=frame,
            time_s=frame / fps,
            scorer_name=str(g.get("PlayerName", "Unknown")),
            scoring_team="orange" if int(g.get("PlayerTeam", 0)) == 1 else "blue",
        ))

    # Full frame DataFrame via carball's Python analysis on the rrrocket JSON
    frame_df = _carball_from_rrrocket_json(data)

    warnings = []
    if frame_df is None or len(frame_df) == 0:
        warnings.append("Positioning data unavailable — frame parse failed")

    # Re-time goals using the canonical scoreboard clock from the frame data.
    # frame/fps includes pre-match and celebration overhead; seconds_remaining
    # gives elapsed time that matches exactly what the in-game clock shows.
    if frame_df is not None and len(frame_df) > 0 and goals:
        try:
            from .metrics import _game_times as _canonical_times
            canon = _canonical_times(frame_df)
            # Build a frame-index → canonical-elapsed lookup
            frame_to_t = dict(zip(frame_df.index.tolist(), canon.tolist()))
            goals = [
                GoalEvent(
                    frame=g.frame,
                    time_s=float(frame_to_t.get(g.frame, g.time_s)),
                    scorer_name=g.scorer_name,
                    scoring_team=g.scoring_team,
                )
                for g in goals
            ]
            log.debug("Goal times corrected to scoreboard clock: %s",
                      [round(g.time_s, 1) for g in goals])
        except Exception as e:
            log.warning("Goal time correction failed: %s", e)

    return ParsedReplay(
        match_id=match_id,
        map_name=map_name,
        date=date_str,
        playlist=f"{team_size}v{team_size}",
        duration_s=duration,
        fps=fps,
        team_size=team_size,
        blue_score=blue_score,
        orange_score=orange_score,
        players=players,
        goals=goals,
        hits=[],
        demos=[],
        frame_df=frame_df,
        warnings=warnings,
    )


# ── Public API ─────────────────────────────────────────────────────────────────

def parse_replay(replay_path: Path, match_id: str) -> ParsedReplay:
    """
    Decode a .replay file and return a ParsedReplay.
    Tries carball first; if it fails with a format error, falls back to rrrocket.
    Raises RuntimeError on complete failure.
    """
    try:
        return _parse_with_carball(replay_path, match_id)
    except ImportError as e:
        raise RuntimeError("carball not installed — run: pip install sprocket_carball") from e
    except Exception as carball_err:
        # carball can't handle this replay (e.g. newer RL format) — try rrrocket
        log.warning("carball failed (%s), trying rrrocket…", carball_err)
        try:
            return _parse_with_rrrocket(replay_path, match_id)
        except Exception as rr_err:
            raise RuntimeError(f"Parse failed: {carball_err} | rrrocket: {rr_err}") from rr_err
