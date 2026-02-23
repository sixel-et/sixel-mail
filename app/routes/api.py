import base64

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, field_validator

from app.auth import generate_api_key, get_agent_id
from app.config import settings
from app.db import get_pool
from app.ratelimit import POLL_LIMIT, POLL_WINDOW, SEND_LIMIT, SEND_WINDOW, limiter
from app.services.credits import deduct_credit
from app.services.email import build_footer, send_email
from app.services.nonce import build_reply_to, generate_nonce

import time

router = APIRouter(prefix="/v1")

# Heartbeat throttle: only write last_seen_at to DB every N seconds.
# Reduces Supabase writes from 1/poll to 1/interval per agent.
HEARTBEAT_INTERVAL = 600  # 10 minutes
_heartbeat_cache: dict[str, float] = {}

MAX_BODY_LENGTH = 100_000  # 100KB
MAX_ATTACHMENT_TOTAL = 10_000_000  # 10MB decoded
MAX_ATTACHMENT_COUNT = 10


class AttachmentInput(BaseModel):
    filename: str
    content: str  # base64-encoded


class SendRequest(BaseModel):
    subject: str = ""
    body: str
    attachments: list[AttachmentInput] | None = None

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


class AttachmentInfo(BaseModel):
    id: str
    filename: str
    mime_type: str
    size_bytes: int


class MessageResponse(BaseModel):
    id: str
    subject: str | None
    body: str
    received_at: str
    encrypted: bool = False
    attachments: list[AttachmentInfo] = []


class InboxResponse(BaseModel):
    messages: list[MessageResponse]
    credits_remaining: int
    agent_status: str


def _validate_attachments(attachments: list[AttachmentInput]) -> list[tuple[str, str, bytes]]:
    """Validate and decode attachments. Returns [(filename, content_b64, decoded_bytes), ...]."""
    if len(attachments) > MAX_ATTACHMENT_COUNT:
        raise HTTPException(
            status_code=400,
            detail=f"Maximum {MAX_ATTACHMENT_COUNT} attachments per message",
        )

    results = []
    total_size = 0
    for att in attachments:
        if not att.filename.strip():
            raise HTTPException(status_code=400, detail="Attachment filename cannot be empty")
        try:
            decoded = base64.b64decode(att.content)
        except Exception:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid base64 content for attachment '{att.filename}'",
            )
        total_size += len(decoded)
        if total_size > MAX_ATTACHMENT_TOTAL:
            raise HTTPException(
                status_code=400,
                detail=f"Total attachment size exceeds {MAX_ATTACHMENT_TOTAL // 1_000_000}MB limit",
            )
        results.append((att.filename, att.content, decoded))

    return results


async def _store_attachments(pool, message_id: str, attachments: list[tuple[str, str, bytes]]):
    """Store attachments in the database."""
    for filename, content_b64, decoded in attachments:
        # Guess MIME type from extension
        import mimetypes
        mime_type = mimetypes.guess_type(filename)[0] or "application/octet-stream"

        await pool.execute(
            """
            INSERT INTO attachments (message_id, filename, mime_type, size_bytes, content_base64)
            VALUES ($1, $2, $3, $4, $5)
            """,
            message_id,
            filename,
            mime_type,
            len(decoded),
            content_b64,
        )


async def _get_attachments_for_messages(pool, message_ids: list) -> dict[str, list[AttachmentInfo]]:
    """Fetch attachment metadata (not content) for a list of messages."""
    if not message_ids:
        return {}

    rows = await pool.fetch(
        """
        SELECT id, message_id, filename, mime_type, size_bytes
        FROM attachments WHERE message_id = ANY($1::uuid[])
        ORDER BY created_at
        """,
        message_ids,
    )

    result: dict[str, list[AttachmentInfo]] = {}
    for row in rows:
        msg_id = str(row["message_id"])
        if msg_id not in result:
            result[msg_id] = []
        result[msg_id].append(AttachmentInfo(
            id=str(row["id"]),
            filename=row["filename"],
            mime_type=row["mime_type"],
            size_bytes=row["size_bytes"],
        ))
    return result


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
        "SELECT address, allowed_contact, credit_balance, nonce_enabled, admin_approved FROM agents WHERE id = $1",
        agent_id,
    )
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")

    if not agent["admin_approved"]:
        raise HTTPException(status_code=403, detail="Account pending admin approval")

    # Validate attachments before deducting credit
    validated_attachments = []
    resend_attachments = None
    if req.attachments:
        validated_attachments = _validate_attachments(req.attachments)
        resend_attachments = [
            {"filename": fname, "content": content_b64}
            for fname, content_b64, _ in validated_attachments
        ]

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

    # Generate nonce for reply-to validation (only if nonce_enabled)
    if agent["nonce_enabled"]:
        nonce = await generate_nonce(pool, agent_id)
        reply_to = build_reply_to(agent["address"], nonce)
    else:
        reply_to = f"{agent['address']}@{settings.mail_domain}"

    await send_email(
        from_address=from_addr,
        to_address=agent["allowed_contact"],
        subject=f"[{agent['address']}] {req.subject}",
        body=full_body,
        reply_to=reply_to,
        attachments=resend_attachments,
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

    # Store attachments
    if validated_attachments:
        await _store_attachments(pool, row["id"], validated_attachments)

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

    # Fetch agent first — needed for heartbeat_enabled check and response
    agent = await pool.fetchrow(
        "SELECT address, allowed_contact, credit_balance, agent_down_notified, nonce_enabled, heartbeat_enabled FROM agents WHERE id = $1",
        agent_id,
    )

    # Heartbeat + recovery only if monitoring is enabled
    if agent and agent["heartbeat_enabled"]:
        # Throttled heartbeat: only write to DB if stale.
        # Best-effort — never block message delivery if the write fails.
        now = time.monotonic()
        last_write = _heartbeat_cache.get(agent_id, 0)
        if now - last_write >= HEARTBEAT_INTERVAL:
            try:
                await pool.execute(
                    "UPDATE agents SET last_seen_at = now() WHERE id = $1",
                    agent_id,
                )
                _heartbeat_cache[agent_id] = now
            except Exception:
                pass  # Heartbeat is best-effort; inbox delivery matters more

        # Check if agent was marked down, send recovery notification
        if agent["agent_down_notified"]:
            await pool.execute(
                "UPDATE agents SET agent_down_notified = FALSE, last_seen_at = now() WHERE id = $1",
                agent_id,
            )
            _heartbeat_cache[agent_id] = now
            if agent["nonce_enabled"]:
                recovery_nonce = await generate_nonce(pool, agent_id)
                recovery_reply_to = build_reply_to(agent["address"], recovery_nonce)
            else:
                recovery_reply_to = f"{agent['address']}@{settings.mail_domain}"
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

    # Fetch attachment metadata for all messages
    msg_ids = [row["id"] for row in rows]
    attachments_map = await _get_attachments_for_messages(pool, msg_ids)

    messages = [
        MessageResponse(
            id=str(row["id"]),
            subject=row["subject"],
            body=row["body"],
            received_at=row["created_at"].isoformat(),
            encrypted=row.get("encrypted", False),
            attachments=attachments_map.get(str(row["id"]), []),
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

    # Fetch attachments
    attachments_map = await _get_attachments_for_messages(pool, [row["id"]])

    return MessageResponse(
        id=str(row["id"]),
        subject=row["subject"],
        body=row["body"],
        received_at=row["created_at"].isoformat(),
        encrypted=row.get("encrypted", False),
        attachments=attachments_map.get(str(row["id"]), []),
    )


# GET /v1/inbox/:message_id/attachments/:attachment_id
@router.get("/inbox/{message_id}/attachments/{attachment_id}")
async def download_attachment(
    message_id: str,
    attachment_id: str,
    agent_id: str = Depends(get_agent_id),
):
    pool = await get_pool()

    # Verify message belongs to agent
    msg = await pool.fetchrow(
        "SELECT id FROM messages WHERE id = $1 AND agent_id = $2",
        message_id,
        agent_id,
    )
    if not msg:
        raise HTTPException(status_code=404, detail="Message not found")

    # Fetch attachment
    att = await pool.fetchrow(
        "SELECT filename, mime_type, content_base64 FROM attachments WHERE id = $1 AND message_id = $2",
        attachment_id,
        message_id,
    )
    if not att:
        raise HTTPException(status_code=404, detail="Attachment not found")

    content = base64.b64decode(att["content_base64"])
    return Response(
        content=content,
        media_type=att["mime_type"],
        headers={"Content-Disposition": f'attachment; filename="{att["filename"]}"'},
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
