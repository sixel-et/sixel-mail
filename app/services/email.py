import logging
import time

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

# Daily email cap per agent. Matches Resend free tier (100/day).
# In-memory, resets at midnight UTC. Caps ALL emails from an agent —
# sends, heartbeat alerts, knock replies, recovery notifications.
DAILY_PER_USER_LIMIT = 100
_daily_per_user: dict[str, dict] = {}  # {from_address: {"count": N, "day": D}}


def _check_daily_limit(from_address: str) -> bool:
    """Returns True if under the per-user daily limit."""
    today = int(time.time()) // 86400
    user = _daily_per_user.get(from_address)
    if not user or user["day"] != today:
        _daily_per_user[from_address] = {"count": 0, "day": today}
        user = _daily_per_user[from_address]
    if user["count"] >= DAILY_PER_USER_LIMIT:
        return False
    user["count"] += 1
    return True


async def send_email(
    from_address: str,
    to_address: str,
    subject: str,
    body: str,
    reply_to: str | None = None,
    attachments: list[dict] | None = None,
):
    """Send an email via Resend."""
    if not _check_daily_limit(from_address):
        logger.warning("Daily per-user email limit reached (%d), dropping: %s -> %s subj=%s",
                        DAILY_PER_USER_LIMIT, from_address, to_address, subject)
        return

    if not settings.resend_api_key:
        logger.info(
            "MOCK EMAIL: from=%s to=%s reply_to=%s subject=%s body=%s",
            from_address,
            to_address,
            reply_to,
            subject,
            body[:200],
        )
        return

    payload = {
        "from": from_address,
        "to": [to_address],
        "subject": subject,
        "text": body,
    }
    if reply_to:
        payload["reply_to"] = reply_to
    if attachments:
        payload["attachments"] = attachments

    async with httpx.AsyncClient() as client:
        resp = await client.post(
            "https://api.resend.com/emails",
            headers={
                "Authorization": f"Bearer {settings.resend_api_key}",
                "Content-Type": "application/json",
            },
            json=payload,
        )
        if resp.status_code != 200:
            logger.error("Resend API error: %s %s", resp.status_code, resp.text)
            raise Exception(f"Email send failed: {resp.status_code}")
        logger.info("Email sent via Resend: %s -> %s", from_address, to_address)


def build_footer(agent_address: str, credits_remaining: int) -> str:
    """Build the mandatory email footer."""
    return (
        f"\n---\n"
        f"Agent alive (last seen: just now)\n"
        f"Credits: {credits_remaining} messages remaining\n"
    )
