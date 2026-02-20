from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, field_validator

from app.auth import generate_api_key, get_agent_id
from app.config import settings
from app.db import get_pool
from app.ratelimit import POLL_LIMIT, POLL_WINDOW, SEND_LIMIT, SEND_WINDOW, limiter
from app.services.credits import deduct_credit
from app.services.email import build_footer, send_email
from app.services.nonce import build_reply_to, generate_nonce

router = APIRouter(prefix="/v1")


MAX_BODY_LENGTH = 100_000  # 100KB


class SendRequest(BaseModel):
    subject: str = ""
    body: str

    @field_validator("body")
    @classmethod
    def body_not_empty(cls, v: str) -> str:
        stripped = v.strip()
        if not stripped:
            raise ValueError("Body cannot be empty")
        if len(v) > MAX_BODY_LENGTH:
            raise ValueError(f"Body exceeds maximum length of {MAX_BODY_LENGTH} characters")
        return v


class SendResponse(BaseModel):
    id: str
    status: str
    credits_remaining: int


class MessageResponse(BaseModel):
    id: str
    subject: str | None
    body: str
    received_at: str
    encrypted: bool = False


class InboxResponse(BaseModel):
    messages: list[MessageResponse]
    credits_remaining: int
    agent_status: str


# POST /v1/send
@router.post("/send", response_model=SendResponse)
async def send_message(req: SendRequest, agent_id: str = Depends(get_agent_id)):
    if not limiter.check(f"send:{agent_id}", SEND_LIMIT, SEND_WINDOW):
        raise HTTPException(
            status_code=429,
            detail={"error": "rate_limited", "limit": f"{SEND_LIMIT} messages/day",
                    "retry_after": "try again later"},
        )

    pool = await get_pool()

    agent = await pool.fetchrow(
        "SELECT address, allowed_contact, credit_balance FROM agents WHERE id = $1",
        agent_id,
    )
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")

    new_balance = await deduct_credit(pool, agent_id, "message_sent")
    if new_balance is None:
        raise HTTPException(
            status_code=402,
            detail={
                "error": "insufficient_credits",
                "credits_remaining": 0,
                "topup_url": f"{settings.api_base_url}/topup/{agent_id}",
            },
        )

    from_addr = f"{agent['address']}@{settings.mail_domain}"
    footer = build_footer(agent["address"], new_balance)
    full_body = req.body + footer

    # Generate nonce for reply-to validation
    nonce = await generate_nonce(pool, agent_id)
    reply_to = build_reply_to(agent["address"], nonce)

    await send_email(
        from_address=from_addr,
        to_address=agent["allowed_contact"],
        subject=f"[{agent['address']}] {req.subject}",
        body=full_body,
        reply_to=reply_to,
    )

    row = await pool.fetchrow(
        """
        INSERT INTO messages (agent_id, direction, subject, body)
        VALUES ($1, 'outbound', $2, $3)
        RETURNING id
        """,
        agent_id,
        req.subject,
        req.body,
    )

    return SendResponse(
        id=str(row["id"]),
        status="sent",
        credits_remaining=new_balance,
    )


# GET /v1/inbox
@router.get("/inbox", response_model=InboxResponse)
async def get_inbox(agent_id: str = Depends(get_agent_id)):
    if not limiter.check(f"poll:{agent_id}", POLL_LIMIT, POLL_WINDOW):
        raise HTTPException(
            status_code=429,
            detail={"error": "rate_limited", "limit": f"{POLL_LIMIT} polls/min",
                    "retry_after": "slow down polling interval"},
        )

    pool = await get_pool()

    # Update heartbeat
    await pool.execute(
        """
        UPDATE agents SET last_seen_at = now()
        WHERE id = $1
        """,
        agent_id,
    )

    # Check if agent was marked down, send recovery notification
    agent = await pool.fetchrow(
        "SELECT address, allowed_contact, credit_balance, agent_down_notified FROM agents WHERE id = $1",
        agent_id,
    )
    if agent["agent_down_notified"]:
        await pool.execute(
            "UPDATE agents SET agent_down_notified = FALSE WHERE id = $1",
            agent_id,
        )
        # System emails also get nonces (no credit deduction for the nonce itself)
        recovery_nonce = await generate_nonce(pool, agent_id)
        recovery_reply_to = build_reply_to(agent["address"], recovery_nonce)
        await send_email(
            from_address=f"{agent['address']}@{settings.mail_domain}",
            to_address=agent["allowed_contact"],
            subject=f"[{agent['address']}] is back online",
            body=f"Your agent {agent['address']}@{settings.mail_domain} is responding again.",
            reply_to=recovery_reply_to,
        )

    # Fetch unread inbound messages
    rows = await pool.fetch(
        """
        SELECT id, subject, body, created_at, encrypted FROM messages
        WHERE agent_id = $1 AND direction = 'inbound' AND is_read = FALSE
        ORDER BY created_at
        """,
        agent_id,
    )

    # Mark as read
    if rows:
        ids = [row["id"] for row in rows]
        await pool.execute(
            "UPDATE messages SET is_read = TRUE WHERE id = ANY($1::uuid[])",
            ids,
        )

    messages = [
        MessageResponse(
            id=str(row["id"]),
            subject=row["subject"],
            body=row["body"],
            received_at=row["created_at"].isoformat(),
            encrypted=row.get("encrypted", False),
        )
        for row in rows
    ]

    return InboxResponse(
        messages=messages,
        credits_remaining=agent["credit_balance"],
        agent_status="alive",
    )


# GET /v1/inbox/:id
@router.get("/inbox/{message_id}", response_model=MessageResponse)
async def get_message(message_id: str, agent_id: str = Depends(get_agent_id)):
    pool = await get_pool()

    row = await pool.fetchrow(
        """
        SELECT id, subject, body, created_at, encrypted FROM messages
        WHERE id = $1 AND agent_id = $2
        """,
        message_id,
        agent_id,
    )
    if not row:
        raise HTTPException(status_code=404, detail="Message not found")

    return MessageResponse(
        id=str(row["id"]),
        subject=row["subject"],
        body=row["body"],
        received_at=row["created_at"].isoformat(),
        encrypted=row.get("encrypted", False),
    )


# POST /v1/rotate-key
@router.post("/rotate-key")
async def rotate_key(agent_id: str = Depends(get_agent_id)):
    pool = await get_pool()

    # Generate new key
    key, key_hash, key_prefix = generate_api_key()

    # Delete old keys, insert new one
    await pool.execute("DELETE FROM api_keys WHERE agent_id = $1", agent_id)
    await pool.execute(
        "INSERT INTO api_keys (agent_id, key_hash, key_prefix) VALUES ($1, $2, $3)",
        agent_id,
        key_hash,
        key_prefix,
    )

    return {
        "api_key": key,
        "message": "Old key has been invalidated. Store this key — it won't be shown again.",
    }
