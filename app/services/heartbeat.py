import asyncio
import logging

from app.db import get_pool
from app.services.email import send_email
from app.services.nonce import build_reply_to, generate_nonce
from app.services.signing import sign_alert_url
from app.config import settings

logger = logging.getLogger(__name__)

# Tracks last_seen_at from the previous check cycle per agent.
# Only trigger "agent down" if the timestamp hasn't changed between
# two consecutive checks AND exceeds the timeout. This eliminates
# beat-frequency false positives from throttled heartbeat writes.
_previous_seen: dict[str, object] = {}  # {agent_id: last_seen_at}


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
            # happen on the same Postgres session.
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
    """Core heartbeat check logic. Caller holds advisory lock on conn.

    Two conditions must BOTH be true to declare an agent down:
    1. last_seen_at exceeds heartbeat_timeout (the timestamp is stale)
    2. last_seen_at hasn't changed since the previous check cycle

    Condition 2 eliminates beat-frequency false positives: if the agent
    is polling and heartbeat writes are just throttled, last_seen_at will
    change between checks even if it looks "old" at any single point.
    """
    # Get candidates: stale last_seen_at, not already notified
    candidates = await conn.fetch(
        """
        SELECT id, address, allowed_contact, credit_balance,
               last_seen_at, user_id, nonce_enabled, heartbeat_timeout
        FROM agents
        WHERE alert_status = 'active'
          AND heartbeat_enabled = TRUE
          AND last_seen_at IS NOT NULL
          AND last_seen_at < now() - (heartbeat_timeout * interval '1 second')
          AND agent_down_notified = FALSE
          AND (alert_mute_until IS NULL OR alert_mute_until < now())
        """
    )

    for agent in candidates:
        agent_id = str(agent["id"])
        current_seen = agent["last_seen_at"]
        previous_seen = _previous_seen.get(agent_id)

        # Update our memory of this agent's last_seen_at for next cycle
        _previous_seen[agent_id] = current_seen

        # Only trigger if last_seen_at hasn't changed since last check.
        # If it changed, the agent is alive — writes are just throttled.
        if previous_seen is None or current_seen != previous_seen:
            continue

        # Both conditions met: stale AND unchanged. Agent is truly down.
        address = agent["address"]
        contact = agent["allowed_contact"]
        credits = agent["credit_balance"]
        last_seen = current_seen.strftime("%I:%M%p %Z")

        footer = _build_alert_footer(
            agent_id, address, credits, f"OFFLINE (last seen: {last_seen})"
        )

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

    # Also track agents that are NOT candidates (alive) — update their
    # _previous_seen so we have fresh baselines.
    alive = await conn.fetch(
        """
        SELECT id, last_seen_at FROM agents
        WHERE heartbeat_enabled = TRUE AND last_seen_at IS NOT NULL
        """
    )
    for agent in alive:
        _previous_seen[str(agent["id"])] = agent["last_seen_at"]

    # Un-mute expired mutes
    await conn.execute(
        """
        UPDATE agents
        SET alert_status = 'active', alert_mute_until = NULL
        WHERE alert_mute_until IS NOT NULL AND alert_mute_until < now()
        """
    )
