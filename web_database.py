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


def encrypt_state(value: str) -> str:
    """Sign+encrypt a short-lived state string for OAuth/OpenID round-trips
    (e.g. the session id carried through Steam's redirect). Falls back to
    urlsafe base64 when no ENCRYPTION_KEY is set (dev only — not tamper-proof)."""
    f = _fernet()
    if f:
        return f.encrypt(value.encode()).decode()
    return base64.urlsafe_b64encode(value.encode()).decode()


def decrypt_state(token: str, max_age_s: int = 600) -> Optional[str]:
    """Reverse encrypt_state, enforcing a max age. None if invalid/expired."""
    if not token:
        return None
    f = _fernet()
    if f:
        try:
            return f.decrypt(token.encode(), ttl=max_age_s).decode()
        except Exception:
            return None
    try:
        return base64.urlsafe_b64decode(token.encode()).decode()
    except Exception:
        return None

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

CREATE TABLE IF NOT EXISTS trackers (
    session_id  TEXT PRIMARY KEY,
    state       TEXT NOT NULL DEFAULT '{}',
    updated_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS series_reports (
    report_id    TEXT PRIMARY KEY,
    session_id   TEXT NOT NULL,
    content      TEXT NOT NULL,
    games        INTEGER NOT NULL DEFAULT 0,
    generated_at TEXT NOT NULL
);

-- Per-type daily AI usage (match analysis vs series), 1/day each.
CREATE TABLE IF NOT EXISTS usage_daily (
    eos_account_id TEXT NOT NULL,
    usage_date     TEXT NOT NULL,
    kind           TEXT NOT NULL,   -- 'match' | 'series'
    count          INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (eos_account_id, usage_date, kind)
);

-- Time-series of the tracked player's framework metrics, captured on each match
-- analysis / series / plan, so My Stats can chart progression over time.
CREATE TABLE IF NOT EXISTS metric_history (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id     TEXT NOT NULL,
    eos_account_id TEXT,
    source         TEXT NOT NULL,   -- 'match' | 'series' | 'plan'
    captured_at    TEXT NOT NULL,
    metrics        TEXT NOT NULL    -- JSON {metric_key: number}
);
CREATE INDEX IF NOT EXISTS idx_metric_history_sess
    ON metric_history(session_id, captured_at);

-- Server-enforced coaching plan cycle: 1 regenerate per cycle, then the user must
-- "Mark Plan Complete" to start a fresh cycle. (Not in the user-writable tracker.)
CREATE TABLE IF NOT EXISTS plan_state (
    session_id   TEXT PRIMARY KEY,
    cycle_no     INTEGER NOT NULL DEFAULT 0,
    regens_used  INTEGER NOT NULL DEFAULT 0,
    plan_id      TEXT,
    active       INTEGER NOT NULL DEFAULT 0,
    started_at   TEXT,
    updated_at   TEXT NOT NULL
);

-- Single dedicated "service" Epic account used to look up registered players'
-- public rank/stats BY ID in the background (TRN-style), so we never use a real
-- user's connection (= never risk disconnecting them mid-match). Tokens encrypted.
CREATE TABLE IF NOT EXISTS service_account (
    id          INTEGER PRIMARY KEY CHECK (id = 1),
    tokens      TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);

-- Background-refreshed rank/lifetime snapshots per account (read by the stats page
-- so it doesn't need a live PsyNet call).
CREATE TABLE IF NOT EXISTS account_stats (
    eos_account_id TEXT PRIMARY KEY,
    ranks_json     TEXT,
    lifetime_json  TEXT,
    updated_at     TEXT NOT NULL
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

    async def delete_account(self, session_id: str) -> None:
        """Permanently delete the user and ALL their data across every table."""
        async with self._db.execute(
            "SELECT user_id, eos_account_id FROM sessions WHERE session_id=?", (session_id,)
        ) as cur:
            row = await cur.fetchone()
        user_id = row["user_id"] if row else None
        eos = row["eos_account_id"] if row else None
        for tbl in ("matches", "jobs", "profiles", "coaching_plans", "trackers",
                    "series_reports", "sessions"):
            await self._db.execute(f"DELETE FROM {tbl} WHERE session_id=?", (session_id,))
        if eos:
            await self._db.execute("DELETE FROM analysis_usage WHERE eos_account_id=?", (eos,))
        if user_id:
            await self._db.execute("DELETE FROM users WHERE user_id=?", (user_id,))
        await self._db.commit()

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

    async def update_display_name(self, session_id: str, name: str) -> None:
        """Update the session + profile display name (used by Refresh username)."""
        await self._db.execute(
            "UPDATE sessions SET display_name=? WHERE session_id=?", (name, session_id)
        )
        await self._db.execute(
            "UPDATE profiles SET display_name=? WHERE session_id=?", (name, session_id)
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

    # ── per-type daily usage (match analysis / series — 1/day each) ──────────────

    async def get_usage_kind(self, eos_account_id: str, usage_date: str, kind: str) -> int:
        async with self._db.execute(
            "SELECT count FROM usage_daily WHERE eos_account_id=? AND usage_date=? AND kind=?",
            (eos_account_id, usage_date, kind),
        ) as cur:
            row = await cur.fetchone()
        return row["count"] if row else 0

    async def incr_usage_kind(self, eos_account_id: str, usage_date: str, kind: str) -> int:
        await self._db.execute(
            """INSERT INTO usage_daily (eos_account_id, usage_date, kind, count) VALUES (?,?,?,1)
               ON CONFLICT(eos_account_id, usage_date, kind)
               DO UPDATE SET count = count + 1""",
            (eos_account_id, usage_date, kind),
        )
        await self._db.commit()
        return await self.get_usage_kind(eos_account_id, usage_date, kind)

    # ── metric history (skill progression over time) ─────────────────────────────

    async def add_metric_snapshot(self, session_id: str, eos_account_id: Optional[str],
                                  source: str, metrics: dict) -> None:
        if not metrics:
            return
        await self._db.execute(
            "INSERT INTO metric_history (session_id, eos_account_id, source, captured_at, metrics)"
            " VALUES (?,?,?,?,?)",
            (session_id, eos_account_id or "", source, self._now(), json.dumps(metrics)),
        )
        await self._db.commit()

    async def get_metric_history(self, session_id: str, limit: int = 400) -> list:
        async with self._db.execute(
            """SELECT source, captured_at, metrics FROM metric_history
               WHERE session_id=? ORDER BY captured_at ASC LIMIT ?""",
            (session_id, limit),
        ) as cur:
            rows = await cur.fetchall()
        out = []
        for r in rows:
            try:
                m = json.loads(r["metrics"])
            except Exception:
                m = {}
            out.append({"source": r["source"], "captured_at": r["captured_at"], "metrics": m})
        return out

    # ── coaching plan cycle (server-enforced regenerate gating) ──────────────────

    async def get_plan_state(self, session_id: str) -> dict:
        async with self._db.execute(
            "SELECT cycle_no, regens_used, plan_id, active, started_at FROM plan_state WHERE session_id=?",
            (session_id,),
        ) as cur:
            row = await cur.fetchone()
        if not row:
            return {"cycle_no": 0, "regens_used": 0, "plan_id": None, "active": 0, "started_at": None}
        return dict(row)

    async def apply_plan_generated(self, session_id: str, plan_id: str) -> dict:
        """Record a successful plan generation. If a cycle is active this counts as
        a regenerate; otherwise it starts a new cycle (regens reset to 0)."""
        st = await self.get_plan_state(session_id)
        now = self._now()
        if st["active"]:
            cycle = st["cycle_no"]
            regens = st["regens_used"] + 1
            started = st["started_at"] or now
        else:
            cycle = st["cycle_no"] + 1
            regens = 0
            started = now
        await self._db.execute(
            """INSERT INTO plan_state (session_id, cycle_no, regens_used, plan_id, active, started_at, updated_at)
               VALUES (?,?,?,?,1,?,?)
               ON CONFLICT(session_id) DO UPDATE SET
                 cycle_no=excluded.cycle_no, regens_used=excluded.regens_used,
                 plan_id=excluded.plan_id, active=1, started_at=excluded.started_at,
                 updated_at=excluded.updated_at""",
            (session_id, cycle, regens, plan_id, started, now),
        )
        await self._db.commit()
        return await self.get_plan_state(session_id)

    async def complete_plan_cycle(self, session_id: str) -> dict:
        await self._db.execute(
            "UPDATE plan_state SET active=0, updated_at=? WHERE session_id=?",
            (self._now(), session_id),
        )
        await self._db.commit()
        return await self.get_plan_state(session_id)

    # ── service account + background-refreshed stats ─────────────────────────────

    async def save_service_tokens(self, tokens: dict) -> None:
        await self._db.execute(
            """INSERT INTO service_account (id, tokens, updated_at) VALUES (1, ?, ?)
               ON CONFLICT(id) DO UPDATE SET tokens=excluded.tokens, updated_at=excluded.updated_at""",
            (_encrypt(json.dumps(tokens)), self._now()),
        )
        await self._db.commit()

    async def get_service_tokens(self) -> Optional[dict]:
        async with self._db.execute("SELECT tokens FROM service_account WHERE id=1") as cur:
            row = await cur.fetchone()
        if not row:
            return None
        try:
            return json.loads(_decrypt(row["tokens"]))
        except Exception:
            return None

    async def list_refresh_targets(self) -> list:
        """Active users with an identity we can look up by ID, + their gamemode."""
        async with self._db.execute(
            """SELECT s.session_id, s.eos_account_id, s.player_id, p.gamemode
               FROM sessions s LEFT JOIN profiles p ON p.session_id = s.session_id
               WHERE s.eos_account_id IS NOT NULL AND s.eos_account_id <> ''"""
        ) as cur:
            return [dict(r) for r in await cur.fetchall()]

    async def save_account_stats(self, eos_account_id: str, ranks, lifetime) -> None:
        await self._db.execute(
            """INSERT INTO account_stats (eos_account_id, ranks_json, lifetime_json, updated_at)
               VALUES (?,?,?,?)
               ON CONFLICT(eos_account_id) DO UPDATE SET
                 ranks_json=excluded.ranks_json, lifetime_json=excluded.lifetime_json,
                 updated_at=excluded.updated_at""",
            (eos_account_id,
             json.dumps(ranks) if ranks is not None else None,
             json.dumps(lifetime) if lifetime is not None else None,
             self._now()),
        )
        await self._db.commit()

    async def get_account_stats(self, eos_account_id: str) -> Optional[dict]:
        async with self._db.execute(
            "SELECT ranks_json, lifetime_json, updated_at FROM account_stats WHERE eos_account_id=?",
            (eos_account_id,),
        ) as cur:
            row = await cur.fetchone()
        if not row:
            return None
        return {
            "ranks": json.loads(row["ranks_json"]) if row["ranks_json"] else None,
            "lifetime": json.loads(row["lifetime_json"]) if row["lifetime_json"] else None,
            "updated_at": row["updated_at"],
        }

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

    async def list_coaching_plans(self, session_id: str) -> list:
        async with self._db.execute(
            """SELECT plan_id, content_md, generated_at FROM coaching_plans
               WHERE session_id=? ORDER BY generated_at DESC""",
            (session_id,),
        ) as cur:
            return [dict(r) for r in await cur.fetchall()]

    async def get_coaching_plan(self, plan_id: str, session_id: str) -> Optional[dict]:
        async with self._db.execute(
            "SELECT * FROM coaching_plans WHERE plan_id=? AND session_id=?",
            (plan_id, session_id),
        ) as cur:
            row = await cur.fetchone()
        if not row:
            return None
        d = dict(row)
        d["replay_guids"] = json.loads(d["replay_guids"])
        return d

    async def delete_coaching_plan(self, plan_id: str, session_id: str) -> None:
        await self._db.execute(
            "DELETE FROM coaching_plans WHERE plan_id=? AND session_id=?", (plan_id, session_id)
        )
        await self._db.commit()

    # ── tracker ────────────────────────────────────────────────────────────────

    async def get_tracker(self, session_id: str) -> dict:
        async with self._db.execute(
            "SELECT state FROM trackers WHERE session_id=?", (session_id,)
        ) as cur:
            row = await cur.fetchone()
        if not row:
            return {}
        try:
            return json.loads(row["state"])
        except Exception:
            return {}

    async def save_tracker(self, session_id: str, state: dict) -> None:
        await self._db.execute(
            "INSERT OR REPLACE INTO trackers (session_id, state, updated_at) VALUES (?,?,?)",
            (session_id, json.dumps(state), self._now()),
        )
        await self._db.commit()

    # ── series reports ──────────────────────────────────────────────────────────

    async def save_series_report(self, report_id: str, session_id: str,
                                 content: str, games: int) -> None:
        await self._db.execute(
            "INSERT OR REPLACE INTO series_reports VALUES (?,?,?,?,?)",
            (report_id, session_id, content, games, self._now()),
        )
        await self._db.commit()

    async def get_latest_series(self, session_id: str) -> Optional[dict]:
        async with self._db.execute(
            "SELECT * FROM series_reports WHERE session_id=? ORDER BY generated_at DESC LIMIT 1",
            (session_id,),
        ) as cur:
            row = await cur.fetchone()
        return dict(row) if row else None

    async def list_series_reports(self, session_id: str) -> list:
        async with self._db.execute(
            """SELECT report_id, games, generated_at FROM series_reports
               WHERE session_id=? ORDER BY generated_at DESC""",
            (session_id,),
        ) as cur:
            return [dict(r) for r in await cur.fetchall()]

    async def get_series_report(self, report_id: str, session_id: str) -> Optional[dict]:
        async with self._db.execute(
            "SELECT * FROM series_reports WHERE report_id=? AND session_id=?",
            (report_id, session_id),
        ) as cur:
            row = await cur.fetchone()
        return dict(row) if row else None

    async def delete_series_report(self, report_id: str, session_id: str) -> None:
        await self._db.execute(
            "DELETE FROM series_reports WHERE report_id=? AND session_id=?", (report_id, session_id)
        )
        await self._db.commit()
