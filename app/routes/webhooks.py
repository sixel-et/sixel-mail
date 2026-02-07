import base64
import email
import email.policy
import json
import logging
import re

import httpx
import stripe
from cryptography.x509 import load_pem_x509_certificate
from cryptography.hazmat.primitives.asymmetric.padding import PKCS1v15
from cryptography.hazmat.primitives.hashes import SHA1
from fastapi import APIRouter, HTTPException, Request

from app.config import settings
from app.db import get_pool
from app.services.credits import add_credits, deduct_credit

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/webhooks")

# Cache for SNS signing certificates
_cert_cache: dict[str, object] = {}

SNS_CERT_URL_PATTERN = re.compile(
    r"^https://sns\.[a-z0-9-]+\.amazonaws\.com/"
)


async def _verify_sns_signature(message: dict) -> bool:
    """Verify an SNS message signature using the signing certificate."""
    cert_url = message.get("SigningCertURL", "")

    # Validate cert URL is from AWS
    if not SNS_CERT_URL_PATTERN.match(cert_url):
        logger.warning("SNS cert URL not from AWS: %s", cert_url)
        return False

    # Fetch and cache the certificate
    if cert_url not in _cert_cache:
        async with httpx.AsyncClient() as client:
            resp = await client.get(cert_url)
            if resp.status_code != 200:
                logger.warning("Failed to fetch SNS cert from %s", cert_url)
                return False
            _cert_cache[cert_url] = load_pem_x509_certificate(resp.content)

    cert = _cert_cache[cert_url]

    # Build the string to sign based on message type
    msg_type = message.get("Type", "")
    if msg_type == "Notification":
        fields = ["Message", "MessageId"]
        if "Subject" in message:
            fields.append("Subject")
        fields.extend(["Timestamp", "TopicArn", "Type"])
    elif msg_type in ("SubscriptionConfirmation", "UnsubscribeConfirmation"):
        fields = ["Message", "MessageId", "SubscribeURL", "Timestamp", "Token", "TopicArn", "Type"]
    else:
        return False

    string_to_sign = ""
    for field in fields:
        string_to_sign += f"{field}\n{message[field]}\n"

    signature = base64.b64decode(message["Signature"])

    try:
        cert.public_key().verify(signature, string_to_sign.encode(), PKCS1v15(), SHA1())
        return True
    except Exception:
        logger.warning("SNS signature verification failed")
        return False


def _extract_text_body(raw_email: str) -> str:
    """Extract the text/plain body from a raw email string."""
    msg = email.message_from_string(raw_email, policy=email.policy.default)

    # Walk MIME parts, prefer text/plain
    if msg.is_multipart():
        for part in msg.walk():
            if part.get_content_type() == "text/plain":
                payload = part.get_content()
                if isinstance(payload, str):
                    return payload
        # Fallback: try text/html
        for part in msg.walk():
            if part.get_content_type() == "text/html":
                payload = part.get_content()
                if isinstance(payload, str):
                    return payload
    else:
        payload = msg.get_content()
        if isinstance(payload, str):
            return payload

    return "(no body)"


async def _store_inbound(pool, agent_address: str, from_addr: str, subject: str, body: str):
    """Validate and store an inbound email message."""
    agent = await pool.fetchrow(
        "SELECT id, allowed_contact, credit_balance FROM agents WHERE address = $1",
        agent_address,
    )
    if not agent:
        logger.info("Inbound for unknown agent: %s", agent_address)
        return {"status": "dropped", "reason": "unknown_agent"}

    # Validate sender is allowed contact
    if from_addr.lower() != agent["allowed_contact"].lower():
        logger.info("Dropped email from %s (not allowed contact for %s)", from_addr, agent_address)
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
        body,
    )

    return {"status": "received"}


# POST /webhooks/ses — receive inbound email via SNS
@router.post("/ses")
async def ses_inbound(request: Request):
    """Handle inbound email from SES via SNS with signature verification."""
    body = await request.json()

    # Verify SNS signature
    if not await _verify_sns_signature(body):
        raise HTTPException(status_code=403, detail="Invalid SNS signature")

    msg_type = body.get("Type")

    # Handle SNS subscription confirmation
    if msg_type == "SubscriptionConfirmation":
        subscribe_url = body.get("SubscribeURL")
        if subscribe_url:
            async with httpx.AsyncClient() as client:
                await client.get(subscribe_url)
            logger.info("Confirmed SNS subscription for topic %s", body.get("TopicArn"))
            return {"status": "subscription_confirmed"}
        raise HTTPException(status_code=400, detail="Missing SubscribeURL")

    # Handle notification
    if msg_type != "Notification":
        return {"status": "ignored"}

    # The SNS message may be base64 (raw email) or JSON (SES notification)
    raw_message = body.get("Message", "")

    # Try to parse as JSON first (SES notification format)
    try:
        ses_message = json.loads(raw_message)
        # SES JSON notification — extract metadata and raw content
        mail_obj = ses_message.get("mail", {})
        receipt = ses_message.get("receipt", {})
        recipients = receipt.get("recipients", mail_obj.get("destination", []))
        from_addr = mail_obj.get("source", "")

        subject = ""
        for header in mail_obj.get("headers", []):
            if header["name"].lower() == "subject":
                subject = header["value"]
                break

        # If content field has the raw email, parse it
        raw_email = ses_message.get("content", "")
        if raw_email:
            text_body = _extract_text_body(raw_email)
        else:
            text_body = "(no body)"

    except (json.JSONDecodeError, ValueError):
        # Base64-encoded raw email (when SNS encoding is Base64)
        try:
            raw_email = base64.b64decode(raw_message).decode("utf-8", errors="replace")
        except Exception:
            raise HTTPException(status_code=400, detail="Could not decode message")

        msg = email.message_from_string(raw_email, policy=email.policy.default)
        from_addr = msg.get("From", "")
        subject = msg.get("Subject", "")
        recipients = [addr.strip() for addr in (msg.get("To", "")).split(",")]
        text_body = _extract_text_body(raw_email)

        # Extract just the email address from "Name <addr>" format
        if "<" in from_addr and ">" in from_addr:
            from_addr = from_addr.split("<")[1].split(">")[0]

    pool = await get_pool()

    # Process for each recipient (usually just one)
    for recipient in recipients:
        # Clean up recipient if in "Name <addr>" format
        if "<" in recipient and ">" in recipient:
            recipient = recipient.split("<")[1].split(">")[0]
        local_part = recipient.split("@")[0].lower()
        await _store_inbound(pool, local_part, from_addr, subject, text_body)

    return {"status": "processed"}


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
