"""
One-time linker for the background-stats SERVICE Epic account.

Run inside the app container (shares the data volume + ENCRYPTION_KEY), logged in
as the dedicated throwaway Epic account:

    docker compose -f docker-compose.yml -f docker-compose.prod.yml \
        exec app python -m rlcoach.service_link

It prints an Epic activate URL + code; open it, sign in as the SERVICE account,
click Confirm. The tokens are stored encrypted in the DB and the background
refresher picks them up automatically (no restart needed).
"""
import asyncio

from web_database import Database
from rlcoach.service_refresh import link_service_account


async def _main() -> None:
    db = Database()
    await db.init()
    try:
        await link_service_account(db)
    finally:
        await db.close()


if __name__ == "__main__":
    asyncio.run(_main())
