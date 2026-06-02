"""PsyNet HTTP API client for Rocket League initial authentication."""
import base64
import hashlib
import hmac
import json
import logging
from typing import Any, List, Optional

import httpx

from .requestid import RequestIDCounter


BASE_URL = "https://api.rlpp.psynet.gg/rpc"
GAME_VERSION = "260506.26700.517210"
FEATURE_SET = "PrimeUpdate58_1"
PSY_BUILD_ID = "-1652286008"
PSY_SIG_KEY = "c338bd36fb8c42b1a431d30add939fc7"
PING_INTERVAL = 20.0
PONG_TIMEOUT = 10.0


class PsyNetError(Exception):
    def __init__(self, type: str = "", message: str = ""):
        self.type = type
        self.message = message
        super().__init__(f"{type}: {message}")


class PsyNet:
    """HTTP client for PsyNet initial auth (use PsyNetRPC for game API calls)."""

    def __init__(self, logger: Optional[logging.Logger] = None):
        self.client = httpx.Client(timeout=30.0)
        self.request_id = RequestIDCounter()
        self.logger = logger or logging.getLogger(__name__)

    def __del__(self):
        try:
            self.client.close()
        except Exception:
            pass

    def close(self):
        self.client.close()

    def _generate_psy_sig(self, body: bytes) -> str:
        h = hmac.new(PSY_SIG_KEY.encode(), digestmod=hashlib.sha256)
        h.update(b"-")
        h.update(body)
        return base64.b64encode(h.digest()).decode()

    def _post_json(self, path: List[str], params: Any, result_type: type) -> Any:
        url = f"{BASE_URL}/{'/'.join(path)}"
        body = json.dumps(params).encode()
        self.logger.debug("HTTP → %s", url)
        headers = {
            "Content-Type": "application/x-www-form-urlencoded",
            "User-Agent": f"RL Win/{GAME_VERSION} gzip (x86_64-pc-win32) curl-7.67.0 Schannel",
            "PsyBuildID": PSY_BUILD_ID,
            "PsyEnvironment": "Prod",
            "PsyRequestID": self.request_id.get_id(),
            "PsySig": self._generate_psy_sig(body),
        }
        response = self.client.post(url, headers=headers, content=body)
        if response.status_code != 200:
            raise Exception(f"PsyNet HTTP {response.status_code}: {response.text}")
        resp_data = response.json()
        if resp_data.get("Error"):
            err = resp_data["Error"]
            raise PsyNetError(type=err.get("Type", ""), message=err.get("Message", ""))
        return resp_data.get("Result")


def new_psy_net(logger: Optional[logging.Logger] = None) -> PsyNet:
    return PsyNet(logger=logger)
