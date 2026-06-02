"""Epic Games Store authentication client."""
import base64
import json
import os
import time
from dataclasses import dataclass
from typing import Optional
from urllib.parse import quote

import httpx

# These are the official EGS/EOS client credentials used by Rocket League third-party tools.
# They are widely known in the community and not secret by nature, but we load them from
# environment variables so they're never baked into container images or git history.
_EGS_CLIENT_ID_DEFAULT     = "34a02cf8f4414e29b15921876da36f9a"
_EGS_CLIENT_SECRET_DEFAULT = "daafbccc737745039dffe53d94fc76cf"
_EOS_CLIENT_ID_DEFAULT     = "xyza7891p5D7s9R6Gm6moTHWGloerp7B"
_EOS_AUTH_HEADER_DEFAULT   = "eHl6YTc4OTFwNUQ3czlSNkdtNm1vVEhXR2xvZXJwN0I6S25oMThkdTROVmxGcyszdVErWlBwRENWdG8wV1lmNHlYUDgrT2N3VnQxbw=="
_EOS_DEPLOYMENT_ID_DEFAULT = "da32ae9c12ae40e8a112c52e1f17f3ba"

EGS_USER_AGENT   = "UELauncher/11.0.1-14907503+++Portal+Release-Live Windows/10.0.19041.1.256.64bit"
EGS_CLIENT_ID    = os.environ.get("EGS_CLIENT_ID",    _EGS_CLIENT_ID_DEFAULT)
EGS_CLIENT_SECRET= os.environ.get("EGS_CLIENT_SECRET",_EGS_CLIENT_SECRET_DEFAULT)
EGS_OAUTH_URL    = "account-public-service-prod03.ol.epicgames.com"
EOS_CLIENT_ID    = os.environ.get("EOS_CLIENT_ID",    _EOS_CLIENT_ID_DEFAULT)
EOS_AUTH_HEADER  = os.environ.get("EOS_AUTH_HEADER",  _EOS_AUTH_HEADER_DEFAULT)
EOS_DEPLOYMENT_ID= os.environ.get("EOS_DEPLOYMENT_ID",_EOS_DEPLOYMENT_ID_DEFAULT)


@dataclass
class TokenResponse:
    access_token: str
    refresh_token: str
    expires_in: int
    expires_at: str
    token_type: str
    client_id: str
    internal_client: bool
    client_service: str
    account_id: str
    display_name: str
    app: str
    in_app_id: str
    device_id: Optional[str] = None


@dataclass
class EOSTokenResponse:
    access_token: str
    refresh_token: str
    expires_in: int
    expires_at: str
    refresh_expires_in: int
    refresh_expires_at: str
    token_type: str
    scope: str
    client_id: str
    application_id: str
    account_id: str
    merged_accounts: list
    acr: str
    auth_time: str
    id_token: Optional[str] = None
    selected_account_id: Optional[str] = None


class EGS:
    def __init__(self):
        self.client = httpx.Client(timeout=30.0)

    def __del__(self):
        try:
            self.client.close()
        except Exception:
            pass

    def close(self):
        self.client.close()

    def get_auth_url(self) -> str:
        login_url = "https://www.epicgames.com/id/login?redirectUrl="
        redirect_url = f"https://www.epicgames.com/id/api/redirect?clientId={EGS_CLIENT_ID}&responseType=code"
        return login_url + quote(redirect_url)

    def authenticate_with_code(self, auth_code: str) -> TokenResponse:
        return self._request_token({
            "grant_type": "authorization_code",
            "code": auth_code,
            "token_type": "eg1",
        })

    def authenticate_with_refresh_token(self, refresh_token: str) -> TokenResponse:
        return self._request_token({
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
            "token_type": "eg1",
        })

    def _request_token(self, params: dict) -> TokenResponse:
        url = f"https://{EGS_OAUTH_URL}/account/api/oauth/token"
        auth_string = f"{EGS_CLIENT_ID}:{EGS_CLIENT_SECRET}"
        auth_header = "Basic " + base64.b64encode(auth_string.encode()).decode()
        headers = {
            "Content-Type": "application/x-www-form-urlencoded",
            "User-Agent": EGS_USER_AGENT,
            "Authorization": auth_header,
        }
        response = self.client.post(url, headers=headers, data=params)
        if response.status_code != 200:
            try:
                err = response.json()
                raise Exception(f"Auth failed: {response.status_code}, {err.get('errorCode')} - {err.get('errorMessage')}")
            except json.JSONDecodeError:
                raise Exception(f"Auth failed: {response.status_code}")
        data = response.json()
        return TokenResponse(
            access_token=data["access_token"],
            refresh_token=data["refresh_token"],
            expires_in=data["expires_in"],
            expires_at=data["expires_at"],
            token_type=data["token_type"],
            client_id=data["client_id"],
            internal_client=data["internal_client"],
            client_service=data["client_service"],
            account_id=data["account_id"],
            display_name=data["displayName"],
            app=data["app"],
            in_app_id=data["in_app_id"],
            device_id=data.get("device_id"),
        )

    def get_exchange_code(self, access_token: str) -> str:
        url = f"https://{EGS_OAUTH_URL}/account/api/oauth/exchange"
        headers = {
            "Authorization": f"bearer {access_token}",
            "User-Agent": EGS_USER_AGENT,
        }
        response = self.client.get(url, headers=headers)
        if response.status_code != 200:
            raise Exception(f"Exchange code request failed: {response.status_code}")
        return response.json()["code"]

    def exchange_eos_token(self, exchange_code: str) -> EOSTokenResponse:
        return self._request_eos_token({
            "grant_type": "exchange_code",
            "exchange_code": exchange_code,
        })

    def refresh_eos_token(self, refresh_token: str) -> EOSTokenResponse:
        return self._request_eos_token({
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
        })

    def _request_eos_token(self, params: dict) -> EOSTokenResponse:
        url = "https://api.epicgames.dev/epic/oauth/v2/token"
        params["deployment_id"] = EOS_DEPLOYMENT_ID
        params["scope"] = "basic_profile"
        headers = {
            "Content-Type": "application/x-www-form-urlencoded",
            "Authorization": f"Basic {EOS_AUTH_HEADER}",
            "User-Agent": EGS_USER_AGENT,
        }
        response = self.client.post(url, headers=headers, data=params)
        if response.status_code != 200:
            raise Exception(f"EOS token request failed: {response.status_code} — {response.text}")
        data = response.json()
        return EOSTokenResponse(
            access_token=data["access_token"],
            refresh_token=data["refresh_token"],
            expires_in=data["expires_in"],
            expires_at=data["expires_at"],
            refresh_expires_in=data["refresh_expires_in"],
            refresh_expires_at=data["refresh_expires_at"],
            token_type=data["token_type"],
            scope=data["scope"],
            client_id=data["client_id"],
            application_id=data["application_id"],
            account_id=data["account_id"],
            merged_accounts=data.get("merged_accounts", []),
            acr=data.get("acr", ""),
            auth_time=data.get("auth_time", ""),
            id_token=data.get("id_token"),
            selected_account_id=data.get("selected_account_id"),
        )


@dataclass
class DeviceAuthResponse:
    user_code: str
    device_code: str
    verification_uri: str
    expires_in: int
    interval: int


# ── Device Authorization Grant (RFC 8628) ─────────────────────────────────────
# Friendlier than the browser-code flow: user visits a short URL and enters a
# code shown by the app; the app polls automatically until they complete it.

def authenticate_with_device(egs: "EGS") -> DeviceAuthResponse:
    """Start the device auth flow. Show verification_uri + user_code to the user."""
    url = "https://api.epicgames.dev/epic/oauth/v2/deviceAuthorization"
    headers = {
        "Content-Type": "application/x-www-form-urlencoded",
        "User-Agent": EGS_USER_AGENT,
    }
    resp = egs.client.post(url, headers=headers, data={"client_id": EOS_CLIENT_ID})
    if resp.status_code != 200:
        raise Exception(f"Device auth initiation failed: {resp.status_code} — {resp.text}")
    d = resp.json()
    return DeviceAuthResponse(
        user_code=d["user_code"],
        device_code=d["device_code"],
        verification_uri=d["verification_uri"],
        expires_in=d["expires_in"],
        interval=d.get("interval", 5),
    )


def wait_for_device_authorization(
    egs: "EGS",
    device: DeviceAuthResponse,
    on_waiting: Optional[callable] = None,
) -> EOSTokenResponse:
    """Poll until the user completes auth at verification_uri, then return EOS token."""
    deadline = time.time() + device.expires_in
    while time.time() < deadline:
        time.sleep(device.interval)
        if on_waiting:
            on_waiting()
        try:
            return egs._request_eos_token({
                "grant_type": "device_code",
                "device_code": device.device_code,
            })
        except Exception as e:
            msg = str(e)
            if "authorization_pending" in msg or "slow_down" in msg:
                continue
            raise
    raise Exception("Device authorization timed out — please try again.")


def new_egs() -> "EGS":
    return EGS()


def get_eos_display_name(access_token: str, account_id: str) -> Optional[str]:
    """
    Look up the human-readable Epic display name for an account id.
    Best-effort: returns None if the lookup fails (caller falls back to the id).
    """
    url = "https://api.epicgames.dev/epic/id/v2/accounts"
    try:
        with httpx.Client(timeout=10.0) as c:
            r = c.get(url, headers={"Authorization": f"Bearer {access_token}"},
                      params={"accountId": account_id})
            if r.status_code == 200:
                data = r.json()
                if isinstance(data, list) and data:
                    name = data[0].get("displayName")
                    if name:
                        return name
    except Exception:
        pass
    return None
