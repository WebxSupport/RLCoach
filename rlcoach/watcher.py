"""
FR1 — Watchdog folder monitor with file-stability debounce.
A new .replay is only handed to the pipeline once its file size has been
stable for `stable_wait_s` seconds (RL writes replays incrementally).
"""
import logging
import threading
import time
from pathlib import Path

from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer

log = logging.getLogger(__name__)


class _ReplayHandler(FileSystemEventHandler):
    def __init__(self, callback, stable_wait_s: float):
        super().__init__()
        self._callback = callback
        self._stable_wait_s = stable_wait_s
        self._pending: dict[str, threading.Timer] = {}
        self._lock = threading.Lock()

    def on_created(self, event):
        if not event.is_directory and event.src_path.endswith(".replay"):
            self._schedule(event.src_path)

    def on_modified(self, event):
        if not event.is_directory and event.src_path.endswith(".replay"):
            self._schedule(event.src_path)

    def _schedule(self, path: str):
        with self._lock:
            if path in self._pending:
                self._pending[path].cancel()
            t = threading.Timer(self._stable_wait_s, self._on_stable, args=[path])
            self._pending[path] = t
            t.start()

    def _on_stable(self, path: str):
        with self._lock:
            self._pending.pop(path, None)
        try:
            size_a = Path(path).stat().st_size
            time.sleep(1.0)
            size_b = Path(path).stat().st_size
        except OSError:
            return
        if size_a != size_b:
            # File is still growing — reschedule
            self._schedule(path)
            return
        log.info("Stable replay detected: %s", path)
        self._callback(Path(path))


class ReplayWatcher:
    def __init__(self, watch_dir: Path, callback, stable_wait_s: float = 3.0):
        self._dir = watch_dir
        self._handler = _ReplayHandler(callback, stable_wait_s)
        self._observer: Observer | None = None

    def start(self):
        self._dir.mkdir(parents=True, exist_ok=True)
        self._observer = Observer()
        self._observer.schedule(self._handler, str(self._dir), recursive=False)
        self._observer.start()
        log.info("Watching %s", self._dir)

    def stop(self):
        if self._observer and self._observer.is_alive():
            self._observer.stop()
            self._observer.join()
        self._observer = None
        log.info("Watcher stopped")

    def restart_on(self, new_dir: Path) -> None:
        """Stop watching the current directory and start watching new_dir."""
        self.stop()
        self._dir = new_dir
        self.start()

    @property
    def watch_dir(self) -> Path:
        return self._dir

    @property
    def is_running(self) -> bool:
        return self._observer is not None and self._observer.is_alive()
