import hashlib
import html
import secrets

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from app.auth import generate_api_key
from app.config import settings
from app.db import get_pool
from app.routes.signup import _sync_agent_to_kv, get_user_id
from app.services.email import send_email

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
        admin_approved = agent.get("admin_approved", False)
        allstop_badge = ' <span style="background:#dc3545;color:#fff;padding:2px 6px;font-size:12px;">CHANNEL OFF</span>' if not channel_active else ""
        killswitch_badge = ' <span style="background:#6c757d;color:#fff;padding:2px 6px;font-size:12px;">KILL SWITCH</span>' if has_allstop else ""
        pending_badge = ' <span style="background:#ffc107;color:#000;padding:2px 6px;font-size:12px;">PENDING APPROVAL</span>' if not admin_approved else ""

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

        cc_email = agent.get("cc_email")
        cc_email_display = esc(cc_email) if cc_email else "<em>none</em>"

        heartbeat_enabled = agent.get("heartbeat_enabled", True)
        heartbeat_badge = ' <span style="background:#17a2b8;color:#fff;padding:2px 6px;font-size:12px;">HEARTBEAT OFF</span>' if not heartbeat_enabled else ""

        heartbeat_button = (
            f'<form method="POST" action="/account/disable-heartbeat" style="display:inline">'
            f'<input type="hidden" name="agent_id" value="{agent_id}">'
            f'<button type="submit" onclick="return confirm(\'Disable heartbeat monitoring? '
            f'You will not be notified if this agent stops responding.\')">Disable Heartbeat</button></form>'
            if heartbeat_enabled else
            f'<form method="POST" action="/account/enable-heartbeat" style="display:inline">'
            f'<input type="hidden" name="agent_id" value="{agent_id}">'
            f'<button type="submit" onclick="return confirm(\'Enable heartbeat monitoring? '
            f'You will be notified if this agent stops polling.\')">Enable Heartbeat</button></form>'
        )

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
    <h3>{address}@sixel.email{nonce_badge}{heartbeat_badge}{killswitch_badge}{allstop_badge}{pending_badge}</h3>
    <p>Status: {status} (last seen: {last_seen_str})</p>
    <form method="POST" action="/account/set-contact" style="margin:8px 0;display:flex;gap:4px;align-items:center;">
        <input type="hidden" name="agent_id" value="{agent_id}">
        <label>Allowed contact:</label>
        <input type="text" name="allowed_contact" value="{esc(agent['allowed_contact'])}"
               style="font-family:monospace;font-size:13px;padding:4px;width:240px;">
        <button type="submit" style="padding:4px 8px;font-size:12px;">Save</button>
    </form>
    <p>CC email (tee): {cc_email_display}</p>
    <p>Credits: {agent['credit_balance']} messages</p>
    <p>API key: <code>{key_display}</code></p>
    <p><strong>Recent messages:</strong></p>
    <div style="font-size: 14px;">{msg_lines if msg_lines else "    No messages yet"}</div>
    <br>
    <form method="POST" action="/account/update-contact" style="margin: 12px 0;">
        <input type="hidden" name="agent_id" value="{agent_id}">
        <label>Change allowed contact:</label><br>
        <input type="email" name="new_contact" placeholder="new-email@example.com"
            style="font-family:monospace;font-size:14px;padding:6px;width:300px;margin:4px 0;">
        <button type="submit" onclick="return confirm('This will:\\n- Change your allowed contact\\n- Clear all message history\\n- Rotate your API key (old key stops working)\\n\\nYou will need to update your agent config with the new key.\\n\\nContinue?')">Update Contact</button>
    </form>
    <form method="POST" action="/account/update-cc-email" style="margin: 12px 0;">
        <input type="hidden" name="agent_id" value="{agent_id}">
        <label>CC email (copies of all messages forwarded here):</label><br>
        <input type="email" name="cc_email" placeholder="monitor@example.com" value="{esc(cc_email) if cc_email else ''}"
            style="font-family:monospace;font-size:14px;padding:6px;width:300px;margin:4px 0;">
        <button type="submit">Set CC</button>
        <button type="submit" formaction="/account/clear-cc-email">Clear</button>
    </form>
    <a href="/topup?agent_id={agent_id}"><button>Add credit</button></a>
    <form method="POST" action="/account/rotate-key" style="display:inline">
        <input type="hidden" name="agent_id" value="{agent_id}">
        <button type="submit" onclick="return confirm('Generate a new API key? The old key will stop working immediately.')">Rotate API key</button>
    </form>
    {nonce_button}
    {heartbeat_button}
    {allstop_button}
</div>
"""

    # Build link-agents section
    link_section = ""
    if len(agents) >= 2:
        agent_options = "".join(
            f'<option value="{a["id"]}">{esc(a["address"])}</option>' for a in agents
        )
        # Detect existing pairs
        pairs_html = ""
        seen_pairs = set()
        for a in agents:
            if a["allowed_contact"].endswith(f"@{settings.mail_domain}"):
                peer_addr = a["allowed_contact"].replace(f"@{settings.mail_domain}", "")
                peer = next((b for b in agents if b["address"] == peer_addr), None)
                if peer and peer["allowed_contact"] == f"{a['address']}@{settings.mail_domain}":
                    pair_key = tuple(sorted([a["address"], peer["address"]]))
                    if pair_key not in seen_pairs:
                        seen_pairs.add(pair_key)
                        pairs_html += f'<li>{esc(a["address"])}@sixel.email &harr; {esc(peer["address"])}@sixel.email</li>'
        if pairs_html:
            link_section += f'<h3>Active pairs</h3><ul>{pairs_html}</ul>'
        link_section += f"""
<h3>Link agent pair</h3>
<form method="POST" action="/account/link" style="display:flex;gap:8px;align-items:center;">
    <select name="agent_a" style="font-family:monospace;font-size:14px;padding:6px;">{agent_options}</select>
    <span>&harr;</span>
    <select name="agent_b" style="font-family:monospace;font-size:14px;padding:6px;">{agent_options}</select>
    <button type="submit">Link</button>
</form>
<p style="font-size:12px;color:#666;">Sets each agent's allowed contact to the other.</p>"""

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

{link_section}

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


@router.post("/account/enable-heartbeat")
async def enable_heartbeat(request: Request):
    pool, agent, user_id = await _get_verified_agent(request)
    await pool.execute(
        "UPDATE agents SET heartbeat_enabled = TRUE WHERE id = $1", agent["id"]
    )
    return RedirectResponse("/account", status_code=303)


@router.post("/account/disable-heartbeat")
async def disable_heartbeat(request: Request):
    pool, agent, user_id = await _get_verified_agent(request)
    await pool.execute(
        "UPDATE agents SET heartbeat_enabled = FALSE WHERE id = $1", agent["id"]
    )
    return RedirectResponse("/account", status_code=303)


@router.post("/account/update-contact", response_class=HTMLResponse)
async def update_contact(request: Request):
    form = await request.form()
    pool, agent, user_id = await _get_verified_agent(request, form)
    new_contact = form.get("new_contact", "").strip()
    agent_id = str(agent["id"])
    address = agent["address"]

    if not new_contact or "@" not in new_contact:
        raise HTTPException(status_code=400, detail="Invalid email address")

    old_contact = agent["allowed_contact"]
    if new_contact.lower() == old_contact.lower():
        raise HTTPException(status_code=400, detail="New contact is the same as the current one")

    # 1. Delete all messages for this agent
    await pool.execute("DELETE FROM attachments WHERE message_id IN (SELECT id FROM messages WHERE agent_id = $1)", agent["id"])
    await pool.execute("DELETE FROM messages WHERE agent_id = $1", agent["id"])

    # 2. Delete old API keys, generate new one
    await pool.execute("DELETE FROM api_keys WHERE agent_id = $1", agent["id"])
    key, key_hash, key_prefix = generate_api_key()
    await pool.execute(
        "INSERT INTO api_keys (agent_id, key_hash, key_prefix) VALUES ($1, $2, $3)",
        agent["id"], key_hash, key_prefix,
    )

    # 3. Update allowed_contact
    await pool.execute(
        "UPDATE agents SET allowed_contact = $1 WHERE id = $2",
        new_contact, agent["id"],
    )

    # 4. Burn existing nonces (they were for the old contact)
    await pool.execute("DELETE FROM nonces WHERE agent_id = $1", agent["id"])

    # 5. Sync to Cloudflare KV
    await _sync_agent_to_kv(
        address, new_contact,
        agent.get("nonce_enabled", False),
        admin_approved=agent.get("admin_approved", False),
    )

    # 6. Notify old contact
    try:
        await send_email(
            from_address=f"{address}@{settings.mail_domain}",
            to_address=old_contact,
            subject=f"[{address}] allowed contact changed",
            body=(
                f"The allowed contact for {address}@{settings.mail_domain} has been changed.\n\n"
                f"If you did not make this change, the account may be compromised. "
                f"Log in at {settings.api_base_url}/account to review."
            ),
            reply_to=f"{address}@{settings.mail_domain}",
        )
    except Exception:
        pass  # Best-effort notification

    return f"""<!DOCTYPE html>
<html><head><title>Sixel-Mail - Contact Updated</title>
<style>
    body {{ font-family: monospace; max-width: 600px; margin: 40px auto; padding: 0 20px; }}
    button {{ font-family: monospace; font-size: 14px; cursor: pointer; background: #000; color: #fff; border: none; padding: 8px 16px; margin: 4px; }}
    code {{ background: #f0f0f0; padding: 2px 6px; }}
</style></head>
<body>
<h1>sixel.email</h1>
<h2>{html.escape(address)}@sixel.email — contact updated</h2>
<p>Allowed contact changed to: <strong>{html.escape(new_contact)}</strong></p>
<p>All message history has been cleared.</p>
<div style="background: #fff3cd; border: 1px solid #ffc107; padding: 16px; margin: 16px 0;">
    <strong>Your new API key (shown once, save it now):</strong><br><br>
    <code>{key}</code><br><br>
    The old key has been revoked. Update your agent config with this key.
</div>
<p>A notification has been sent to the previous contact.</p>
<a href="/account"><button>Back to dashboard</button></a>
</body></html>"""


@router.post("/account/enable-nonce")
async def enable_nonce(request: Request):
    pool, agent, user_id = await _get_verified_agent(request)

    await pool.execute(
        "UPDATE agents SET nonce_enabled = true WHERE id = $1", agent["id"]
    )
    await _sync_agent_to_kv(agent["address"], agent["allowed_contact"], True, admin_approved=agent.get("admin_approved", False))

    return RedirectResponse("/account", status_code=303)


@router.post("/account/disable-nonce")
async def disable_nonce(request: Request):
    pool, agent, user_id = await _get_verified_agent(request)

    await pool.execute(
        "UPDATE agents SET nonce_enabled = false WHERE id = $1", agent["id"]
    )
    await _sync_agent_to_kv(agent["address"], agent["allowed_contact"], False, admin_approved=agent.get("admin_approved", False))

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


@router.post("/account/update-cc-email")
async def update_cc_email(request: Request):
    """Set the CC email for agent-to-agent monitoring tee."""
    form = await request.form()
    pool, agent, user_id = await _get_verified_agent(request, form)
    cc_email = form.get("cc_email", "").strip()

    if not cc_email or "@" not in cc_email:
        raise HTTPException(status_code=400, detail="Invalid email address")

    await pool.execute(
        "UPDATE agents SET cc_email = $1 WHERE id = $2", cc_email, agent["id"]
    )

    return RedirectResponse("/account", status_code=303)


@router.post("/account/set-contact")
async def set_contact(request: Request):
    """Lightweight contact update — just changes allowed_contact + syncs KV."""
    form = await request.form()
    pool, agent, user_id = await _get_verified_agent(request, form)
    new_contact = form.get("allowed_contact", "").strip().lower()

    if not new_contact:
        raise HTTPException(status_code=400, detail="Allowed contact cannot be empty")

    await pool.execute(
        "UPDATE agents SET allowed_contact = $1 WHERE id = $2",
        new_contact, agent["id"],
    )
    await _sync_agent_to_kv(
        agent["address"], new_contact, agent.get("nonce_enabled", False),
        admin_approved=agent.get("admin_approved", False),
    )

    return RedirectResponse("/account", status_code=303)


@router.post("/account/link")
async def link_agents(request: Request):
    """Link two agents as a pipe pair — set each as the other's allowed contact."""
    user_id = get_user_id(request)
    if not user_id:
        raise HTTPException(status_code=401, detail="Not logged in")

    form = await request.form()
    agent_a_id = form.get("agent_a", "").strip()
    agent_b_id = form.get("agent_b", "").strip()

    if not agent_a_id or not agent_b_id or agent_a_id == agent_b_id:
        raise HTTPException(status_code=400, detail="Select two different agents")

    pool = await get_pool()
    agent_a = await pool.fetchrow(
        "SELECT id, address, nonce_enabled, admin_approved, user_id FROM agents WHERE id = $1 AND user_id = $2",
        agent_a_id, user_id,
    )
    agent_b = await pool.fetchrow(
        "SELECT id, address, nonce_enabled, admin_approved, user_id FROM agents WHERE id = $1 AND user_id = $2",
        agent_b_id, user_id,
    )
    if not agent_a or not agent_b:
        raise HTTPException(status_code=404, detail="Agent not found")

    contact_a = f"{agent_b['address']}@{settings.mail_domain}"
    contact_b = f"{agent_a['address']}@{settings.mail_domain}"

    await pool.execute("UPDATE agents SET allowed_contact = $1 WHERE id = $2", contact_a, agent_a["id"])
    await pool.execute("UPDATE agents SET allowed_contact = $1 WHERE id = $2", contact_b, agent_b["id"])

    await _sync_agent_to_kv(
        agent_a["address"], contact_a, agent_a["nonce_enabled"],
        admin_approved=agent_a["admin_approved"],
    )
    await _sync_agent_to_kv(
        agent_b["address"], contact_b, agent_b["nonce_enabled"],
        admin_approved=agent_b["admin_approved"],
    )

    return RedirectResponse("/account", status_code=303)


@router.post("/account/clear-cc-email")
async def clear_cc_email(request: Request):
    """Clear the CC email."""
    form = await request.form()
    pool, agent, user_id = await _get_verified_agent(request, form)

    await pool.execute(
        "UPDATE agents SET cc_email = NULL WHERE id = $1", agent["id"]
    )

    return RedirectResponse("/account", status_code=303)
