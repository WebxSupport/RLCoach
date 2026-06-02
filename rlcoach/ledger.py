"""Processed-replay ledger — prevents re-parsing replays across restarts.

Two dedup strategies:
  - File-hash (SHA-256): for replays processed from local files.
  - Match GUID: for replays pulled from the PsyNet API.
Both are stored in the same processed.json under different key prefixes.
"""
import hashlib
import json
from datetime import datetime
from pathlib import Path


def file_hash(filepath: Path) -> str:
    h = hashlib.sha256()
    with open(filepath, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


class Ledger:
    def __init__(self, path: Path):
        self.path = path
        self._data: dict = {}
        self._load()

    def _load(self):
        if self.path.exists():
            with open(self.path, encoding="utf-8") as f:
                self._data = json.load(f)

    def _save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump(self._data, f, indent=2)

    # ── File-hash methods (local-file watcher, backward compat) ───────────────

    def is_processed(self, filepath: Path) -> bool:
        h = file_hash(filepath)
        entry = self._data.get(h)
        return entry is not None and entry.get("status") == "ok"

    def mark_processed(self, filepath: Path, output_folder: str, match_id: str):
        h = file_hash(filepath)
        self._data[h] = {
            "status": "ok",
            "processed_at": datetime.now().isoformat(),
            "source_file": str(filepath),
            "output_folder": output_folder,
            "match_id": match_id,
        }
        self._save()

    def mark_failed(self, filepath: Path, error: str):
        h = file_hash(filepath)
        self._data[h] = {
            "status": "failed",
            "processed_at": datetime.now().isoformat(),
            "source_file": str(filepath),
            "error": error,
        }
        self._save()

    # ── GUID methods (PsyNet API poller) ──────────────────────────────────────

    def is_processed_guid(self, guid: str) -> bool:
        return f"guid:{guid}" in self._data

    def mark_processed_guid(self, guid: str, output_folder: str = "", skipped: bool = False):
        self._data[f"guid:{guid}"] = {
            "status": "skipped" if skipped else "ok",
            "processed_at": datetime.now().isoformat(),
            "output_folder": output_folder,
        }
        self._save()
