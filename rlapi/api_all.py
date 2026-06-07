"""Rocket League API endpoint mixins."""
import logging
from typing import Any, Dict, List, Optional

_log = logging.getLogger(__name__)


class MatchesAPI:
    async def get_match_history(self, timeout: Optional[float] = None) -> List[Dict[str, Any]]:
        request = {"PlayerID": str(self.local_player_id)}
        result = await self.send_request_sync("Matches/GetMatchHistory v1", request, timeout)
        return result.get("Matches", []) if result else []


# Skills (MMR / rank per playlist)
class SkillsAPI:
    async def get_player_skills(self, timeout: float = 10.0):
        """
        Fetch the authenticated player's skills/rankings from PsyNet.

        The exact RPC method + body shape isn't publicly documented, so we try
        several plausible variants and log what each returns. Once we see which
        one yields data (check `docker compose logs`), the parser in
        rlcoach/stats_api.py can be locked to that shape.
        """
        pid = str(self.local_player_id)
        attempts = [
            ("Skills/GetSkills v1", {"Players": [{"PlayerID": pid}]}),
            ("Skills/GetSkills v1", {"PlayerID": pid}),
            ("Skills/GetPlayerSkill v1", {"PlayerID": pid}),
            ("Skills/GetSkills v2", {"PlayerID": pid}),
        ]
        for method, body in attempts:
            try:
                result = await self.send_request_sync(method, body, timeout)
                shape = list(result.keys()) if isinstance(result, dict) else type(result).__name__
                _log.info("Skills probe OK  method=%r body=%r -> %s", method, body, shape)
                if result:
                    return result
            except Exception as e:
                _log.info("Skills probe FAIL method=%r body=%r -> %s", method, body, e)
        _log.warning("All skills probes returned nothing — rank will fall back to self-reported")
        return None
class StatsAPI:
    # Locked from server logs: this service + body works (returns {LeaderboardID,
    # bHasValue, Value}); the other variants are ServiceNotFound.
    LIFETIME_SERVICE = "Stats/GetStatLeaderboardValueForUser v1"

    # Candidate leaderboard stat names — discovery phase. We log the full response
    # for each so the real names can be confirmed from:
    #   docker compose logs | grep -i "lifetime stat"
    LIFETIME_STAT_CANDIDATES = [
        "Wins", "Goals", "Saves", "Assists", "MVPs", "Shots",
        "Win", "Goal", "Save", "Assist", "MVP", "Shot",
        "Demolitions", "GoalShots", "Centers", "Clears", "Touches",
        "MatchesPlayed", "GamesPlayed", "TimePlayed", "Points", "Score",
    ]

    @staticmethod
    def _extract_stat_value(result):
        """Pull the numeric stat value out of the response. Handles the locked
        {bHasValue, Value} shape plus a few generic fallbacks."""
        if isinstance(result, (int, float)):
            return int(result)
        if isinstance(result, dict):
            if "bHasValue" in result or "Value" in result:
                if result.get("bHasValue") is False:
                    return None
                v = result.get("Value")
                return int(v) if isinstance(v, (int, float)) else None
            for k in ("value", "StatValue", "Total", "Count"):
                v = result.get(k)
                if isinstance(v, (int, float)):
                    return int(v)
            for k in ("Stats", "Values", "Results", "PlayerStats", "Leaderboard"):
                lst = result.get(k)
                if isinstance(lst, list) and lst:
                    inner = StatsAPI._extract_stat_value(lst[0])
                    if inner is not None:
                        return inner
        if isinstance(result, list) and result:
            return StatsAPI._extract_stat_value(result[0])
        return None

    async def get_lifetime_stats(self, timeout: float = 6.0) -> Optional[Dict[str, int]]:
        """
        Fetch the player's lifetime career totals from PsyNet's stat-leaderboard
        service. The service/body are locked; we probe candidate stat NAMES and
        keep whichever return a value (full responses are logged for confirmation).
        """
        pid = str(self.local_player_id)
        out: Dict[str, int] = {}
        for name in self.LIFETIME_STAT_CANDIDATES:
            try:
                result = await self.send_request_sync(
                    self.LIFETIME_SERVICE, {"Stat": name, "PlayerID": pid}, timeout)
                val = self._extract_stat_value(result)
                _log.info("lifetime stat %r -> %r (val=%s)", name, result, val)
                if val is not None:
                    out[name.lower()] = val
            except Exception as e:
                _log.info("lifetime stat %r FAIL -> %s", name, e)
        _log.info("lifetime stats fetched: %s", out)
        return out or None
class ClubsAPI: pass
class PartyAPI: pass
class MatchmakingAPI: pass
class PlaylistsAPI: pass
class PopulationAPI: pass
class ProductsAPI: pass
class MTXAPI: pass
class RocketPassAPI: pass
class ChallengesAPI: pass
class TournamentsAPI: pass
class TrainingAPI: pass
class MiscAPI: pass
