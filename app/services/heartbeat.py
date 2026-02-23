import asyncio
import logging

from app.db import get_pool
from app.services.email import send_email
from app.services.nonce import build_reply_to, generate_nonce
from app.services.signing import sign_alert_url
from app.config import settings

logger = logging.getLogger(__name__)


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

            # Find agents that have gone silent
            overdue = await pool.fetch(
                """
                SELECT id, address, allowed_contact, credit_balance,
                       last_seen_at, user_id, nonce_enabled
                FROM agents
                WHERE alert_status = 'active'
                  AND heartbeat_enabled = TRUE
                  AND last_seen_at IS NOT NULL
                  AND last_seen_at < now() - (heartbeat_timeout * interval '1 second')
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
                    alert_nonce = await generate_nonce(pool, agent_id)
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

                await pool.execute(
                    "UPDATE agents SET agent_down_notified = TRUE WHERE id = $1",
                    agent["id"],
                )
                logger.info("Sent agent-down alert for %s", address)

            # Un-mute expired mutes
            await pool.execute(
                """
                UPDATE agents
                SET alert_status = 'active', alert_mute_until = NULL
                WHERE alert_mute_until IS NOT NULL AND alert_mute_until < now()
                """
            )

        except asyncio.CancelledError:
            logger.info("Heartbeat checker stopped")
            return
        except Exception:
            logger.exception("Heartbeat checker error")

        await asyncio.sleep(60)
