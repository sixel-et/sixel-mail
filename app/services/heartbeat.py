import asyncio
import logging

from app.db import get_pool
from app.services.email import send_email
from app.services.nonce import build_reply_to, generate_nonce
from app.services.signing import sign_alert_url
from app.config import settings

logger = logging.getLogger(__name__)

# Minimum timeout floor: must be MORE than 2x the heartbeat write interval
# in api.py (HEARTBEAT_INTERVAL = 600s). After recovery, the next regular
# write is one full interval away, then the timeout counts from THAT write.
# So minimum safe floor = 2 * interval + margin.
MIN_TIMEOUT_SECONDS = 1800  # 30 minutes (2x600 + 600 margin)


def _build_alert_footer(agent_id: str, agent_address: str, credits: int, status: str) -> str:
    on_url = sign_alert_url(agent_id, "on")
    pause1_url = sign_alert_url(agent_id, "pause1h")
    pause8_url = sign_alert_url(agent_id, "pause8h")
    mute_url = sign_alert_url(agent_id, "mute")
    topup_url = sign_alert_url(agent_id, "topup")

    return (
        f"\n---\n"
        f"Agent {status}\n"
        f"Credits: {credits} messages remaining\n\n"
        f"Turn alerts ON: {on_url}\n"
        f"Pause 1hr: {pause1_url}\n"
        f"Pause 8hr: {pause8_url}\n"
        f"Mute until tomorrow: {mute_url}\n\n"
        f"Add $5 credit: {settings.api_base_url}/topup?agent_id={agent_id}"
    )


async def heartbeat_loop():
    """Check for agents that have stopped polling and send alerts."""
    logger.info("Heartbeat checker started")
    while True:
        try:
            pool = await get_pool()

            # Use a single connection for advisory lock to ensure lock/unlock
            # happen on the same Postgres session. Connection pool otherwise
            # routes lock and unlock to different connections, breaking the lock.
            async with pool.acquire() as conn:
                got_lock = await conn.fetchval("SELECT pg_try_advisory_lock(8675309)")
                if not got_lock:
                    await asyncio.sleep(60)
                    continue

                try:
                    await _run_heartbeat_check(conn)
                finally:
                    await conn.execute("SELECT pg_advisory_unlock(8675309)")

        except asyncio.CancelledError:
            logger.info("Heartbeat checker stopped")
            return
        except Exception:
            logger.exception("Heartbeat checker error")

        await asyncio.sleep(60)


async def _run_heartbeat_check(conn):
    """Core heartbeat check logic. Caller holds advisory lock on conn."""
    # Find agents that have gone silent.
    # Uses GREATEST to enforce a minimum timeout floor regardless of what's
    # stored in the DB column. Prevents false positives from timeout < write interval.
    overdue = await conn.fetch(
        f"""
        SELECT id, address, allowed_contact, credit_balance,
               last_seen_at, user_id, nonce_enabled
        FROM agents
        WHERE alert_status = 'active'
          AND heartbeat_enabled = TRUE
          AND last_seen_at IS NOT NULL
          AND last_seen_at < now() - (GREATEST(heartbeat_timeout, {MIN_TIMEOUT_SECONDS}) * interval '1 second')
          AND agent_down_notified = FALSE
          AND (alert_mute_until IS NULL OR alert_mute_until < now())
        """
    )

    for agent in overdue:
        agent_id = str(agent["id"])
        address = agent["address"]
        contact = agent["allowed_contact"]
        credits = agent["credit_balance"]
        last_seen = agent["last_seen_at"].strftime("%I:%M%p %Z")

        footer = _build_alert_footer(
            agent_id, address, credits, f"OFFLINE (last seen: {last_seen})"
        )

        # Generate nonce for alert reply-to (only if nonce_enabled)
        if agent.get("nonce_enabled", False):
            alert_nonce = await generate_nonce(conn, agent_id)
            alert_reply_to = build_reply_to(address, alert_nonce)
        else:
            alert_reply_to = f"{address}@{settings.mail_domain}"

        await send_email(
            from_address=f"{address}@{settings.mail_domain}",
            to_address=contact,
            subject=f"[{address}] stopped responding",
            body=(
                f"Your agent {address}@{settings.mail_domain} hasn't checked in since "
                f"{last_seen}."
                f"{footer}"
            ),
            reply_to=alert_reply_to,
        )

        await conn.execute(
            "UPDATE agents SET agent_down_notified = TRUE WHERE id = $1",
            agent["id"],
        )
        logger.info("Sent agent-down alert for %s", address)

    # Un-mute expired mutes
    await conn.execute(
        """
        UPDATE agents
        SET alert_status = 'active', alert_mute_until = NULL
        WHERE alert_mute_until IS NOT NULL AND alert_mute_until < now()
        """
    )
