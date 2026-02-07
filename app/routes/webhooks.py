import logging

import stripe
from fastapi import APIRouter, HTTPException, Request

from app.config import settings
from app.db import get_pool
from app.services.credits import add_credits, deduct_credit

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/webhooks")


# POST /webhooks/ses — receive inbound email via SNS
@router.post("/ses")
async def ses_inbound(request: Request):
    """Handle inbound email from SES via SNS.

    For local testing, accepts a simplified JSON payload:
    {
        "agent_address": "my-agent",
        "from": "human@example.com",
        "subject": "Re: something",
        "body": "reply text"
    }
    """
    pool = await get_pool()
    body = await request.json()

    # TODO: Verify SNS signature in production

    # Support simplified test payload
    if "agent_address" in body:
        return await _handle_test_inbound(pool, body)

    # Real SNS notification handling
    # TODO: Parse actual SES/SNS notification format
    raise HTTPException(status_code=400, detail="Unsupported payload format")


async def _handle_test_inbound(pool, body: dict):
    """Handle simplified test inbound payload."""
    agent_address = body["agent_address"]
    from_addr = body["from"]
    subject = body.get("subject", "")
    msg_body = body["body"]

    agent = await pool.fetchrow(
        "SELECT id, allowed_contact, credit_balance FROM agents WHERE address = $1",
        agent_address,
    )
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")

    # Validate sender is allowed contact
    if from_addr.lower() != agent["allowed_contact"].lower():
        logger.info("Dropped email from %s (not allowed contact)", from_addr)
        return {"status": "dropped", "reason": "sender_not_allowed"}

    # Deduct credit
    new_balance = await deduct_credit(pool, str(agent["id"]), "message_received")
    if new_balance is None:
        logger.info("Dropped inbound for %s (no credits)", agent_address)
        return {"status": "dropped", "reason": "insufficient_credits"}

    # Store message
    await pool.execute(
        """
        INSERT INTO messages (agent_id, direction, subject, body, is_read)
        VALUES ($1, 'inbound', $2, $3, FALSE)
        """,
        agent["id"],
        subject,
        msg_body,
    )

    return {"status": "received"}


# POST /webhooks/stripe — handle Stripe Checkout completion
@router.post("/stripe")
async def stripe_webhook(request: Request):
    payload = await request.body()
    sig_header = request.headers.get("stripe-signature", "")

    if not settings.stripe_webhook_secret:
        # Dev mode: parse without signature verification
        event = stripe.Event.construct_from(
            await request.json(), stripe.api_key
        )
    else:
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
