"""
Background stats refresher (TRN-style, disconnect-safe).

A single dedicated "service" Epic account looks up every registered user's PUBLIC
rank/MMR and lifetime totals BY ID. Because it's the service account's own PsyNet
connection — never a real user's — it can run in the background without any risk
of disconnecting players from their live matches (the cross-player lookups were
verified via /api/debug/psynet-probe).

It refreshes:
  - rank/MMR per playlist  -> cached in account_stats + a daily MMR snapshot logged
    into each user's tracker (so the MMR chart fills in even if they never open the app)
  - lifetime totals        -> cached in account_stats (read by /api/stats/lifetime)

Replays/match history are account-private (AccessDenied cross-player) and stay
on-demand with the user's own token — they are NOT touched here.

Dormant until a service account is linked (see link_service_account / the
`python -m rlcoach.service_link` CLI). With no service token the loop no-ops.
"""
from __future__ import annotations

import asyncio
import logging
import os
from datetime import date

log = logging.getLogger(__name__)

INTERVAL_MIN = int(os.environ.get("SERVICE_REFRESH_INTERVAL_MIN", "180"))   # full pass cadence
STAGGER_S = float(os.environ.get("SERVICE_REFRESH_STAGGER_S", "3"))         # gap between accounts
START_DELAY_S = int(os.environ.get("SERVICE_REFRESH_START_DELAY_S", "60"))  # delay after boot


def _target_pid(eos_account_id: str):
    """Canonical PsyNet PlayerID for a registered user — their authenticated Epic
    (RL) account. That's the account we know is theirs, so its ranks are correct."""
    return f"Epic|{eos_account_id}|0" if eos_account_id else None


def _refresh_tokens_sync(tokens: dict):
    """If the service access token is expired, refresh it via the EOS refresh token
    (which rotates — caller must persist the result). Returns (tokens, changed)."""
    from rlcoach.psynet_auth import _is_expired
    if not _is_expired(tokens.get("eos_expires_at", "")):
        return tokens, False
    if _is_expired(tokens.get("eos_refresh_expires_at", "")):
        raise RuntimeError("service refresh token expired — re-link the service account")
    from rlapi.egs import EGS
    egs = EGS()
    try:
        new = egs.refresh_eos_token(tokens["eos_refresh_token"])
    finally:
        egs.close()
    return ({
        "eos_access_token": new.access_token,
        "eos_refresh_token": new.refresh_token,
        "eos_expires_at": new.expires_at,
        "eos_refresh_expires_at": new.refresh_expires_at,
        "account_id": new.account_id,
        "display_name": tokens.get("display_name", "Service"),
    }, True)


async def _service_creds(db):
    """Load + (refresh & persist) the service account creds. None if not linked /
    needs re-linking."""
    tokens = await db.get_service_tokens()
    if not tokens or not tokens.get("eos_refresh_token"):
        return None
    try:
        loop = asyncio.get_event_loop()
        tokens, changed = await loop.run_in_executor(None, _refresh_tokens_sync, tokens)
        if changed:
            await db.save_service_tokens(tokens)
    except Exception as e:
        log.warning("service account token refresh failed: %s", e)
        return None
    return tokens["eos_access_token"], tokens["account_id"], tokens.get("display_name", "Service")


async def _refresh_one(db, client, t: dict) -> None:
    from rlcoach.stats_api import _parse_skills_raw
    eos = t.get("eos_account_id")
    pid = _target_pid(eos)
    if not pid:
        return

    ranks = {}
    try:
        raw = await client.get_player_skill(pid, timeout=8.0)
        if raw:
            ranks = _parse_skills_raw(raw)
    except Exception as e:
        log.debug("rank lookup failed for %s: %s", (eos or "")[:8], e)

    lifetime = None
    try:
        lifetime = await client.get_lifetime_stats(timeout=6.0, player_id=pid)
    except Exception as e:
        log.debug("lifetime lookup failed for %s: %s", (eos or "")[:8], e)

    if ranks or lifetime:
        await db.save_account_stats(eos, ranks or None, lifetime or None)

    # Daily MMR snapshot into the user's tracker (once/day) for the progression chart.
    gm = (t.get("gamemode") or "2v2")
    entry = ranks.get(gm) if ranks else None
    if entry and entry.get("mmr_estimate"):
        tracker = await db.get_tracker(t["session_id"])
        mmrlog = list(tracker.get("mmrLog", []))
        today = date.today().isoformat()
        if not any(e.get("date") == today for e in mmrlog):
            mmrlog.append({"date": today, "mmr": entry["mmr_estimate"], "rank": entry.get("rank")})
            tracker["mmrLog"] = mmrlog
            await db.save_tracker(t["session_id"], tracker)


async def run_refresh_pass(db) -> int:
    """One pass over all registered accounts via the service connection. Returns the
    number of accounts processed (0 if dormant / no service account)."""
    creds = await _service_creds(db)
    if not creds:
        return 0
    targets = await db.list_refresh_targets()
    if not targets:
        return 0
    access_token, account_id, display_name = creds
    from rlapi.client import create_client
    client = await create_client(access_token, account_id, display_name)
    done = 0
    try:
        for t in targets:
            try:
                await _refresh_one(db, client, t)
                done += 1
            except Exception as e:
                log.debug("refresh target failed: %s", e)
            await asyncio.sleep(STAGGER_S)
    finally:
        try:
            await client.close()
        except Exception:
            pass
    log.info("service refresh pass complete: %d/%d accounts", done, len(targets))
    return done


async def scheduler_loop(db) -> None:
    """Background loop. Dormant (cheap no-op) until a service account is linked."""
    await asyncio.sleep(START_DELAY_S)
    while True:
        try:
            await run_refresh_pass(db)
        except Exception as e:
            log.warning("service refresh loop error: %s", e)
        await asyncio.sleep(max(60, INTERVAL_MIN * 60))


# ── one-time linking (CLI: python -m rlcoach.service_link) ───────────────────────

async def link_service_account(db) -> dict:
    """Run the Epic device-auth flow for the SERVICE account and store its tokens.
    Prints the activate URL + code; blocks until you confirm on Epic."""
    from rlapi.egs import (EGS, authenticate_with_device,
                           wait_for_device_authorization, get_eos_display_name)
    egs = EGS()
    try:
        device = authenticate_with_device(egs)
        print("\n=== Link the SERVICE Epic account (log in as the throwaway account) ===")
        print("Open:", device.verification_uri_complete or device.verification_uri)
        print("Code:", device.user_code, flush=True)
        eos = wait_for_device_authorization(egs, device)
        name = get_eos_display_name(eos.access_token, eos.account_id) or "Service"
        tokens = {
            "eos_access_token": eos.access_token,
            "eos_refresh_token": eos.refresh_token,
            "eos_expires_at": eos.expires_at,
            "eos_refresh_expires_at": eos.refresh_expires_at,
            "account_id": eos.account_id,
            "display_name": name,
        }
        await db.save_service_tokens(tokens)
        print(f"\nService account linked: {name} ({eos.account_id})")
        return tokens
    finally:
        egs.close()
