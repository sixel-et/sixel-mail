import logging

import httpx

from app.config import settings

logger = logging.getLogger(__name__)


async def send_email(
    from_address: str,
    to_address: str,
    subject: str,
    body: str,
    reply_to: str | None = None,
    attachments: list[dict] | None = None,
):
    """Send an email via Resend."""
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
