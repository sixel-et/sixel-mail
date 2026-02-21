import base64
import hashlib
import hmac
import logging
import mimetypes
import time

import stripe
from fastapi import APIRouter, HTTPException, Request

from app.config import settings
from app.db import get_pool
from app.services.credits import add_credits, deduct_credit
from app.services.email import build_footer, send_email
from app.services.nonce import build_reply_to, generate_nonce, validate_nonce

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/webhooks")


# --- Knock rate limiting (in-memory, per-agent) ---
# Tracks recent knock timestamps per agent. Simple sliding window.
_knock_timestamps: dict[str, list[float]] = {}
KNOCK_RATE_LIMIT = 10  # max knocks per window
KNOCK_RATE_WINDOW = 60  # seconds


MAX_ATTACHMENT_TOTAL = 10_000_000  # 10MB decoded


async def _store_inbound_attachments(pool, message_id, attachments: list[dict]):
    """Store attachments from the Worker payload into the attachments table."""
    total_size = 0
    for att in attachments:
        content_b64 = att.get("contentBase64", "")
        filename = att.get("filename", "unnamed")
        mime_type = att.get("mimeType", "application/octet-stream")

        # Estimate decoded size
        decoded_size = len(content_b64) * 3 // 4
        total_size += decoded_size
        if total_size > MAX_ATTACHMENT_TOTAL:
            logger.warning("Inbound attachments exceed size limit, truncating")
            break

        await pool.execute(
            """
            INSERT INTO attachments (message_id, filename, mime_type, size_bytes, content_base64)
            VALUES ($1, $2, $3, $4, $5)
            """,
            message_id,
            filename,
            mime_type,
            decoded_size,
            content_b64,
        )


def _check_knock_rate(agent_id: str) -> bool:
    """Return True if knock is allowed, False if rate-limited."""
    now = time.time()
    timestamps = _knock_timestamps.get(agent_id, [])
    # Prune old entries
    timestamps = [t for t in timestamps if now - t < KNOCK_RATE_WINDOW]
    if len(timestamps) >= KNOCK_RATE_LIMIT:
        _knock_timestamps[agent_id] = timestamps
        return False
    timestamps.append(now)
    _knock_timestamps[agent_id] = timestamps
    return True


# POST /webhooks/inbound — receive inbound email from Cloudflare Email Worker
@router.post("/inbound")
async def cf_inbound(request: Request):
    """Handle inbound email forwarded from Cloudflare Email Worker.

    The Worker has already:
    - Verified DMARC (Cloudflare Email Routing enforces at SMTP)
    - Checked allowed contact (Worker rejects non-allowed senders)
    - Extracted nonce from + addressing (if present)

    Flow:
    - If nonce present and valid: authenticated message → store, deduct credit
    - If no nonce from allowed contact: knock → reply with fresh nonce, no credit
    - If no nonce from unknown sender: silent drop
    """
    # Verify the request is from our Worker
    auth_header = request.headers.get("X-Worker-Auth", "")
    if not settings.cf_worker_secret or not auth_header:
        raise HTTPException(status_code=403, detail="Missing authentication")
    if not hmac.compare_digest(auth_header, settings.cf_worker_secret):
        raise HTTPException(status_code=403, detail="Invalid authentication")

    body = await request.json()
    agent_address = body.get("agent_address", "").lower().strip()
    from_addr = body.get("from", "").strip()
    subject = body.get("subject", "")
    message_body = body.get("body", "")
    encrypted = body.get("encrypted", False)
    nonce_str = body.get("nonce")  # Extracted by Worker from + addressing
    attachments = body.get("attachments", [])  # [{filename, mimeType, contentBase64}]

    if not agent_address or not from_addr:
        raise HTTPException(status_code=400, detail="Missing required fields")

    pool = await get_pool()

    agent = await pool.fetchrow(
        "SELECT id, address, allowed_contact, credit_balance, channel_active, nonce_enabled "
        "FROM agents WHERE address = $1",
        agent_address,
    )
    if not agent:
        logger.info("Inbound for unknown agent: %s", agent_address)
        return {"status": "dropped", "reason": "unknown_agent"}

    agent_id = str(agent["id"])

    # Check channel kill switch
    if not agent["channel_active"]:
        logger.info("Inbound dropped for %s (channel inactive)", agent_address)
        return {"status": "dropped", "reason": "channel_inactive"}

    # Double-check allowed contact (defense in depth — Worker already checked)
    if from_addr.lower() != agent["allowed_contact"].lower():
        logger.warning(
            "CF Worker forwarded email from %s but allowed contact is %s for %s",
            from_addr, agent["allowed_contact"], agent_address,
        )
        return {"status": "dropped", "reason": "sender_not_allowed"}

    # --- ALL-STOP CHECK (nonce starting with "allstop-") ---
    if nonce_str and nonce_str.startswith("allstop-"):
        allstop_key = nonce_str[len("allstop-"):]
        if agent.get("allstop_key_hash"):
            key_hash = hashlib.sha256(allstop_key.encode()).hexdigest()
            if hmac.compare_digest(key_hash, agent["allstop_key_hash"]):
                await pool.execute(
                    "UPDATE agents SET channel_active = FALSE WHERE id = $1",
                    agent["id"],
                )
                logger.warning("ALL-STOP triggered via email for agent %s", agent_address)
                return {"status": "channel_deactivated"}
        # Invalid allstop key — treat as invalid nonce, don't reveal allstop exists
        logger.info("Invalid allstop attempt for %s", agent_address)
        return {"status": "dropped", "reason": "invalid_nonce"}

    # --- NONCE DISABLED: accept directly from allowed contact ---
    nonce_enabled = agent.get("nonce_enabled", False)
    if not nonce_enabled:
        # Accept email directly — no nonce check, no knock
        new_balance = await deduct_credit(pool, agent_id, "message_received")
        if new_balance is None:
            logger.info("Dropped inbound for %s (no credits)", agent_address)
            return {"status": "dropped", "reason": "insufficient_credits"}

        row = await pool.fetchrow(
            """
            INSERT INTO messages (agent_id, direction, subject, body, is_read, encrypted)
            VALUES ($1, 'inbound', $2, $3, FALSE, $4)
            RETURNING id
            """,
            agent["id"],
            subject,
            message_body,
            encrypted,
        )
        if attachments:
            await _store_inbound_attachments(pool, row["id"], attachments)
        logger.info("Message received for %s (nonce disabled, direct accept, %d attachments)", agent_address, len(attachments))
        return {"status": "received"}

    # --- NONCE VALIDATION PATH (nonce_enabled=true) ---
    if nonce_str:
        validated_agent_id = await validate_nonce(pool, nonce_str)
        if validated_agent_id is None:
            logger.info("Invalid/expired nonce from %s for %s", from_addr, agent_address)
            return {"status": "dropped", "reason": "invalid_nonce"}

        if validated_agent_id != agent_id:
            logger.warning("Nonce agent mismatch: nonce=%s, recipient=%s", validated_agent_id, agent_id)
            return {"status": "dropped", "reason": "nonce_agent_mismatch"}

        # Valid nonce — this is an authenticated message. Deduct credit.
        new_balance = await deduct_credit(pool, agent_id, "message_received")
        if new_balance is None:
            logger.info("Dropped inbound for %s (no credits)", agent_address)
            return {"status": "dropped", "reason": "insufficient_credits"}

        # Store message
        row = await pool.fetchrow(
            """
            INSERT INTO messages (agent_id, direction, subject, body, is_read, encrypted)
            VALUES ($1, 'inbound', $2, $3, FALSE, $4)
            RETURNING id
            """,
            agent["id"],
            subject,
            message_body,
            encrypted,
        )
        if attachments:
            await _store_inbound_attachments(pool, row["id"], attachments)
        logger.info("Authenticated message received for %s (nonce valid, %d attachments)", agent_address, len(attachments))
        return {"status": "received"}

    # --- KNOCK PATH (no nonce, from allowed contact, nonce_enabled=true) ---
    if not _check_knock_rate(agent_id):
        logger.warning("Knock rate limited for %s", agent_address)
        return {"status": "dropped", "reason": "knock_rate_limited"}

    # Generate fresh nonce and reply — no credit deduction
    knock_nonce = await generate_nonce(pool, agent_id)
    knock_reply_to = build_reply_to(agent["address"], knock_nonce)

    from_email = f"{agent['address']}@{settings.mail_domain}"
    footer = build_footer(agent["address"], agent["credit_balance"])

    await send_email(
        from_address=from_email,
        to_address=agent["allowed_contact"],
        subject=f"[{agent['address']}] Re: {subject}",
        body=(
            "Knock received. Reply to this email to send your message.\n"
            "(This is an automated reply — your original message was not processed.)"
            f"{footer}"
        ),
        reply_to=knock_reply_to,
    )
    logger.info("Knock reply sent for %s (nonce issued)", agent_address)
    return {"status": "knock_replied"}


# POST /webhooks/stripe — handle Stripe Checkout completion
@router.post("/stripe")
async def stripe_webhook(request: Request):
    payload = await request.body()
    sig_header = request.headers.get("stripe-signature", "")

    if not settings.stripe_webhook_secret:
        logger.warning("Stripe webhook received but no webhook secret configured — rejecting")
        raise HTTPException(status_code=503, detail="Stripe webhooks not configured")

    try:
        event = stripe.Webhook.construct_event(
            payload, sig_header, settings.stripe_webhook_secret
        )
    except stripe.SignatureVerificationError:
        raise HTTPException(status_code=400, detail="Invalid signature")

    if event["type"] != "checkout.session.completed":
        return {"status": "ignored"}

    session = event["data"]["object"]
    metadata = session.get("metadata", {})
    agent_id = metadata.get("agent_id")
    credit_amount = int(metadata.get("credit_amount", 0))
    session_id = session.get("id", "")

    if not agent_id or not credit_amount:
        logger.warning("Stripe webhook missing metadata: %s", metadata)
        return {"status": "error", "reason": "missing_metadata"}

    pool = await get_pool()

    # Deduplicate: check if this session_id already credited
    existing = await pool.fetchval(
        "SELECT COUNT(*) FROM credit_transactions WHERE stripe_session_id = $1",
        session_id,
    )
    if existing > 0:
        logger.info("Duplicate Stripe webhook for session %s", session_id)
        return {"status": "duplicate"}

    new_balance = await add_credits(
        pool, agent_id, credit_amount, "stripe_topup", stripe_session_id=session_id
    )
    logger.info(
        "Added %d credits to agent %s (session %s), new balance: %d",
        credit_amount, agent_id, session_id, new_balance,
    )

    return {"status": "credited", "credits_added": credit_amount}
