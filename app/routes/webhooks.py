import json
import logging

from fastapi import APIRouter, HTTPException, Request

from app.db import get_pool
from app.services.credits import deduct_credit

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
