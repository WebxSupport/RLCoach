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
class StatsAPI: pass
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
