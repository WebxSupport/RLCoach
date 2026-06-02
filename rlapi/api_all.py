"""Rocket League API endpoint mixins."""
from typing import Any, Dict, List, Optional


class MatchesAPI:
    async def get_match_history(self, timeout: Optional[float] = None) -> List[Dict[str, Any]]:
        request = {"PlayerID": str(self.local_player_id)}
        result = await self.send_request_sync("Matches/GetMatchHistory v1", request, timeout)
        return result.get("Matches", []) if result else []


# Skills (MMR / rank per playlist)
class SkillsAPI:
    async def get_player_skills(self, timeout: float = 10.0):
        """
        Fetch the authenticated player's skills/rankings.
        Tries two known PsyNet RPC endpoint variants; returns raw dict or None.
        """
        for method in ("Skills/GetSkills v2", "1/skill/2"):
            try:
                result = await self.send_request_sync(method, {}, timeout)
                if result:
                    return result
            except Exception:
                pass
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
