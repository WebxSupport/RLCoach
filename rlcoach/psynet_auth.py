"""Epic Games / EOS token management for PsyNet polling."""
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Tuple

log = logging.getLogger(__name__)

# (access_token, account_id, display_name)
Credentials = Tuple[str, str, str]


def _is_expired(expires_at: str, margin_s: int = 300) -> bool:
    """True if the token expires within margin_s seconds (or timestamp is invalid)."""
    try:
        ts = expires_at.replace("Z", "+00:00")
        expiry = datetime.fromisoformat(ts)
        return (expiry - datetime.now(timezone.utc)).total_seconds() < margin_s
    except Exception:
        return True


class TokenStore:
    """Persists EOS tokens to a JSON file; handles transparent refresh."""

    def __init__(self, path: Path):
        self.path = path
        self._data: dict = {}
        if path.exists():
            try:
                self._data = json.loads(path.read_text(encoding="utf-8"))
            except Exception as e:
                log.warning("Could not read token file: %s", e)

    def _save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self._data, indent=2), encoding="utf-8")

    def store(self, eos_token, display_name: str):
        self._data = {
            "eos_access_token": eos_token.access_token,
            "eos_refresh_token": eos_token.refresh_token,
            "eos_expires_at": eos_token.expires_at,
            "eos_refresh_expires_at": eos_token.refresh_expires_at,
            "account_id": eos_token.account_id,
            "display_name": display_name,
        }
        self._save()
        log.info("Tokens saved for %s (%s)", display_name, eos_token.account_id)

    def get_valid_credentials(self) -> Optional[Credentials]:
        """Return (access_token, account_id, display_name) or None if re-auth needed."""
        if not self._data:
            return None

        access_token = self._data.get("eos_access_token", "")
        refresh_token = self._data.get("eos_refresh_token", "")
        expires_at = self._data.get("eos_expires_at", "")
        refresh_expires_at = self._data.get("eos_refresh_expires_at", "")
        account_id = self._data.get("account_id", "")
        display_name = self._data.get("display_name", "Player")

        if not access_token or not account_id:
            return None

        # Access token still valid
        if not _is_expired(expires_at):
            return access_token, account_id, display_name

        # Try silent refresh
        if refresh_token and not _is_expired(refresh_expires_at):
            try:
                log.info("EOS token expired — refreshing...")
                from rlapi.egs import EGS
                egs = EGS()
                new_eos = egs.refresh_eos_token(refresh_token)
                egs.close()
                self.store(new_eos, display_name)
                log.info("Token refreshed for %s", display_name)
                return new_eos.access_token, new_eos.account_id, display_name
            except Exception as e:
                log.warning("Token refresh failed: %s", e)

        log.warning("Stored tokens are expired. Re-authentication required.")
        return None

    def needs_setup(self) -> bool:
        return self.get_valid_credentials() is None

    def clear(self):
        self._data = {}
        if self.path.exists():
            self.path.unlink()
