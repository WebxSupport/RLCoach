"""Rocket League PsyNet API client (vendored from github.com/b9llach/rlapi-py)."""

__version__ = "1.0.0"

from .egs import EGS, TokenResponse, EOSTokenResponse, new_egs
from .psynet import PsyNet, PsyNetError, new_psy_net
from .psynetrpc import PsyNetRPC, Event, EventType
from .playerid import PlayerID, Platform, new_player_id, parse_player_id
from .client import RocketLeagueClient, create_client
from .auth import auth_player
from .types import Match, MatchEntry

__all__ = [
    "EGS", "TokenResponse", "EOSTokenResponse", "new_egs",
    "PsyNet", "PsyNetError", "new_psy_net",
    "PsyNetRPC", "Event", "EventType",
    "PlayerID", "Platform", "new_player_id", "parse_player_id",
    "RocketLeagueClient", "create_client",
    "auth_player",
    "Match", "MatchEntry",
]
