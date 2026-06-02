"""Main Rocket League API client."""
import logging
from typing import Optional

from .psynet import PsyNet
from .psynetrpc import PsyNetRPC
from .auth import auth_player
from .api_players import PlayersAPI
from .api_shops import ShopsAPI
from .api_all import (
    MatchesAPI, SkillsAPI, StatsAPI, ClubsAPI, PartyAPI,
    MatchmakingAPI, PlaylistsAPI, PopulationAPI, ProductsAPI,
    MTXAPI, RocketPassAPI, ChallengesAPI, TournamentsAPI, TrainingAPI, MiscAPI,
)


class RocketLeagueClient(
    PsyNetRPC,
    PlayersAPI, ShopsAPI,
    MatchesAPI, SkillsAPI, StatsAPI, ClubsAPI, PartyAPI,
    MatchmakingAPI, PlaylistsAPI, PopulationAPI, ProductsAPI,
    MTXAPI, RocketPassAPI, ChallengesAPI, TournamentsAPI, TrainingAPI, MiscAPI,
):
    pass


async def create_client(
    auth_token: str,
    account_id: str,
    account_name: str,
    logger: Optional[logging.Logger] = None,
) -> RocketLeagueClient:
    psy_net = PsyNet(logger=logger)
    rpc = await auth_player(psy_net, auth_token, account_id, account_name)
    client = RocketLeagueClient(
        ws_conn=rpc.ws_conn,
        local_player_id=rpc.local_player_id,
        psy_token=rpc.psy_token,
        session_id=rpc.session_id,
        request_id=rpc.request_id,
        logger=rpc.logger,
    )
    client._lock = rpc._lock
    client._pending_reqs = rpc._pending_reqs
    client._pong_event = rpc._pong_event
    client._event_queue = rpc._event_queue
    client._connected = rpc._connected
    client._ping_task = rpc._ping_task
    client._read_task = rpc._read_task
    return client
