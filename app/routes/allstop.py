"""All-Stop: emergency channel kill switch.

GET /allstop?agent=<address>&key=<key>

Validates pre-shared key, deactivates the agent's email channel.
Reactivation only via live text session (direct DB update or admin endpoint).

The key is pre-shared out-of-band (never over email). Eric bookmarks the URL.
"""

import hashlib
import hmac
import logging

from fastapi import APIRouter, HTTPException, Request

from app.db import get_pool

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/allstop")
async def allstop(agent: str, key: str):
    """Emergency channel shutdown. Disables all inbound email processing."""
    pool = await get_pool()

    row = await pool.fetchrow(
        "SELECT id, allstop_key_hash, channel_active FROM agents WHERE address = $1",
        agent.lower().strip(),
    )
    if not row:
        # Don't reveal whether agent exists
        raise HTTPException(status_code=404, detail="Not found")

    if not row["allstop_key_hash"]:
        raise HTTPException(status_code=404, detail="Not found")

    # Verify key (stored as SHA-256 hash)
    key_hash = hashlib.sha256(key.encode()).hexdigest()
    if not hmac.compare_digest(key_hash, row["allstop_key_hash"]):
        raise HTTPException(status_code=404, detail="Not found")

    if not row["channel_active"]:
        return {
            "status": "already_inactive",
            "message": f"Channel for {agent} was already deactivated.",
        }

    await pool.execute(
        "UPDATE agents SET channel_active = FALSE WHERE id = $1",
        row["id"],
    )
    logger.warning("ALL-STOP triggered for agent %s", agent)

    return {
        "status": "deactivated",
        "message": f"Channel for {agent} has been shut down. Reactivate via live text session.",
    }
