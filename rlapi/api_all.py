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

    # Locked from server logs — these are the valid lifetime stat-leaderboard
    # names (others return RequestError). PsyNet returns the Value as a STRING.
    LIFETIME_STAT_NAMES = ["Wins", "Goals", "Saves", "Assists", "MVPs", "Shots"]

    @staticmethod
    def _to_int(v):
        if isinstance(v, bool):
            return None
        if isinstance(v, (int, float)):
            return int(v)
        if isinstance(v, str):
            s = v.strip()
            try:
                return int(float(s)) if s else None
            except ValueError:
                return None
        return None

    @staticmethod
    def _extract_stat_value(result):
        """Pull the stat value out of the {LeaderboardID, bHasValue, Value} shape
        (Value arrives as a numeric string), with a few generic fallbacks."""
        if isinstance(result, (int, float, str)):
            return StatsAPI._to_int(result)
        if isinstance(result, dict):
            if "bHasValue" in result or "Value" in result:
                if result.get("bHasValue") is False:
                    return None
                return StatsAPI._to_int(result.get("Value"))
            for k in ("value", "StatValue", "Total", "Count"):
                n = StatsAPI._to_int(result.get(k))
                if n is not None:
                    return n
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
        Fetch the player's lifetime career totals (Wins/Goals/Saves/Assists/MVPs/
        Shots) from PsyNet's stat-leaderboard service. Service, body and stat names
        are all locked from server logs.
        """
        pid = str(self.local_player_id)
        out: Dict[str, int] = {}
        for name in self.LIFETIME_STAT_NAMES:
            try:
                result = await self.send_request_sync(
                    self.LIFETIME_SERVICE, {"Stat": name, "PlayerID": pid}, timeout)
                val = self._extract_stat_value(result)
                if val is not None:
                    out[name.lower()] = val
            except Exception as e:
                _log.info("lifetime stat %r failed: %s", name, e)
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
