import hashlib
import secrets

from fastapi import Depends, HTTPException, Security
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.db import get_pool

PREFIX = "sm_live_"
security = HTTPBearer()


def generate_api_key() -> tuple[str, str, str]:
    """Generate a new API key. Returns (full_key, key_hash, key_prefix)."""
    raw = secrets.token_bytes(32)
    key = PREFIX + secrets.token_urlsafe(32)
    key_hash = hashlib.sha256(key.encode()).hexdigest()
    key_prefix = key[:16]
    return key, key_hash, key_prefix


def hash_key(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()


async def get_agent_id(
    credentials: HTTPAuthorizationCredentials = Security(security),
) -> str:
    """Validate API key and return agent_id."""
    token = credentials.credentials
    if not token.startswith(PREFIX):
        raise HTTPException(status_code=401, detail="Invalid API key")

    token_hash = hash_key(token)
    prefix = token[:16]

    pool = await get_pool()
    row = await pool.fetchrow(
        "SELECT agent_id FROM api_keys WHERE key_prefix = $1 AND key_hash = $2",
        prefix,
        token_hash,
    )
    if not row:
        raise HTTPException(status_code=401, detail="Invalid API key")

    return str(row["agent_id"])
