"""Door Knock nonce service.

Generates single-use, time-limited nonces for reply-to email validation.
"""

import logging
import secrets
from datetime import datetime, timedelta, timezone

import asyncpg

from app.config import settings

logger = logging.getLogger(__name__)

NONCE_BYTES = 24  # 32 base64url chars, ~192 bits entropy
NONCE_TTL_MINUTES = 30


async def generate_nonce(pool: asyncpg.Pool, agent_id: str) -> str:
    """Generate a nonce, store it, return the nonce string."""
    nonce = secrets.token_urlsafe(NONCE_BYTES)
    expires_at = datetime.now(timezone.utc) + timedelta(minutes=NONCE_TTL_MINUTES)

    await pool.execute(
        """
        INSERT INTO nonces (agent_id, nonce, expires_at)
        VALUES ($1, $2, $3)
        """,
        agent_id,
        nonce,
        expires_at,
    )
    return nonce


async def validate_nonce(pool: asyncpg.Pool, nonce_str: str) -> str | None:
    """Validate and burn a nonce. Returns agent_id if valid, None otherwise."""
    row = await pool.fetchrow(
        """
        UPDATE nonces
        SET burned = TRUE, burned_at = now()
        WHERE nonce = $1
          AND burned = FALSE
          AND expires_at > now()
        RETURNING agent_id
        """,
        nonce_str,
    )
    if row is None:
        return None
    return str(row["agent_id"])


def build_reply_to(agent_address: str, nonce: str) -> str:
    """Build reply-to address with nonce: agent+nonce@domain."""
    return f"{agent_address}+{nonce}@{settings.mail_domain}"


async def cleanup_expired_nonces(pool: asyncpg.Pool) -> int:
    """Delete expired or burned nonces older than 1 hour. Returns count deleted."""
    result = await pool.execute(
        """
        DELETE FROM nonces
        WHERE (expires_at < now() - interval '1 hour')
           OR (burned = TRUE AND burned_at < now() - interval '1 hour')
        """
    )
    # asyncpg returns "DELETE N"
    count = int(result.split()[-1])
    if count > 0:
        logger.info("Cleaned up %d expired nonces", count)
    return count
