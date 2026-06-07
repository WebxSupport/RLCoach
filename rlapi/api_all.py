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
    # The lifetime stats Rocket League tracks per account (same set TRN shows).
    LIFETIME_STATS = ["Wins", "Goals", "Assists", "Saves", "Shots", "MVPs"]

    @staticmethod
    def _extract_stat_value(result):
        """Pull the first numeric stat value out of an unknown response shape."""
        if isinstance(result, (int, float)):
            return int(result)
        if isinstance(result, dict):
            for k in ("Value", "value", "StatValue", "Total", "Count"):
                v = result.get(k)
                if isinstance(v, (int, float)):
                    return int(v)
            for k in ("Stats", "Values", "Value", "Results", "PlayerStats", "Leaderboard"):
                lst = result.get(k)
                if isinstance(lst, list) and lst:
                    inner = StatsAPI._extract_stat_value(lst[0])
                    if inner is not None:
                        return inner
        if isinstance(result, list) and result:
            return StatsAPI._extract_stat_value(result[0])
        return None

    async def get_lifetime_stats(self, timeout: float = 8.0) -> Optional[Dict[str, int]]:
        """
        Fetch the player's lifetime career totals from PsyNet's stat leaderboards.

        The exact RPC method + body shape is undocumented, so we probe candidates
        with the 'Wins' stat, lock onto whatever returns a numeric value, then
        fetch the rest with that shape. Confirm/lock from:
            docker compose logs | grep -i "lifetime stat"
        """
        pid = str(self.local_player_id)
        candidates = [
            ("Stats/GetStatLeaderboardValueForUsers v1", lambda s: {"Stat": s, "PlayerIDs": [pid]}),
            ("Stats/GetStatLeaderboardValueForUser v1",  lambda s: {"Stat": s, "PlayerID": pid}),
            ("Stats/GetStatLeaderboardValueForUsers v1", lambda s: {"Stat": s, "Players": [{"PlayerID": pid}]}),
            ("Stats/GetStatLeaderboardValueForUser v1",  lambda s: {"StatName": s, "PlayerID": pid}),
        ]
        chosen = None
        for service, build in candidates:
            try:
                result = await self.send_request_sync(service, build("Wins"), timeout)
                val = self._extract_stat_value(result)
                shape = list(result.keys()) if isinstance(result, dict) else type(result).__name__
                _log.info("lifetime stat probe service=%r -> shape=%s Wins=%s", service, shape, val)
                if val is not None:
                    chosen = (service, build)
                    break
            except Exception as e:
                _log.info("lifetime stat probe FAIL service=%r -> %s", service, e)
        if not chosen:
            _log.warning("No PsyNet lifetime-stats RPC matched — career totals unavailable")
            return None

        service, build = chosen
        out: Dict[str, int] = {}
        for stat in self.LIFETIME_STATS + ["MatchesPlayed"]:
            try:
                v = self._extract_stat_value(await self.send_request_sync(service, build(stat), timeout))
                if v is not None:
                    out[stat.lower()] = v
            except Exception as e:
                _log.info("lifetime stat %s failed: %s", stat, e)
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
