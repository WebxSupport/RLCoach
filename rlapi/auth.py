"""Authentication flow: EGS/EOS → PsyNet WebSocket."""
import logging
from typing import Optional

import websockets

from .psynet import PsyNet, FEATURE_SET, PSY_BUILD_ID, GAME_VERSION
from .psynetrpc import PsyNetRPC
from .playerid import PlayerID, Platform, new_player_id


async def auth_player(
    psy_net: PsyNet,
    auth_token: str,
    account_id: str,
    account_name: str,
) -> PsyNetRPC:
    """Authenticate with PsyNet via EOS and return an active WebSocket RPC client."""
    local_player_id = new_player_id(Platform.EPIC, account_id)
    req_data = {
        "Platform": Platform.EPIC.value,
        "PlayerName": account_name,
        "PlayerID": account_id,
        "Language": "INT",
        "AuthTicket": auth_token,
        "BuildRegion": "",
        "FeatureSet": FEATURE_SET,
        "Device": "PC",
        "LocalFirstPlayerID": str(local_player_id),
        "bSkipAuth": False,
        "bSetAsPrimaryAccount": True,
        "EpicAuthTicket": auth_token,
        "EpicAccountID": account_id,
    }
    result = psy_net._post_json(["Auth", "AuthPlayer", "v2"], req_data, dict)
    psy_token = result["PsyToken"]
    session_id = result["SessionID"]
    ws_url = result["PerConURLv2"]

    extra_headers = {
        "PsyBuildID": PSY_BUILD_ID,
        "User-Agent": f"RL Win/{GAME_VERSION} gzip",
        "PsyEnvironment": "Prod",
        "PsyToken": psy_token,
        "PsySessionID": session_id,
    }
    ws_conn = await websockets.connect(ws_url, additional_headers=extra_headers)
    rpc = PsyNetRPC(
        ws_conn=ws_conn,
        local_player_id=local_player_id,
        psy_token=psy_token,
        session_id=session_id,
        request_id=psy_net.request_id,
        logger=psy_net.logger,
    )
    rpc.start_background_tasks()
    return rpc
