import hashlib
import html
import secrets

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from app.auth import generate_api_key
from app.config import settings
from app.db import get_pool
from app.routes.signup import _sync_agent_to_kv, get_user_id

router = APIRouter()


@router.get("/account", response_class=HTMLResponse)
async def account_page(request: Request):
    user_id = get_user_id(request)
    if not user_id:
        return RedirectResponse("/auth/github")
    pool = await get_pool()

    user = await pool.fetchrow("SELECT * FROM users WHERE id = $1", user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    agents = await pool.fetch(
        "SELECT * FROM agents WHERE user_id = $1 ORDER BY created_at", user_id
    )

    esc = html.escape

    agent_sections = ""
    for agent in agents:
        agent_id = str(agent["id"])
        address = esc(agent["address"])
        last_seen = agent["last_seen_at"]
        last_seen_str = last_seen.strftime("%I:%M%p %Z") if last_seen else "never"
        status = "alive" if not agent["agent_down_notified"] else "OFFLINE"
        nonce_enabled = agent.get("nonce_enabled", False)
        nonce_badge = ' <span style="background:#28a745;color:#fff;padding:2px 6px;font-size:12px;">DOOR KNOCK</span>' if nonce_enabled else ""
        has_allstop = bool(agent.get("allstop_key_hash"))
        channel_active = agent.get("channel_active", True)
        allstop_badge = ' <span style="background:#dc3545;color:#fff;padding:2px 6px;font-size:12px;">CHANNEL OFF</span>' if not channel_active else ""
        killswitch_badge = ' <span style="background:#6c757d;color:#fff;padding:2px 6px;font-size:12px;">KILL SWITCH</span>' if has_allstop else ""

        # Get API key prefix
        key_row = await pool.fetchrow(
            "SELECT key_prefix FROM api_keys WHERE agent_id = $1 ORDER BY created_at DESC LIMIT 1",
            agent["id"],
        )
        key_display = f"{esc(key_row['key_prefix'])}..." if key_row else "none"

        # Recent messages
        messages = await pool.fetch(
            """
            SELECT direction, subject, created_at, encrypted FROM messages
            WHERE agent_id = $1 ORDER BY created_at DESC LIMIT 10
            """,
            agent["id"],
        )
        msg_lines = ""
        for msg in messages:
            arrow = "→" if msg["direction"] == "outbound" else "←"
            time_str = msg["created_at"].strftime("%I:%M%p")
            subj = esc(msg["subject"] or "(no subject)")
            lock = " 🔒" if msg.get("encrypted") else ""
            msg_lines += f'    {arrow} "{subj}" ({time_str}){lock}<br>\n'

        # Credit transactions
        txns = await pool.fetch(
            """
            SELECT amount, reason, created_at FROM credit_transactions
            WHERE agent_id = $1 AND amount > 0 ORDER BY created_at DESC LIMIT 5
            """,
            agent["id"],
        )
        txn_lines = ""
        for txn in txns:
            date_str = txn["created_at"].strftime("%b %d")
            amount_dollars = txn["amount"] / 100
            txn_lines += f"  {date_str} — ${amount_dollars:.2f} ({txn['amount']} messages) — {esc(txn['reason'])}<br>\n"

        nonce_button = (
            f'<form method="POST" action="/account/disable-nonce" style="display:inline">'
            f'<input type="hidden" name="agent_id" value="{agent_id}">'
            f'<button type="submit" onclick="return confirm(\'Disable Door Knock verification? '
            f'Emails will be accepted without nonce validation.\')">Disable Door Knock</button></form>'
            if nonce_enabled else
            f'<form method="POST" action="/account/enable-nonce" style="display:inline">'
            f'<input type="hidden" name="agent_id" value="{agent_id}">'
            f'<button type="submit" onclick="return confirm(\'Enable Door Knock verification? '
            f'Outbound emails will include a nonce in reply-to.\')">Enable Door Knock</button></form>'
        )

        if not channel_active:
            allstop_button = (
                f'<form method="POST" action="/account/reactivate-channel" style="display:inline">'
                f'<input type="hidden" name="agent_id" value="{agent_id}">'
                f'<button type="submit" style="background:#dc3545" '
                f'onclick="return confirm(\'Reactivate email channel?\')">Reactivate Channel</button></form>'
            )
        elif has_allstop:
            allstop_button = (
                f'<a href="/account/setup-allstop?agent_id={agent_id}">'
                f'<button style="background:#6c757d">Regenerate Kill Switch</button></a>'
            )
        else:
            allstop_button = (
                f'<a href="/account/setup-allstop?agent_id={agent_id}">'
                f'<button>Setup Kill Switch</button></a>'
            )

        agent_sections += f"""
<div style="border: 1px solid #ccc; padding: 16px; margin: 16px 0;">
    <h3>{address}@sixel.email{nonce_badge}{killswitch_badge}{allstop_badge}</h3>
    <p>Status: {status} (last seen: {last_seen_str})</p>
    <p>Allowed contact: {esc(agent['allowed_contact'])}</p>
    <p>Credits: {agent['credit_balance']} messages</p>
    <p>API key: <code>{key_display}</code></p>
    <p><strong>Recent messages:</strong></p>
    <div style="font-size: 14px;">{msg_lines if msg_lines else "    No messages yet"}</div>
    <br>
    <a href="/topup?agent_id={agent_id}"><button>Add credit</button></a>
    <form method="POST" action="/account/rotate-key" style="display:inline">
        <input type="hidden" name="agent_id" value="{agent_id}">
        <button type="submit" onclick="return confirm('Generate a new API key? The old key will stop working immediately.')">Rotate API key</button>
    </form>
    {nonce_button}
    {allstop_button}
</div>
"""

    return f"""<!DOCTYPE html>
<html><head><title>Sixel-Mail Account</title>
<style>
    body {{ font-family: monospace; max-width: 600px; margin: 40px auto; padding: 0 20px; }}
    button {{ font-family: monospace; font-size: 14px; cursor: pointer; background: #000; color: #fff; border: none; padding: 8px 16px; margin: 4px; }}
    code {{ background: #f0f0f0; padding: 2px 6px; }}
</style></head>
<body>
<h1>sixel.email — your account</h1>
<p>{esc(user['github_username'])} ({esc(user['email'])})</p>
{agent_sections}
<br>
<a href="/setup"><button>+ Create another agent</button></a>
</body></html>"""


async def _get_verified_agent(request: Request, form=None):
    """Verify user owns the agent. Returns (pool, agent, user_id)."""
    user_id = get_user_id(request)
    if not user_id:
        raise HTTPException(status_code=401, detail="Not logged in")
    if form is None:
        form = await request.form()
    agent_id = form["agent_id"]
    pool = await get_pool()
    agent = await pool.fetchrow(
        "SELECT * FROM agents WHERE id = $1 AND user_id = $2", agent_id, user_id
    )
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    return pool, agent, user_id


@router.post("/account/rotate-key", response_class=HTMLResponse)
async def rotate_key(request: Request):
    pool, agent, user_id = await _get_verified_agent(request)
    agent_id = str(agent["id"])
    address = html.escape(agent["address"])

    # Delete old keys
    await pool.execute("DELETE FROM api_keys WHERE agent_id = $1", agent["id"])

    # Generate new key
    key, key_hash, key_prefix = generate_api_key()
    await pool.execute(
        "INSERT INTO api_keys (agent_id, key_hash, key_prefix) VALUES ($1, $2, $3)",
        agent["id"],
        key_hash,
        key_prefix,
    )

    return f"""<!DOCTYPE html>
<html><head><title>Sixel-Mail - New API Key</title>
<style>
    body {{ font-family: monospace; max-width: 600px; margin: 40px auto; padding: 0 20px; }}
    button {{ font-family: monospace; font-size: 14px; cursor: pointer; background: #000; color: #fff; border: none; padding: 8px 16px; margin: 4px; }}
    code {{ background: #f0f0f0; padding: 2px 6px; }}
    pre {{ background: #f0f0f0; padding: 12px; white-space: pre-wrap; }}
</style></head>
<body>
<h1>sixel.email</h1>
<h2>{address}@sixel.email — new API key</h2>
<div style="background: #fff3cd; border: 1px solid #ffc107; padding: 16px; margin: 16px 0;">
    <strong>Your new API key (shown once, save it now):</strong><br><br>
    <code>{key}</code>
</div>
<p>The old key has been revoked.</p>
<a href="/account"><button>Back to dashboard</button></a>
</body></html>"""


@router.post("/account/enable-nonce")
async def enable_nonce(request: Request):
    pool, agent, user_id = await _get_verified_agent(request)

    await pool.execute(
        "UPDATE agents SET nonce_enabled = true WHERE id = $1", agent["id"]
    )
    await _sync_agent_to_kv(agent["address"], agent["allowed_contact"], True)

    return RedirectResponse("/account", status_code=303)


@router.post("/account/disable-nonce")
async def disable_nonce(request: Request):
    pool, agent, user_id = await _get_verified_agent(request)

    await pool.execute(
        "UPDATE agents SET nonce_enabled = false WHERE id = $1", agent["id"]
    )
    await _sync_agent_to_kv(agent["address"], agent["allowed_contact"], False)

    return RedirectResponse("/account", status_code=303)


@router.get("/account/setup-allstop", response_class=HTMLResponse)
async def setup_allstop_page(request: Request, agent_id: str):
    """Generate a kill switch key, store hash, show QR code + address."""
    user_id = get_user_id(request)
    if not user_id:
        return RedirectResponse("/auth/github")
    pool = await get_pool()
    agent = await pool.fetchrow(
        "SELECT * FROM agents WHERE id = $1 AND user_id = $2", agent_id, user_id
    )
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")

    address = html.escape(agent["address"])

    # Generate key server-side (we need the hash)
    allstop_key = secrets.token_urlsafe(32)
    key_hash = hashlib.sha256(allstop_key.encode()).hexdigest()

    # Store hash in DB
    await pool.execute(
        "UPDATE agents SET allstop_key_hash = $1 WHERE id = $2",
        key_hash,
        agent["id"],
    )

    allstop_address = f"{agent['address']}+allstop-{allstop_key}@{settings.mail_domain}"
    allstop_url = f"{settings.api_base_url}/allstop?agent={agent['address']}&key={allstop_key}"

    return f"""<!DOCTYPE html>
<html><head><title>Sixel-Mail - Kill Switch</title>
<style>
    body {{ font-family: monospace; max-width: 600px; margin: 40px auto; padding: 0 20px; }}
    button {{ font-family: monospace; font-size: 14px; cursor: pointer; background: #000; color: #fff; border: none; padding: 8px 16px; margin: 4px; }}
    code {{ background: #f0f0f0; padding: 2px 6px; word-break: break-all; }}
    .warning {{ background: #fff3cd; border: 1px solid #ffc107; padding: 16px; margin: 16px 0; }}
    .address-box {{ background: #f8f9fa; border: 1px solid #dee2e6; padding: 12px; margin: 8px 0; word-break: break-all; font-size: 13px; }}
</style>
<script src="https://cdn.jsdelivr.net/npm/qrcode-generator@1.4.4/qrcode.min.js"></script>
</head>
<body>
<h1>sixel.email</h1>
<h2>Kill Switch for {address}@sixel.email</h2>

<div class="warning">
    <strong>Save this now.</strong> This key is shown once. If you lose it, you can regenerate (which invalidates the old one).
</div>

<h3>Email kill switch</h3>
<p>Save this address as a contact (e.g., "Kill {address}").</p>
<p>To kill the channel: send any email to this address.</p>
<div class="address-box" id="allstop-address">{html.escape(allstop_address)}</div>
<button type="button" onclick="copyAddr()">Copy address</button>

<h3>Scan to save</h3>
<div id="qr-code"></div>

<h3>Browser kill switch</h3>
<p>Bookmark this URL. Click it to kill the channel from any browser.</p>
<div class="address-box"><a href="{html.escape(allstop_url)}">{html.escape(allstop_url)}</a></div>

<br>
<a href="/account"><button>Back to dashboard</button></a>

<script>
const allstopAddr = {html.escape(repr(allstop_address))};

if (typeof qrcode !== 'undefined') {{
    const qr = qrcode(0, 'L');
    qr.addData(allstopAddr);
    qr.make();
    document.getElementById('qr-code').innerHTML = qr.createSvgTag(4);
}}

function copyAddr() {{
    navigator.clipboard.writeText(allstopAddr).then(function() {{
        alert('Kill switch address copied');
    }});
}}
</script>
</body></html>"""


@router.post("/account/reactivate-channel")
async def reactivate_channel(request: Request):
    """Reactivate a channel that was killed via allstop."""
    pool, agent, user_id = await _get_verified_agent(request)

    await pool.execute(
        "UPDATE agents SET channel_active = TRUE WHERE id = $1", agent["id"]
    )

    return RedirectResponse("/account", status_code=303)
