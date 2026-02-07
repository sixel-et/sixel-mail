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


# Step 3: Setup page — pick agent address, set allowed contact
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
</style></head>
<body>
<h1>sixel.email</h1>
<h2>Set up your agent</h2>
<form method="POST" action="/setup">
    <label>Agent address:</label><br>
    <input type="text" name="address" placeholder="my-agent" pattern="[a-z0-9\\-]{{3,30}}" required>
    <span class="suffix">@sixel.email</span><br><br>
    <label>Your email (the one allowed contact):</label><br>
    <input type="email" name="allowed_contact" required><br><br>
    <button type="submit">Create agent</button>
</form>
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
            INSERT INTO agents (user_id, address, allowed_contact, credit_balance)
            VALUES ($1, $2, $3, 0)
            RETURNING id
            """,
            user_id,
            address,
            allowed_contact,
        )
    except Exception:
        raise HTTPException(status_code=400, detail="Address already taken")

    agent_id = agent["id"]

    # Generate API key
    key, key_hash, key_prefix = generate_api_key()
    await pool.execute(
        "INSERT INTO api_keys (agent_id, key_hash, key_prefix) VALUES ($1, $2, $3)",
        agent_id,
        key_hash,
        key_prefix,
    )

    # Render key display page directly (never put API key in a URL)
    config_snippet = (
        f"You have an email address for contacting me when you're stuck.\\n"
        f"API: {settings.api_base_url}/v1\\n"
        f"Token: {key}\\n"
        f"Use POST /v1/send to email me. Use GET /v1/inbox to check for my reply.\\n"
        f"Poll /v1/inbox every 60 seconds while waiting."
    )
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
