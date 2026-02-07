import logging

from app.config import settings

logger = logging.getLogger(__name__)


async def send_email(from_address: str, to_address: str, subject: str, body: str):
    """Send an email via SES. Currently mocked for local development."""
    if not settings.aws_access_key_id:
        logger.info(
            "MOCK EMAIL: from=%s to=%s subject=%s body=%s",
            from_address,
            to_address,
            subject,
            body[:200],
        )
        return

    # TODO: Real SES implementation
    import boto3

    client = boto3.client(
        "ses",
        region_name=settings.aws_region,
        aws_access_key_id=settings.aws_access_key_id,
        aws_secret_access_key=settings.aws_secret_access_key,
    )
    client.send_email(
        Source=from_address,
        Destination={"ToAddresses": [to_address]},
        Message={
            "Subject": {"Data": subject, "Charset": "UTF-8"},
            "Body": {"Text": {"Data": body, "Charset": "UTF-8"}},
        },
    )


def build_footer(agent_address: str, credits_remaining: int) -> str:
    """Build the mandatory email footer."""
    return (
        f"\n---\n"
        f"Agent alive (last seen: just now)\n"
        f"Credits: {credits_remaining} messages remaining\n"
    )
