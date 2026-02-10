import hashlib
import hmac
import logging

import httpx
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from app.auth import generate_api_key
from app.config import settings
from app.db import get_pool

logger = logging.getLogger(__name__)
router = APIRouter()


async def _sync_agent_to_kv(address: str, allowed_contact: str, has_totp: bool):
    """Push agent→contact mapping to Cloudflare KV for the Email Worker.

    The Worker uses this to check allowed contacts at the edge.
    If Cloudflare credentials aren't configured, log and skip (dev mode).
    """
    if not settings.cf_account_id or not settings.cf_kv_namespace_id or not settings.cf_api_token:
        logger.info("Cloudflare KV not configured — skipping agent sync for %s", address)
        return

    import json

    value = json.dumps({
        "allowed_contact": allowed_contact.lower(),
        "has_totp": has_totp,
    })

    try:
        async with httpx.AsyncClient() as client:
            resp = await client.put(
                f"https://api.cloudflare.com/client/v4/accounts/{settings.cf_account_id}"
                f"/storage/kv/namespaces/{settings.cf_kv_namespace_id}/values/{address}",
                headers={
                    "Authorization": f"Bearer {settings.cf_api_token}",
                    "Content-Type": "text/plain",
                },
                content=value,
            )
            if resp.status_code == 200:
                logger.info("Synced agent %s to Cloudflare KV", address)
            else:
                logger.warning("Failed to sync agent %s to KV: %s %s", address, resp.status_code, resp.text)
    except Exception as e:
        logger.warning("Error syncing agent %s to KV: %s", address, e)


def make_session_token(user_id: str) -> str:
    sig = hmac.new(
        settings.signing_secret.encode(), user_id.encode(), hashlib.sha256
    ).hexdigest()[:16]
    return f"{user_id}:{sig}"


def verify_session_token(token: str) -> str | None:
    if not token or ":" not in token:
        return None
    user_id, sig = token.rsplit(":", 1)
    expected = hmac.new(
        settings.signing_secret.encode(), user_id.encode(), hashlib.sha256
    ).hexdigest()[:16]
    if hmac.compare_digest(sig, expected):
        return user_id
    return None


def get_user_id(request: Request) -> str | None:
    token = request.cookies.get("session")
    if token:
        return verify_session_token(token)
    return None


# Step 1: Redirect to GitHub OAuth
@router.get("/auth/github")
async def github_login():
    if not settings.github_client_id:
        raise HTTPException(status_code=503, detail="GitHub OAuth not configured")
    return RedirectResponse(
        f"https://github.com/login/oauth/authorize"
        f"?client_id={settings.github_client_id}"
        f"&scope=read:user,user:email"
    )


# Step 2: GitHub callback
@router.get("/auth/github/callback")
async def github_callback(code: str):
    if not settings.github_client_id:
        raise HTTPException(status_code=503, detail="GitHub OAuth not configured")

    # Exchange code for token
    async with httpx.AsyncClient() as client:
        token_resp = await client.post(
            "https://github.com/login/oauth/access_token",
            json={
                "client_id": settings.github_client_id,
                "client_secret": settings.github_client_secret,
                "code": code,
            },
            headers={"Accept": "application/json"},
        )
        token_data = token_resp.json()

    access_token = token_data.get("access_token")
    if not access_token:
        raise HTTPException(status_code=400, detail="GitHub auth failed")

    # Get user info
    async with httpx.AsyncClient() as client:
        user_resp = await client.get(
            "https://api.github.com/user",
            headers={"Authorization": f"Bearer {access_token}"},
        )
        user_data = user_resp.json()

        # Get primary email
        email_resp = await client.get(
            "https://api.github.com/user/emails",
            headers={"Authorization": f"Bearer {access_token}"},
        )
        emails = email_resp.json()

    github_id = user_data["id"]
    username = user_data["login"]
    primary_email = next(
        (e["email"] for e in emails if e["primary"]),
        emails[0]["email"] if emails else f"{username}@github",
    )

    # Create or update user
    pool = await get_pool()
    user = await pool.fetchrow(
        """
        INSERT INTO users (github_id, github_username, email)
        VALUES ($1, $2, $3)
        ON CONFLICT (github_id) DO UPDATE SET github_username = $2, email = $3
        RETURNING id
        """,
        github_id,
        username,
        primary_email,
    )

    user_id = str(user["id"])

    # Check if user already has agents → dashboard, otherwise → setup
    agent_count = await pool.fetchval(
        "SELECT COUNT(*) FROM agents WHERE user_id = $1", user_id
    )
    dest = "/account" if agent_count > 0 else "/setup"

    response = RedirectResponse(dest, status_code=303)
    response.set_cookie(
        "session", make_session_token(user_id),
        httponly=True, secure=True, samesite="lax", max_age=86400 * 30,
    )
    return response


# Step 3: Setup page — pick agent address, set allowed contact, optional TOTP
@router.get("/setup", response_class=HTMLResponse)
async def setup_page(request: Request):
    user_id = get_user_id(request)
    if not user_id:
        return RedirectResponse("/auth/github")
    return f"""<!DOCTYPE html>
<html><head><title>Sixel-Mail Setup</title>
<style>
    body {{ font-family: monospace; max-width: 600px; margin: 40px auto; padding: 0 20px; }}
    input, button {{ font-family: monospace; font-size: 16px; padding: 8px; }}
    input {{ width: 100%; box-sizing: border-box; margin: 8px 0; }}
    button {{ cursor: pointer; background: #000; color: #fff; border: none; padding: 10px 20px; }}
    .suffix {{ color: #666; }}
    .totp-section {{ background: #f8f8f8; border: 1px solid #ddd; padding: 16px; margin: 16px 0; display: none; }}
    .totp-section.active {{ display: block; }}
    #qr-code {{ margin: 12px 0; }}
    .secret-display {{ background: #fff; border: 1px solid #ccc; padding: 8px; font-size: 18px; letter-spacing: 2px; word-break: break-all; }}
    .toggle-label {{ cursor: pointer; user-select: none; }}
    .note {{ color: #666; font-size: 13px; margin: 4px 0; }}
</style>
<script src="https://cdn.jsdelivr.net/npm/qrcode-generator@1.4.4/qrcode.min.js"></script>
</head>
<body>
<h1>sixel.email</h1>
<h2>Set up your agent</h2>
<form method="POST" action="/setup" id="setup-form">
    <label>Agent address:</label><br>
    <input type="text" name="address" id="address" placeholder="my-agent" pattern="[a-z0-9\\-]{{3,30}}" required>
    <span class="suffix">@sixel.email</span><br><br>
    <label>Your email (the one allowed contact):</label><br>
    <input type="email" name="allowed_contact" required><br><br>

    <label class="toggle-label">
        <input type="checkbox" id="totp-toggle" name="enable_totp" value="1">
        Enable TOTP encryption (recommended)
    </label>
    <p class="note">Encrypts your messages so even our server can't read them. Requires any authenticator app.</p>

    <div class="totp-section" id="totp-section">
        <h3>TOTP Setup</h3>
        <p>Scan this QR code with your authenticator app (Google Authenticator, Authy, 1Password, etc.):</p>
        <div id="qr-code"></div>
        <p>Or copy this secret manually:</p>
        <div class="secret-display" id="totp-secret-display"></div>
        <button type="button" onclick="copySecret()" style="margin-top: 8px; font-size: 13px; padding: 6px 12px;">Copy secret</button>
        <p class="note">This secret is generated in your browser. It never leaves this page. Save it — you'll need to give it to your agent.</p>
        <input type="hidden" name="has_totp" id="has-totp" value="0">
    </div>
    <br>
    <button type="submit">Create agent</button>
</form>

<script>
// Generate a random TOTP secret (base32, 20 bytes = 32 chars)
function generateSecret() {{
    const bytes = new Uint8Array(20);
    crypto.getRandomValues(bytes);
    const base32chars = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ234567';
    let secret = '';
    for (let i = 0; i < bytes.length; i++) {{
        // Simple base32 encoding
        secret += base32chars[bytes[i] % 32];
    }}
    // Pad to 32 chars
    while (secret.length < 32) {{
        const extra = new Uint8Array(1);
        crypto.getRandomValues(extra);
        secret += base32chars[extra[0] % 32];
    }}
    return secret;
}}

let totpSecret = null;

document.getElementById('totp-toggle').addEventListener('change', function() {{
    const section = document.getElementById('totp-section');
    const hasTotp = document.getElementById('has-totp');
    if (this.checked) {{
        section.classList.add('active');
        if (!totpSecret) {{
            totpSecret = generateSecret();
        }}
        hasTotp.value = '1';
        updateQR();
    }} else {{
        section.classList.remove('active');
        hasTotp.value = '0';
    }}
}});

document.getElementById('address').addEventListener('input', function() {{
    if (totpSecret && document.getElementById('totp-toggle').checked) {{
        updateQR();
    }}
}});

function updateQR() {{
    const address = document.getElementById('address').value || 'my-agent';
    const otpUrl = 'otpauth://totp/sixel.email:' + encodeURIComponent(address) +
                   '?secret=' + totpSecret + '&issuer=sixel.email';

    document.getElementById('totp-secret-display').textContent = totpSecret;

    // Generate QR code
    const qrDiv = document.getElementById('qr-code');
    qrDiv.innerHTML = '';
    if (typeof qrcode !== 'undefined') {{
        const qr = qrcode(0, 'M');
        qr.addData(otpUrl);
        qr.make();
        qrDiv.innerHTML = qr.createSvgTag(4);
    }}
}}

function copySecret() {{
    if (totpSecret) {{
        navigator.clipboard.writeText(totpSecret).then(function() {{
            alert('Secret copied to clipboard');
        }});
    }}
}}
</script>
</body></html>"""


# Step 4: Create agent
@router.post("/setup")
async def create_agent(request: Request):
    user_id = get_user_id(request)
    if not user_id:
        raise HTTPException(status_code=401, detail="Not logged in")
    form = await request.form()
    address = form["address"].lower().strip()
    allowed_contact = form["allowed_contact"].strip()
    has_totp = form.get("has_totp", "0") == "1"

    # Validate address format
    import re

    if not re.match(r"^[a-z0-9\-]{3,30}$", address):
        raise HTTPException(status_code=400, detail="Invalid address format")

    pool = await get_pool()

    # Check agent limit (10 per user)
    count = await pool.fetchval(
        "SELECT COUNT(*) FROM agents WHERE user_id = $1", user_id
    )
    if count >= 10:
        raise HTTPException(status_code=400, detail="Maximum 10 agents per user")

    # Create agent
    try:
        agent = await pool.fetchrow(
            """
            INSERT INTO agents (user_id, address, allowed_contact, credit_balance, has_totp)
            VALUES ($1, $2, $3, 0, $4)
            RETURNING id
            """,
            user_id,
            address,
            allowed_contact,
            has_totp,
        )
    except Exception:
        raise HTTPException(status_code=400, detail="Address already taken")

    agent_id = agent["id"]

    # Sync agent→contact mapping to Cloudflare KV (for Email Worker)
    await _sync_agent_to_kv(address, allowed_contact, has_totp)

    # Generate API key
    key, key_hash, key_prefix = generate_api_key()
    await pool.execute(
        "INSERT INTO api_keys (agent_id, key_hash, key_prefix) VALUES ($1, $2, $3)",
        agent_id,
        key_hash,
        key_prefix,
    )

    # Build config snippet
    totp_note = ""
    if has_totp:
        totp_note = (
            "\\n\\nTOTP encryption is enabled for this agent.\\n"
            "IMPORTANT: Use the reference client to read messages. Never call /v1/inbox directly.\\n"
            "The reference client decrypts messages using your TOTP secret and only surfaces verified messages.\\n"
            "Messages that fail decryption are discarded and an alert is sent to your contact."
        )

    config_snippet = (
        f"You have an email address for contacting me when you're stuck.\\n"
        f"API: {settings.api_base_url}/v1\\n"
        f"Token: {key}\\n"
        f"Use POST /v1/send to email me. Use GET /v1/inbox to check for my reply.\\n"
        f"Poll /v1/inbox every 60 seconds while waiting."
        f"{totp_note}"
    )

    totp_html = ""
    if has_totp:
        totp_html = """
<div style="background: #fff3cd; border: 1px solid #ffc107; padding: 16px; margin: 16px 0;">
    <strong>TOTP Encryption Enabled</strong><br>
    <p>Your agent's messages will be encrypted. To send an encrypted email to your agent,
    paste the current 6-digit code from your authenticator app at the top or bottom of your message.</p>
    <p>Give the TOTP secret from the setup page to your agent (in its config file).
    The agent's reference client will use it to decrypt messages.</p>
</div>"""

    return HTMLResponse(f"""<!DOCTYPE html>
<html><head><title>Sixel-Mail - Agent Created</title>
<style>
    body {{ font-family: monospace; max-width: 600px; margin: 40px auto; padding: 0 20px; }}
    button {{ font-family: monospace; font-size: 16px; cursor: pointer; background: #000; color: #fff; border: none; padding: 10px 20px; margin: 8px 4px; }}
    code, pre {{ background: #f0f0f0; padding: 2px 6px; }}
    pre {{ white-space: pre-wrap; padding: 12px; }}
</style></head>
<body>
<h1>sixel.email</h1>
<h2>{address}@sixel.email</h2>
{totp_html}
<div style="background: #f0f0f0; padding: 16px; margin: 16px 0;">
    <strong>Your API key (shown once, save it now):</strong><br>
    <code>{key}</code><br><br>
    <strong>Paste this into your agent config:</strong><br>
    <pre>{config_snippet}</pre>
</div>
<a href="/topup?agent_id={agent_id}"><button>Add credit</button></a>
<a href="/account"><button>Go to dashboard</button></a>
</body></html>""")


# Step 5: Top-up page (credits only, no key display)
@router.get("/topup", response_class=HTMLResponse)
async def topup_page(request: Request, agent_id: str):
    user_id = get_user_id(request)
    if not user_id:
        return RedirectResponse("/auth/github")
    pool = await get_pool()
    agent = await pool.fetchrow(
        "SELECT address, credit_balance, user_id FROM agents WHERE id = $1", agent_id
    )
    if not agent or str(agent["user_id"]) != user_id:
        raise HTTPException(status_code=404, detail="Agent not found")

    stripe_button = ""
    if settings.stripe_secret_key:
        stripe_button = f"""
        <a href="/create-checkout?agent_id={agent_id}&amount=5">
            <button>Add $5 credit (500 messages)</button>
        </a>
        <a href="/create-checkout?agent_id={agent_id}&amount=10">
            <button>Add $10 credit (1,000 messages)</button>
        </a>"""
    else:
        stripe_button = "<p><em>Stripe not configured. Credits can be added manually for testing.</em></p>"

    return f"""<!DOCTYPE html>
<html><head><title>Sixel-Mail - Top Up</title>
<style>
    body {{ font-family: monospace; max-width: 600px; margin: 40px auto; padding: 0 20px; }}
    button {{ font-family: monospace; font-size: 16px; cursor: pointer; background: #000; color: #fff; border: none; padding: 10px 20px; margin: 8px 4px; }}
    code, pre {{ background: #f0f0f0; padding: 2px 6px; }}
    pre {{ white-space: pre-wrap; padding: 12px; }}
</style></head>
<body>
<h1>sixel.email</h1>
<h2>{agent['address']}@sixel.email</h2>
<p>Credits: {agent['credit_balance']} messages</p>
<h3>Add credit</h3>
{stripe_button}
<br><a href="/account"><button>Back to dashboard</button></a>
</body></html>"""


# Stripe Checkout session creation
@router.get("/create-checkout")
async def create_checkout(agent_id: str, amount: int = 5):
    if not settings.stripe_secret_key:
        raise HTTPException(status_code=503, detail="Stripe not configured")

    if amount not in (5, 10, 25):
        raise HTTPException(status_code=400, detail="Invalid amount")

    import stripe

    stripe.api_key = settings.stripe_secret_key

    session = stripe.checkout.Session.create(
        mode="payment",
        line_items=[
            {
                "price_data": {
                    "currency": "usd",
                    "unit_amount": amount * 100,
                    "product_data": {
                        "name": f"Sixel-Mail Credit ({amount * 100} messages)"
                    },
                },
                "quantity": 1,
            }
        ],
        metadata={"agent_id": agent_id, "credit_amount": str(amount * 100)},
        success_url=f"{settings.api_base_url}/topup?agent_id={agent_id}&success=1",
        cancel_url=f"{settings.api_base_url}/topup?agent_id={agent_id}",
    )
    return RedirectResponse(session.url, status_code=303)
