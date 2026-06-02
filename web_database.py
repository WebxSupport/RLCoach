"""Async SQLite database layer for RLCoach web app — multi-user edition."""
from __future__ import annotations
import base64
import hashlib
import hmac
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import aiosqlite


# ── token encryption (Fernet symmetric) ──────────────────────────────────────
# ENCRYPTION_KEY env var → SHA-256 → Fernet key.
# Gracefully degrades to plaintext if the key is not set (dev mode).

_fernet_instance = None


def _fernet():
    global _fernet_instance
    if _fernet_instance is not None:
        return _fernet_instance
    key_raw = os.environ.get("ENCRYPTION_KEY", "")
    if not key_raw:
        return None
    try:
        from cryptography.fernet import Fernet
        derived = base64.urlsafe_b64encode(hashlib.sha256(key_raw.encode()).digest())
        _fernet_instance = Fernet(derived)
        return _fernet_instance
    except ImportError:
        return None


def _encrypt(plaintext: str) -> str:
    f = _fernet()
    return f.encrypt(plaintext.encode()).decode() if f else plaintext


def _decrypt(ciphertext: str) -> str:
    f = _fernet()
    if f is None:
        return ciphertext
    try:
        return f.decrypt(ciphertext.encode()).decode()
    except Exception:
        return ciphertext  # legacy unencrypted value — fall through

DB_PATH = Path("data/rlcoach.db")

_SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

-- RLCoach accounts (email + password)
CREATE TABLE IF NOT EXISTS users (
    user_id       TEXT PRIMARY KEY,
    email         TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    created_at    TEXT NOT NULL
);

-- One persistent session per user; is_active tracks logged-in state.
-- Epic Games auth stored here too (nullable until connected).
CREATE TABLE IF NOT EXISTS sessions (
    session_id     TEXT PRIMARY KEY,
    user_id        TEXT UNIQUE NOT NULL REFERENCES users(user_id),
    eos_account_id TEXT,
    display_name   TEXT,
    player_id      TEXT,
    auth_tokens    TEXT,
    is_active      INTEGER NOT NULL DEFAULT 1,
    created_at     TEXT NOT NULL,
    last_seen      TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS analysis_usage (
    eos_account_id TEXT NOT NULL,
    usage_date     TEXT NOT NULL,
    count          INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (eos_account_id, usage_date)
);

CREATE TABLE IF NOT EXISTS jobs (
    job_id     TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    status     TEXT NOT NULL DEFAULT 'pending',
    progress   TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS matches (
    match_id     TEXT PRIMARY KEY,
    session_id   TEXT NOT NULL,
    folder_path  TEXT NOT NULL,
    summary      TEXT NOT NULL,
    has_analysis INTEGER NOT NULL DEFAULT 0,
    created_at   TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS profiles (
    session_id       TEXT PRIMARY KEY,
    platform         TEXT NOT NULL,
    gamemode         TEXT NOT NULL,
    team_size        INTEGER NOT NULL DEFAULT 2,
    current_rank     TEXT,
    target_rank      TEXT,
    mins_per_day     INTEGER NOT NULL DEFAULT 60,
    days_per_week    INTEGER NOT NULL DEFAULT 5,
    duo_partner      TEXT,
    freestyle        INTEGER NOT NULL DEFAULT 0,
    display_name     TEXT,
    stats_json       TEXT,
    created_at       TEXT NOT NULL,
    updated_at       TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS coaching_plans (
    plan_id      TEXT PRIMARY KEY,
    session_id   TEXT NOT NULL,
    content_md   TEXT NOT NULL,
    replay_guids TEXT NOT NULL DEFAULT '[]',
    generated_at TEXT NOT NULL
);
"""

DAILY_LIMIT = 5


# ── password hashing (stdlib scrypt — no extra deps) ──────────────────────────

def _hash_password(password: str) -> str:
    salt = os.urandom(16)
    key = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=16384, r=8, p=1, dklen=32)
    return salt.hex() + ":" + key.hex()


def _verify_password(password: str, stored: str) -> bool:
    try:
        salt_hex, key_hex = stored.split(":", 1)
        salt = bytes.fromhex(salt_hex)
        key = bytes.fromhex(key_hex)
        check = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=16384, r=8, p=1, dklen=32)
        return hmac.compare_digest(check, key)
    except Exception:
        return False


class Database:
    def __init__(self, path: Path = DB_PATH):
        self.path = path
        self._db: Optional[aiosqlite.Connection] = None

    async def init(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._db = await aiosqlite.connect(str(self.path))
        self._db.row_factory = aiosqlite.Row
        await self._db.executescript(_SCHEMA)
        await self._db.commit()

    async def close(self) -> None:
        if self._db:
            await self._db.close()

    def _now(self) -> str:
        return datetime.now(timezone.utc).isoformat()

    # ── users ─────────────────────────────────────────────────────────────────

    async def create_user(self, user_id: str, email: str, password: str) -> None:
        await self._db.execute(
            "INSERT INTO users VALUES (?,?,?,?)",
            (user_id, email.lower().strip(), _hash_password(password), self._now()),
        )
        await self._db.commit()

    async def get_user_by_email(self, email: str) -> Optional[dict]:
        async with self._db.execute(
            "SELECT * FROM users WHERE email=?", (email.lower().strip(),)
        ) as cur:
            row = await cur.fetchone()
        return dict(row) if row else None

    def verify_password(self, password: str, user: dict) -> bool:
        return _verify_password(password, user["password_hash"])

    # ── sessions ──────────────────────────────────────────────────────────────

    async def create_session(self, session_id: str, user_id: str) -> None:
        now = self._now()
        await self._db.execute(
            """INSERT INTO sessions
               (session_id, user_id, eos_account_id, display_name, player_id,
                auth_tokens, is_active, created_at, last_seen)
               VALUES (?,?,NULL,NULL,NULL,NULL,1,?,?)""",
            (session_id, user_id, now, now),
        )
        await self._db.commit()

    async def get_session(self, session_id: str) -> Optional[dict]:
        async with self._db.execute(
            "SELECT * FROM sessions WHERE session_id=? AND is_active=1", (session_id,)
        ) as cur:
            row = await cur.fetchone()
        if not row:
            return None
        await self._db.execute(
            "UPDATE sessions SET last_seen=? WHERE session_id=?",
            (self._now(), session_id),
        )
        await self._db.commit()
        d = dict(row)
        # Transparently decrypt auth_tokens before returning
        if d.get("auth_tokens"):
            d["auth_tokens"] = _decrypt(d["auth_tokens"])
        return d

    async def get_session_by_user_id(self, user_id: str) -> Optional[dict]:
        async with self._db.execute(
            "SELECT * FROM sessions WHERE user_id=?", (user_id,)
        ) as cur:
            row = await cur.fetchone()
        return dict(row) if row else None

    async def activate_session(self, session_id: str) -> None:
        await self._db.execute(
            "UPDATE sessions SET is_active=1, last_seen=? WHERE session_id=?",
            (self._now(), session_id),
        )
        await self._db.commit()

    async def deactivate_session(self, session_id: str) -> None:
        """Logout — keeps data, just marks session as inactive."""
        await self._db.execute(
            "UPDATE sessions SET is_active=0 WHERE session_id=?", (session_id,)
        )
        await self._db.commit()

    async def delete_session(self, session_id: str) -> None:
        """Hard delete — used only when disconnecting Epic or removing account."""
        await self._db.execute("DELETE FROM sessions WHERE session_id=?", (session_id,))
        await self._db.commit()

    async def connect_epic(
        self, session_id: str, eos_account_id: str, display_name: str, tokens: dict
    ) -> None:
        await self._db.execute(
            """UPDATE sessions
               SET eos_account_id=?, display_name=?, auth_tokens=?, last_seen=?
               WHERE session_id=?""",
            (eos_account_id, display_name, _encrypt(json.dumps(tokens)), self._now(), session_id),
        )
        await self._db.commit()

    async def disconnect_epic(self, session_id: str) -> None:
        await self._db.execute(
            """UPDATE sessions
               SET eos_account_id=NULL, display_name=NULL, auth_tokens=NULL, player_id=NULL
               WHERE session_id=?""",
            (session_id,),
        )
        await self._db.commit()

    async def update_tokens(self, session_id: str, tokens: dict) -> None:
        await self._db.execute(
            "UPDATE sessions SET auth_tokens=? WHERE session_id=?",
            (_encrypt(json.dumps(tokens)), session_id),
        )
        await self._db.commit()

    async def update_player_id(self, session_id: str, player_id: str) -> None:
        await self._db.execute(
            "UPDATE sessions SET player_id=? WHERE session_id=?",
            (player_id, session_id),
        )
        await self._db.commit()

    # ── usage ─────────────────────────────────────────────────────────────────

    async def get_usage(self, eos_account_id: str, usage_date: str) -> int:
        async with self._db.execute(
            "SELECT count FROM analysis_usage WHERE eos_account_id=? AND usage_date=?",
            (eos_account_id, usage_date),
        ) as cur:
            row = await cur.fetchone()
        return row["count"] if row else 0

    async def increment_usage(self, eos_account_id: str, usage_date: str) -> int:
        await self._db.execute(
            """INSERT INTO analysis_usage (eos_account_id, usage_date, count) VALUES (?,?,1)
               ON CONFLICT(eos_account_id, usage_date)
               DO UPDATE SET count = count + 1""",
            (eos_account_id, usage_date),
        )
        await self._db.commit()
        return await self.get_usage(eos_account_id, usage_date)

    # ── jobs ──────────────────────────────────────────────────────────────────

    async def create_job(self, job_id: str, session_id: str) -> None:
        now = self._now()
        init = json.dumps(
            {"status": "pending", "step": "Queued", "total": 0, "current": 0, "messages": []}
        )
        await self._db.execute(
            "INSERT INTO jobs VALUES (?,?,?,?,?,?)",
            (job_id, session_id, "pending", init, now, now),
        )
        await self._db.commit()

    async def update_job(self, job_id: str, progress: dict) -> None:
        await self._db.execute(
            "UPDATE jobs SET progress=?, status=?, updated_at=? WHERE job_id=?",
            (json.dumps(progress), progress.get("status", "running"), self._now(), job_id),
        )
        await self._db.commit()

    async def get_job(self, job_id: str) -> Optional[dict]:
        async with self._db.execute("SELECT * FROM jobs WHERE job_id=?", (job_id,)) as cur:
            row = await cur.fetchone()
        return dict(row) if row else None

    async def get_active_job(self, session_id: str) -> Optional[dict]:
        async with self._db.execute(
            """SELECT * FROM jobs WHERE session_id=? AND status IN ('pending','running')
               ORDER BY created_at DESC LIMIT 1""",
            (session_id,),
        ) as cur:
            row = await cur.fetchone()
        return dict(row) if row else None

    # ── matches ───────────────────────────────────────────────────────────────

    async def upsert_match(
        self, match_id: str, session_id: str, folder_path: str,
        summary: dict, has_analysis: bool = False,
    ) -> None:
        await self._db.execute(
            "INSERT OR REPLACE INTO matches VALUES (?,?,?,?,?,?)",
            (match_id, session_id, folder_path, json.dumps(summary),
             1 if has_analysis else 0, self._now()),
        )
        await self._db.commit()

    async def mark_analysis_done(self, match_id: str) -> None:
        await self._db.execute(
            "UPDATE matches SET has_analysis=1 WHERE match_id=?", (match_id,)
        )
        await self._db.commit()

    async def get_matches(self, session_id: str) -> list:
        async with self._db.execute(
            "SELECT * FROM matches WHERE session_id=? ORDER BY created_at DESC",
            (session_id,),
        ) as cur:
            rows = await cur.fetchall()
        result = []
        for r in rows:
            d = dict(r)
            d["summary"] = json.loads(d["summary"])
            result.append(d)
        return result

    async def get_match(self, match_id: str, session_id: str) -> Optional[dict]:
        async with self._db.execute(
            "SELECT * FROM matches WHERE match_id=? AND session_id=?",
            (match_id, session_id),
        ) as cur:
            row = await cur.fetchone()
        if not row:
            return None
        d = dict(row)
        d["summary"] = json.loads(d["summary"])
        return d

    # ── profiles ──────────────────────────────────────────────────────────────

    async def upsert_profile(self, session_id: str, data: dict) -> None:
        now = self._now()
        existing = await self.get_profile(session_id)
        created = existing["created_at"] if existing else now
        await self._db.execute(
            """INSERT OR REPLACE INTO profiles
               (session_id, platform, gamemode, team_size, current_rank, target_rank,
                mins_per_day, days_per_week, duo_partner, freestyle, display_name,
                stats_json, created_at, updated_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                session_id,
                data.get("platform", "steam"),
                data.get("gamemode", "2v2"),
                data.get("team_size", 2),
                data.get("current_rank"),
                data.get("target_rank"),
                data.get("mins_per_day", 60),
                data.get("days_per_week", 5),
                data.get("duo_partner"),
                1 if data.get("freestyle") else 0,
                data.get("display_name"),
                json.dumps(data.get("stats")) if data.get("stats") else None,
                created, now,
            ),
        )
        await self._db.commit()

    async def get_profile(self, session_id: str) -> Optional[dict]:
        async with self._db.execute(
            "SELECT * FROM profiles WHERE session_id=?", (session_id,)
        ) as cur:
            row = await cur.fetchone()
        if not row:
            return None
        d = dict(row)
        if d.get("stats_json"):
            d["stats"] = json.loads(d["stats_json"])
        return d

    async def update_profile_stats(self, session_id: str, stats: dict) -> None:
        await self._db.execute(
            "UPDATE profiles SET stats_json=?, updated_at=? WHERE session_id=?",
            (json.dumps(stats), self._now(), session_id),
        )
        await self._db.commit()

    # ── coaching plans ─────────────────────────────────────────────────────────

    async def save_coaching_plan(
        self, plan_id: str, session_id: str, content_md: str, replay_guids: list
    ) -> None:
        await self._db.execute(
            "INSERT OR REPLACE INTO coaching_plans VALUES (?,?,?,?,?)",
            (plan_id, session_id, content_md, json.dumps(replay_guids), self._now()),
        )
        await self._db.commit()

    async def get_latest_coaching_plan(self, session_id: str) -> Optional[dict]:
        async with self._db.execute(
            """SELECT * FROM coaching_plans WHERE session_id=?
               ORDER BY generated_at DESC LIMIT 1""",
            (session_id,),
        ) as cur:
            row = await cur.fetchone()
        if not row:
            return None
        d = dict(row)
        d["replay_guids"] = json.loads(d["replay_guids"])
        return d
