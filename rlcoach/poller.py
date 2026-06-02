"""API-first replay poller — replaces the file watcher.

On each poll:
  1. Get match history from PsyNet (cloud API, works even without local replay saving).
  2. Skip GUIDs already in the ledger, forfeits, and no-contests.
  3. Lazy-download the .replay from Psyonix's CDN to a temp file.
  4. Call the processing callback (same pipeline as before).
  5. Delete the temp file.
"""
import asyncio
import logging
import tempfile
import threading
from pathlib import Path
from typing import Callable, Optional

log = logging.getLogger(__name__)

# Callback type: (temp_replay_path, match_guid) -> None
OnReplayCB = Callable[[Path, str], None]


class ReplayPoller:
    def __init__(
        self,
        token_store,          # rlcoach.psynet_auth.TokenStore
        on_new_replay: OnReplayCB,
        ledger,               # rlcoach.ledger.Ledger
        poll_interval_s: int = 2700,
        status_cb: Optional[Callable[[str], None]] = None,
        reporter=None,        # rlcoach.ui.UIReporter (optional)
    ):
        self._token_store = token_store
        self._on_new_replay = on_new_replay
        self._ledger = ledger
        self._interval = poll_interval_s
        self._status_cb = status_cb or (lambda s: None)
        self._reporter = reporter
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self.is_running = False

    # ── Lifecycle ──────────────────────────────────────────────────────────────

    def start(self):
        if self.is_running:
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run_loop, daemon=True, name="rl-poller")
        self._thread.start()
        self.is_running = True
        log.info("Replay poller started (poll every %ds)", self._interval)

    def stop(self):
        self._stop.set()
        self.is_running = False
        log.info("Replay poller stopped")

    def poll_now(self):
        """Trigger an immediate poll (e.g. from tray menu)."""
        if self._loop and not self._loop.is_closed():
            asyncio.run_coroutine_threadsafe(self._poll(), self._loop)

    # ── Threading glue ─────────────────────────────────────────────────────────

    def _run_loop(self):
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        self._loop.run_until_complete(self._async_main())

    async def _async_main(self):
        # First poll immediately on start
        await self._poll()
        # Then poll every interval, sleeping in small chunks to stay responsive to stop()
        elapsed = 0
        while not self._stop.is_set():
            await asyncio.sleep(1)
            elapsed += 1
            if elapsed >= self._interval:
                elapsed = 0
                await self._poll()

    # ── Core poll ──────────────────────────────────────────────────────────────

    async def _poll(self):
        log.info("Polling PsyNet for replays…")
        self._status_cb("Polling PsyNet…")
        if self._reporter:
            self._reporter.poll_start()

        creds = self._token_store.get_valid_credentials()
        if creds is None:
            msg = "No valid Epic auth — use 'Setup Epic Auth' from tray menu."
            log.warning(msg)
            self._status_cb(msg)
            if self._reporter:
                self._reporter.status(msg)
            return

        access_token, account_id, display_name = creds

        try:
            from rlapi.client import create_client
            client = await create_client(access_token, account_id, display_name)
        except Exception as e:
            log.error("PsyNet connect failed: %s", e)
            self._status_cb(f"PsyNet connect error: {e}")
            if self._reporter:
                self._reporter.status(f"PsyNet connect error: {e}")
            return

        try:
            matches = await client.get_match_history(timeout=20.0)
        except Exception as e:
            log.error("get_match_history failed: %s", e)
            self._status_cb(f"Match history error: {e}")
            if self._reporter:
                self._reporter.status(f"Match history error: {e}")
            return
        finally:
            try:
                await client.close()
            except Exception:
                pass

        log.info("Got %d matches from PsyNet", len(matches))

        # Pre-filter to new entries so we can give the UI an accurate total upfront
        new_entries = []
        for entry in matches:
            match_data = entry.get("Match", {})
            guid = match_data.get("MatchGUID", "")
            replay_url = entry.get("ReplayUrl", "")
            if not guid or not replay_url:
                log.debug("Skip (no URL/GUID): %s", guid[:8] or "?")
                continue
            if self._ledger.is_processed_guid(guid):
                continue
            new_entries.append((guid, replay_url))

        log.info("%d new replays to process", len(new_entries))
        if self._reporter:
            self._reporter.batch_init(len(new_entries))

        new_count = 0
        for i, (guid, replay_url) in enumerate(new_entries):
            log.info("New replay %s — downloading…", guid)
            self._status_cb(f"Downloading replay {guid[:8]}…")
            if self._reporter:
                self._reporter.download(guid[:8], i, len(new_entries))

            try:
                tmp_path = await self._download(replay_url)
            except Exception as e:
                log.error("Download failed for %s: %s", guid, e)
                if self._reporter:
                    self._reporter.replay_failed(guid[:8], f"Download failed: {e}")
                continue

            # Keep a debug copy so we can test alternative parsers on failure
            debug_dir = self._ledger.path.parent / "failed_replays"
            debug_dir.mkdir(exist_ok=True)
            debug_copy = debug_dir / f"{guid[:8]}.replay"
            import shutil
            shutil.copy2(str(tmp_path), str(debug_copy))

            try:
                loop = asyncio.get_event_loop()
                await loop.run_in_executor(None, self._on_new_replay, tmp_path, guid)
                new_count += 1
                debug_copy.unlink(missing_ok=True)
            finally:
                try:
                    tmp_path.unlink(missing_ok=True)
                except Exception:
                    pass

        log.info("Poll complete — %d processed", new_count)
        msg = f"Poll complete — {new_count} new replay(s) processed."
        self._status_cb(msg if new_count else "Up to date.")
        if self._reporter:
            self._reporter.poll_done(new_count)

    async def _download(self, url: str) -> Path:
        import httpx
        tmp = Path(tempfile.mktemp(suffix=".replay"))
        async with httpx.AsyncClient(timeout=120.0, follow_redirects=True) as client:
            async with client.stream("GET", url) as resp:
                resp.raise_for_status()
                with open(tmp, "wb") as f:
                    async for chunk in resp.aiter_bytes(65536):
                        f.write(chunk)
        return tmp
