import hmac
import logging

import stripe
from fastapi import APIRouter, HTTPException, Request

from app.config import settings
from app.db import get_pool
from app.services.credits import add_credits, deduct_credit

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/webhooks")


# POST /webhooks/inbound — receive inbound email from Cloudflare Email Worker
@router.post("/inbound")
async def cf_inbound(request: Request):
    """Handle inbound email forwarded from Cloudflare Email Worker.

    The Worker has already:
    - Verified DMARC (Cloudflare Email Routing enforces at SMTP)
    - Checked allowed contact (Worker rejects non-allowed senders)
    - Optionally encrypted the body with TOTP (if agent has TOTP enabled)
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

    if not agent_address or not from_addr:
        raise HTTPException(status_code=400, detail="Missing required fields")

    pool = await get_pool()

    agent = await pool.fetchrow(
        "SELECT id, allowed_contact, credit_balance FROM agents WHERE address = $1",
        agent_address,
    )
    if not agent:
        logger.info("Inbound for unknown agent: %s", agent_address)
        return {"status": "dropped", "reason": "unknown_agent"}

    # Double-check allowed contact (defense in depth — Worker already checked)
    if from_addr.lower() != agent["allowed_contact"].lower():
        logger.warning(
            "CF Worker forwarded email from %s but allowed contact is %s for %s",
            from_addr, agent["allowed_contact"], agent_address,
        )
        return {"status": "dropped", "reason": "sender_not_allowed"}

    # Deduct credit
    new_balance = await deduct_credit(pool, str(agent["id"]), "message_received")
    if new_balance is None:
        logger.info("Dropped inbound for %s (no credits)", agent_address)
        return {"status": "dropped", "reason": "insufficient_credits"}

    # Store message (body may be ciphertext or plaintext — we don't care)
    await pool.execute(
        """
        INSERT INTO messages (agent_id, direction, subject, body, is_read, encrypted)
        VALUES ($1, 'inbound', $2, $3, FALSE, $4)
        """,
        agent["id"],
        subject,
        message_body,
        encrypted,
    )

    return {"status": "received"}


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
