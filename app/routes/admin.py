import html
import logging

import httpx
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from app.config import settings
from app.db import get_pool
from app.routes.signup import _sync_agent_to_kv, get_user_id
from app.services.credits import add_credits

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/admin")


async def _delete_agent_from_kv(address: str):
    """Remove agent from Cloudflare KV so the Worker stops accepting email."""
    if not settings.cf_account_id or not settings.cf_kv_namespace_id or not settings.cf_api_token:
        return
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.delete(
                f"https://api.cloudflare.com/client/v4/accounts/{settings.cf_account_id}"
                f"/storage/kv/namespaces/{settings.cf_kv_namespace_id}/values/{address}",
                headers={"Authorization": f"Bearer {settings.cf_api_token}"},
            )
            if resp.status_code == 200:
                logger.info("Deleted agent %s from Cloudflare KV", address)
            else:
                logger.error("Failed to delete %s from KV: %s %s", address, resp.status_code, resp.text)
    except Exception:
        logger.exception("Error deleting agent %s from Cloudflare KV", address)

# Admin access: GitHub user IDs allowed to access the admin panel
ADMIN_GITHUB_IDS = {6231816}  # estbiostudent (Eric)

STYLE = """
<style>
    body { font-family: monospace; max-width: 900px; margin: 40px auto; padding: 0 20px; }
    button { font-family: monospace; font-size: 14px; cursor: pointer; background: #000; color: #fff;
             border: none; padding: 8px 16px; margin: 4px; }
    button.danger { background: #c00; }
    code { background: #f0f0f0; padding: 2px 6px; }
    table { border-collapse: collapse; width: 100%; margin: 16px 0; }
    th, td { border: 1px solid #ddd; padding: 8px; text-align: left; font-family: monospace; font-size: 14px; }
    th { background: #f5f5f5; }
    tr:hover { background: #f9f9f9; }
    .stat { display: inline-block; border: 1px solid #ccc; padding: 12px 20px; margin: 8px; text-align: center; }
    .stat .number { font-size: 24px; font-weight: bold; }
    .stat .label { font-size: 12px; color: #666; }
    input[type=number] { font-family: monospace; font-size: 14px; padding: 6px; width: 80px; }
    select { font-family: monospace; font-size: 14px; padding: 6px; }
    .flash { background: #d4edda; border: 1px solid #c3e6cb; padding: 12px; margin: 16px 0; }
    a { color: #000; }
</style>
"""


async def _require_admin(request: Request) -> str:
    """Check that the current user is an admin. Returns user_id or raises."""
    user_id = get_user_id(request)
    if not user_id:
        raise HTTPException(status_code=302, headers={"Location": "/auth/github"})

    pool = await get_pool()
    user = await pool.fetchrow("SELECT github_id FROM users WHERE id = $1", user_id)
    if not user or user["github_id"] not in ADMIN_GITHUB_IDS:
        raise HTTPException(status_code=403, detail="Admin access required")

    return user_id


@router.get("/", response_class=HTMLResponse)
async def admin_dashboard(request: Request):
    await _require_admin(request)
    pool = await get_pool()

    # System stats
    total_agents = await pool.fetchval("SELECT COUNT(*) FROM agents")
    total_users = await pool.fetchval("SELECT COUNT(*) FROM users")
    total_messages = await pool.fetchval("SELECT COUNT(*) FROM messages")
    total_credits_held = await pool.fetchval("SELECT COALESCE(SUM(credit_balance), 0) FROM agents")
    agents_online = await pool.fetchval(
        "SELECT COUNT(*) FROM agents WHERE last_seen_at > now() - interval '5 minutes'"
    )

    # All agents with user info
    agents = await pool.fetch("""
        SELECT a.id, a.address, a.allowed_contact, a.credit_balance, a.last_seen_at,
               a.agent_down_notified, a.nonce_enabled, a.admin_approved, a.created_at,
               u.github_username, u.email as user_email,
               (SELECT COUNT(*) FROM messages m WHERE m.agent_id = a.id) as msg_count,
               (SELECT COUNT(*) FROM messages m WHERE m.agent_id = a.id AND m.direction = 'inbound' AND m.is_read = FALSE) as unread_count
        FROM agents a
        JOIN users u ON a.user_id = u.id
        ORDER BY a.created_at DESC
    """)

    esc = html.escape

    agent_rows = ""
    for a in agents:
        addr = esc(a["address"])
        last_seen = a["last_seen_at"]
        if last_seen:
            import datetime
            age = datetime.datetime.now(datetime.timezone.utc) - last_seen
            if age.total_seconds() < 300:
                status = "online"
                status_color = "#28a745"
            elif age.total_seconds() < 3600:
                status = f"{int(age.total_seconds() / 60)}m ago"
                status_color = "#ffc107"
            else:
                status = f"{int(age.total_seconds() / 3600)}h ago"
                status_color = "#dc3545"
        else:
            status = "never"
            status_color = "#999"

        nonce = "yes" if a["nonce_enabled"] else "no"
        channel = "on" if a.get("channel_active", True) else '<span style="color:#dc3545">OFF</span>'
        approved = '<span style="color:#28a745">yes</span>' if a.get("admin_approved", False) else '<span style="color:#dc3545;font-weight:bold">PENDING</span>'
        agent_rows += f"""
        <tr>
            <td><input type="checkbox" name="agent_ids" value="{a['id']}" class="agent-check"></td>
            <td><a href="/admin/agent/{a['id']}">{addr}@sixel.email</a></td>
            <td>{esc(a['github_username'])}</td>
            <td>{a['credit_balance']}</td>
            <td><span style="color:{status_color}">{status}</span></td>
            <td>{a['msg_count']} ({a['unread_count']} unread)</td>
            <td>{nonce}</td>
            <td>{channel}</td>
            <td>{approved}</td>
        </tr>"""

    flash = ""
    if request.query_params.get("credited"):
        flash = '<div class="flash">Credits added successfully.</div>'
    elif request.query_params.get("deleted"):
        flash = '<div class="flash" style="background:#f8d7da;border-color:#f5c6cb;">Agent(s) deleted.</div>'
    elif request.query_params.get("bulk_done"):
        flash = '<div class="flash">Bulk action applied.</div>'

    return f"""<!DOCTYPE html>
<html><head><title>Sixel-Mail Admin</title>{STYLE}</head>
<body>
<h1>sixel.email admin</h1>
{flash}
<div>
    <div class="stat"><div class="number">{total_agents}</div><div class="label">agents</div></div>
    <div class="stat"><div class="number">{agents_online}</div><div class="label">online</div></div>
    <div class="stat"><div class="number">{total_users}</div><div class="label">users</div></div>
    <div class="stat"><div class="number">{total_messages}</div><div class="label">messages</div></div>
    <div class="stat"><div class="number">{total_credits_held}</div><div class="label">credits held</div></div>
</div>

<p><a href="/admin/owners">Owner config</a></p>

<h2>All agents</h2>
<form method="POST" action="/admin/bulk" id="bulk-form">
<div style="margin:8px 0;display:flex;gap:8px;align-items:center;">
    <label><input type="checkbox" id="select-all" onchange="document.querySelectorAll('.agent-check').forEach(c=>c.checked=this.checked)"> Select all</label>
    <select name="action" style="font-family:monospace;font-size:14px;padding:6px;">
        <option value="">— Bulk action —</option>
        <option value="approve">Approve</option>
        <option value="unapprove">Revoke approval</option>
        <option value="enable_channel">Enable channel</option>
        <option value="disable_channel">Disable channel</option>
        <option value="enable_nonce">Enable Door Knock</option>
        <option value="disable_nonce">Disable Door Knock</option>
        <option value="delete">Delete agents</option>
    </select>
    <button type="submit" onclick="if(this.form.action.value==='delete')return confirm('Delete selected agents? Cannot be undone.')">Apply</button>
</div>
<table>
    <tr><th style="width:30px;"></th><th>Address</th><th>Owner</th><th>Credits</th><th>Last seen</th><th>Messages</th><th>Nonce</th><th>Channel</th><th>Approved</th></tr>
    {agent_rows}
</table>
</form>

<h2>Quick credit</h2>
<form method="POST" action="/admin/credits" style="display:flex;gap:8px;align-items:center;">
    <select name="agent_id">
        {''.join(f'<option value="{a["id"]}">{esc(a["address"])}</option>' for a in agents)}
    </select>
    <input type="number" name="amount" value="100" min="1" max="10000">
    <input type="text" name="reason" value="admin_grant" style="font-family:monospace;font-size:14px;padding:6px;width:150px;">
    <button type="submit">Add credits</button>
</form>

</body></html>"""


@router.get("/agent/{agent_id}", response_class=HTMLResponse)
async def admin_agent_detail(agent_id: str, request: Request):
    await _require_admin(request)
    pool = await get_pool()

    agent = await pool.fetchrow("""
        SELECT a.*, u.github_username, u.email as user_email
        FROM agents a JOIN users u ON a.user_id = u.id
        WHERE a.id = $1
    """, agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")

    esc = html.escape
    addr = esc(agent["address"])

    # Messages (last 50) with attachment counts
    messages = await pool.fetch("""
        SELECT m.id, m.direction, m.subject, m.body, m.is_read, m.encrypted, m.created_at,
               (SELECT COUNT(*) FROM attachments a WHERE a.message_id = m.id) as attachment_count
        FROM messages m WHERE m.agent_id = $1
        ORDER BY m.created_at DESC LIMIT 50
    """, agent_id)

    msg_rows = ""
    for m in messages:
        arrow = "→ out" if m["direction"] == "outbound" else "← in"
        time_str = m["created_at"].strftime("%Y-%m-%d %H:%M")
        subj = esc(m["subject"] or "(no subject)")[:60]
        body_preview = esc(m["body"][:100]) if m["body"] else ""
        if m.get("encrypted"):
            body_preview = "<em>(encrypted)</em>"
        read_mark = "" if m["is_read"] or m["direction"] == "outbound" else " <strong>NEW</strong>"
        att_badge = f' <span style="color:#0066cc;font-size:11px;">({m["attachment_count"]} file{"s" if m["attachment_count"] != 1 else ""})</span>' if m["attachment_count"] > 0 else ""
        msg_rows += f"""
        <tr>
            <td>{time_str}</td>
            <td>{arrow}{read_mark}</td>
            <td>{subj}{att_badge}</td>
            <td style="font-size:12px;color:#666;">{body_preview}</td>
        </tr>"""

    # Credit transactions (last 20)
    txns = await pool.fetch("""
        SELECT amount, reason, stripe_session_id, created_at
        FROM credit_transactions WHERE agent_id = $1
        ORDER BY created_at DESC LIMIT 20
    """, agent_id)

    txn_rows = ""
    for t in txns:
        time_str = t["created_at"].strftime("%Y-%m-%d %H:%M")
        amount = t["amount"]
        sign = "+" if amount > 0 else ""
        color = "#28a745" if amount > 0 else "#dc3545"
        reason = esc(t["reason"])
        txn_rows += f"""
        <tr>
            <td>{time_str}</td>
            <td style="color:{color}">{sign}{amount}</td>
            <td>{reason}</td>
        </tr>"""

    # API key info
    key_row = await pool.fetchrow(
        "SELECT key_prefix, created_at FROM api_keys WHERE agent_id = $1 ORDER BY created_at DESC LIMIT 1",
        agent["id"],
    )
    key_info = f"<code>{esc(key_row['key_prefix'])}...</code> (created {key_row['created_at'].strftime('%Y-%m-%d')})" if key_row else "none"

    last_seen = agent["last_seen_at"]
    last_seen_str = last_seen.strftime("%Y-%m-%d %H:%M:%S UTC") if last_seen else "never"
    nonce_enabled = agent.get("nonce_enabled", False)
    nonce_str = "enabled" if nonce_enabled else "disabled"
    channel_active = agent.get("channel_active", True)
    channel_str = "active" if channel_active else "DISABLED"
    channel_color = "#28a745" if channel_active else "#dc3545"
    admin_approved = agent.get("admin_approved", False)
    approved_str = "approved" if admin_approved else "PENDING"
    approved_color = "#28a745" if admin_approved else "#dc3545"
    created_str = agent["created_at"].strftime("%Y-%m-%d %H:%M")

    flash = ""
    if request.query_params.get("credited"):
        flash = '<div class="flash">Credits added successfully.</div>'
    elif request.query_params.get("nonce_toggled"):
        flash = f'<div class="flash">Door Knock {"enabled" if nonce_enabled else "disabled"}.</div>'
    elif request.query_params.get("channel_toggled"):
        flash = f'<div class="flash">Channel {"enabled" if channel_active else "disabled"}.</div>'
    elif request.query_params.get("approval_toggled"):
        flash = f'<div class="flash">Admin approval {"granted" if admin_approved else "revoked"}.</div>'

    return f"""<!DOCTYPE html>
<html><head><title>Admin — {addr}@sixel.email</title>{STYLE}</head>
<body>
<p><a href="/admin/">&larr; Back to dashboard</a></p>
<h1>{addr}@sixel.email</h1>
{flash}

<table style="width:auto;">
    <tr><td><strong>Owner</strong></td><td>{esc(agent['github_username'])} ({esc(agent['user_email'])})</td></tr>
    <tr><td><strong>Allowed contact</strong></td><td>{esc(agent['allowed_contact'])}</td></tr>
    <tr><td><strong>Credits</strong></td><td>{agent['credit_balance']}</td></tr>
    <tr><td><strong>Last seen</strong></td><td>{last_seen_str}</td></tr>
    <tr><td><strong>Door Knock</strong></td><td>{nonce_str}</td></tr>
    <tr><td><strong>Channel</strong></td><td><span style="color:{channel_color}">{channel_str}</span></td></tr>
    <tr><td><strong>Admin approved</strong></td><td><span style="color:{approved_color};font-weight:bold">{approved_str}</span></td></tr>
    <tr><td><strong>API key</strong></td><td>{key_info}</td></tr>
    <tr><td><strong>Created</strong></td><td>{created_str}</td></tr>
</table>

<h3>Actions</h3>
<div style="display:flex;gap:8px;flex-wrap:wrap;align-items:center;">
    <form method="POST" action="/admin/agent/{agent_id}/toggle-approval" style="margin:0;">
        <button type="submit" class="{'danger' if admin_approved else ''}" style="{'background:#28a745' if not admin_approved else ''}">
            {'Revoke approval' if admin_approved else 'Approve'}
        </button>
    </form>
    <form method="POST" action="/admin/agent/{agent_id}/toggle-nonce" style="margin:0;">
        <button type="submit">{'Disable' if nonce_enabled else 'Enable'} Door Knock</button>
    </form>
    <form method="POST" action="/admin/agent/{agent_id}/toggle-channel" style="margin:0;">
        <button type="submit" class="{'danger' if channel_active else ''}">
            {'Disable channel' if channel_active else 'Enable channel'}
        </button>
    </form>
</div>

<h3>Add credits</h3>
<form method="POST" action="/admin/credits" style="display:flex;gap:8px;align-items:center;">
    <input type="hidden" name="agent_id" value="{agent_id}">
    <input type="number" name="amount" value="100" min="1" max="10000">
    <input type="text" name="reason" value="admin_grant" style="font-family:monospace;font-size:14px;padding:6px;width:150px;">
    <button type="submit">Add credits</button>
</form>

<h3>Danger zone</h3>
<form method="POST" action="/admin/agent/{agent_id}/delete"
      onsubmit="return confirm('Delete {addr}@sixel.email? This removes the agent, all messages, API keys, and KV entry. Cannot be undone.');">
    <button type="submit" class="danger">Delete agent</button>
</form>

<h2>Messages (last 50)</h2>
<table>
    <tr><th>Time</th><th>Dir</th><th>Subject</th><th>Preview</th></tr>
    {msg_rows if msg_rows else '<tr><td colspan="4">No messages</td></tr>'}
</table>

<h2>Credit transactions (last 20)</h2>
<table>
    <tr><th>Time</th><th>Amount</th><th>Reason</th></tr>
    {txn_rows if txn_rows else '<tr><td colspan="3">No transactions</td></tr>'}
</table>

</body></html>"""


@router.post("/credits")
async def admin_add_credits(request: Request):
    await _require_admin(request)

    form = await request.form()
    agent_id = form.get("agent_id", "").strip()
    amount = int(form.get("amount", 0))
    reason = form.get("reason", "admin_grant").strip()

    if not agent_id or amount < 1 or amount > 10000:
        raise HTTPException(status_code=400, detail="Invalid agent or amount")

    pool = await get_pool()

    # Verify agent exists
    agent = await pool.fetchrow("SELECT id, address FROM agents WHERE id = $1", agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")

    new_balance = await add_credits(pool, agent_id, amount, reason)
    logger.info("Admin granted %d credits to %s (reason: %s), new balance: %d",
                amount, agent["address"], reason, new_balance)

    # Redirect back to where we came from
    referer = request.headers.get("referer", "")
    if f"/admin/agent/{agent_id}" in referer:
        return RedirectResponse(f"/admin/agent/{agent_id}?credited=1", status_code=303)
    return RedirectResponse("/admin/?credited=1", status_code=303)


@router.post("/bulk")
async def admin_bulk_action(request: Request):
    await _require_admin(request)

    form = await request.form()
    action = form.get("action", "")
    agent_ids = form.getlist("agent_ids")

    if not action or not agent_ids:
        return RedirectResponse("/admin/", status_code=303)

    pool = await get_pool()

    if action == "approve":
        for aid in agent_ids:
            agent = await pool.fetchrow("SELECT address, allowed_contact, nonce_enabled FROM agents WHERE id = $1", aid)
            if agent:
                await pool.execute("UPDATE agents SET admin_approved = TRUE WHERE id = $1", aid)
                await _sync_agent_to_kv(agent["address"], agent["allowed_contact"], agent["nonce_enabled"], admin_approved=True)
        logger.info("Admin bulk approved %d agents", len(agent_ids))
    elif action == "unapprove":
        for aid in agent_ids:
            agent = await pool.fetchrow("SELECT address, allowed_contact, nonce_enabled FROM agents WHERE id = $1", aid)
            if agent:
                await pool.execute("UPDATE agents SET admin_approved = FALSE WHERE id = $1", aid)
                await _sync_agent_to_kv(agent["address"], agent["allowed_contact"], agent["nonce_enabled"], admin_approved=False)
        logger.info("Admin bulk unapproved %d agents", len(agent_ids))
    elif action == "enable_channel":
        for aid in agent_ids:
            await pool.execute("UPDATE agents SET channel_active = TRUE WHERE id = $1", aid)
        logger.info("Admin bulk enabled channel for %d agents", len(agent_ids))
    elif action == "disable_channel":
        for aid in agent_ids:
            await pool.execute("UPDATE agents SET channel_active = FALSE WHERE id = $1", aid)
        logger.info("Admin bulk disabled channel for %d agents", len(agent_ids))
    elif action == "enable_nonce":
        for aid in agent_ids:
            agent = await pool.fetchrow("SELECT address, allowed_contact, admin_approved FROM agents WHERE id = $1", aid)
            if agent:
                await pool.execute("UPDATE agents SET nonce_enabled = TRUE WHERE id = $1", aid)
                await _sync_agent_to_kv(agent["address"], agent["allowed_contact"], True, admin_approved=agent["admin_approved"])
        logger.info("Admin bulk enabled nonce for %d agents", len(agent_ids))
    elif action == "disable_nonce":
        for aid in agent_ids:
            agent = await pool.fetchrow("SELECT address, allowed_contact, admin_approved FROM agents WHERE id = $1", aid)
            if agent:
                await pool.execute("UPDATE agents SET nonce_enabled = FALSE WHERE id = $1", aid)
                await _sync_agent_to_kv(agent["address"], agent["allowed_contact"], False, admin_approved=agent["admin_approved"])
        logger.info("Admin bulk disabled nonce for %d agents", len(agent_ids))
    elif action == "delete":
        for aid in agent_ids:
            agent = await pool.fetchrow("SELECT id, address FROM agents WHERE id = $1", aid)
            if agent:
                await pool.execute("DELETE FROM nonces WHERE agent_id = $1", agent["id"])
                await pool.execute("DELETE FROM messages WHERE agent_id = $1", agent["id"])
                await pool.execute("DELETE FROM credit_transactions WHERE agent_id = $1", agent["id"])
                await pool.execute("DELETE FROM api_keys WHERE agent_id = $1", agent["id"])
                await pool.execute("DELETE FROM agents WHERE id = $1", agent["id"])
                await _delete_agent_from_kv(agent["address"])
                logger.warning("Admin bulk deleted agent %s", agent["address"])

    param = "bulk_done"
    if action == "delete":
        param = "deleted"
    return RedirectResponse(f"/admin/?{param}=1", status_code=303)


@router.post("/agent/{agent_id}/toggle-approval")
async def admin_toggle_approval(agent_id: str, request: Request):
    await _require_admin(request)
    pool = await get_pool()

    agent = await pool.fetchrow(
        "SELECT id, address, allowed_contact, nonce_enabled, admin_approved FROM agents WHERE id = $1",
        agent_id,
    )
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")

    new_value = not agent["admin_approved"]
    await pool.execute("UPDATE agents SET admin_approved = $1 WHERE id = $2", new_value, agent["id"])
    await _sync_agent_to_kv(agent["address"], agent["allowed_contact"], agent["nonce_enabled"], admin_approved=new_value)
    logger.info("Admin toggled approval for %s: %s", agent["address"], new_value)

    return RedirectResponse(f"/admin/agent/{agent_id}?approval_toggled=1", status_code=303)


@router.post("/agent/{agent_id}/toggle-nonce")
async def admin_toggle_nonce(agent_id: str, request: Request):
    await _require_admin(request)
    pool = await get_pool()

    agent = await pool.fetchrow(
        "SELECT id, address, allowed_contact, nonce_enabled, admin_approved FROM agents WHERE id = $1",
        agent_id,
    )
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")

    new_value = not agent["nonce_enabled"]
    await pool.execute("UPDATE agents SET nonce_enabled = $1 WHERE id = $2", new_value, agent["id"])
    await _sync_agent_to_kv(agent["address"], agent["allowed_contact"], new_value, admin_approved=agent["admin_approved"])
    logger.info("Admin toggled nonce for %s: %s", agent["address"], new_value)

    return RedirectResponse(f"/admin/agent/{agent_id}?nonce_toggled=1", status_code=303)


@router.post("/agent/{agent_id}/toggle-channel")
async def admin_toggle_channel(agent_id: str, request: Request):
    await _require_admin(request)
    pool = await get_pool()

    agent = await pool.fetchrow(
        "SELECT id, address, channel_active FROM agents WHERE id = $1",
        agent_id,
    )
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")

    new_value = not agent["channel_active"]
    await pool.execute("UPDATE agents SET channel_active = $1 WHERE id = $2", new_value, agent["id"])
    logger.info("Admin toggled channel for %s: %s", agent["address"], new_value)

    return RedirectResponse(f"/admin/agent/{agent_id}?channel_toggled=1", status_code=303)


@router.post("/agent/{agent_id}/delete")
async def admin_delete_agent(agent_id: str, request: Request):
    await _require_admin(request)
    pool = await get_pool()

    agent = await pool.fetchrow("SELECT id, address FROM agents WHERE id = $1", agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")

    address = agent["address"]

    # Delete in order: nonces, messages, credit_transactions, api_keys, agent
    await pool.execute("DELETE FROM nonces WHERE agent_id = $1", agent["id"])
    await pool.execute("DELETE FROM messages WHERE agent_id = $1", agent["id"])
    await pool.execute("DELETE FROM credit_transactions WHERE agent_id = $1", agent["id"])
    await pool.execute("DELETE FROM api_keys WHERE agent_id = $1", agent["id"])
    await pool.execute("DELETE FROM agents WHERE id = $1", agent["id"])

    # Remove from Cloudflare KV
    await _delete_agent_from_kv(address)

    logger.warning("Admin deleted agent %s", address)
    return RedirectResponse("/admin/?deleted=1", status_code=303)


# --- Owner config ---

@router.get("/owners", response_class=HTMLResponse)
async def admin_owners(request: Request):
    await _require_admin(request)
    pool = await get_pool()

    owners = await pool.fetch("""
        SELECT u.id, u.github_username, u.email,
               COUNT(a.id) as agent_count,
               COALESCE(oc.max_agents, 5) as max_agents,
               u.created_at
        FROM users u
        LEFT JOIN agents a ON a.user_id = u.id
        LEFT JOIN owner_config oc ON oc.user_id = u.id
        GROUP BY u.id, u.github_username, u.email, oc.max_agents, u.created_at
        ORDER BY u.created_at DESC
    """)

    esc = html.escape
    rows = ""
    for o in owners:
        rows += f"""
        <tr>
            <td><a href="/admin/owner/{o['id']}">{esc(o['github_username'])}</a></td>
            <td>{esc(o['email'])}</td>
            <td>{o['agent_count']} / {o['max_agents']}</td>
            <td>{o['created_at'].strftime('%Y-%m-%d') if o['created_at'] else '?'}</td>
        </tr>"""

    flash = ""
    if request.query_params.get("saved"):
        flash = '<div class="flash">Owner config saved.</div>'

    return f"""<!DOCTYPE html>
<html><head><title>Owners - Sixel-Mail Admin</title>{STYLE}</head>
<body>
<h1><a href="/admin/">admin</a> / owners</h1>
{flash}
<table>
    <tr><th>Owner</th><th>Email</th><th>Agents</th><th>Joined</th></tr>
    {rows}
</table>
</body></html>"""


@router.get("/owner/{user_id}", response_class=HTMLResponse)
async def admin_owner_detail(user_id: str, request: Request):
    await _require_admin(request)
    pool = await get_pool()

    user = await pool.fetchrow("SELECT * FROM users WHERE id = $1", user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    config = await pool.fetchrow("SELECT * FROM owner_config WHERE user_id = $1", user_id)
    max_agents = config["max_agents"] if config else 5

    agents = await pool.fetch(
        "SELECT address, credit_balance, last_seen_at, admin_approved FROM agents WHERE user_id = $1 ORDER BY created_at",
        user_id,
    )

    esc = html.escape
    agent_rows = ""
    for a in agents:
        approved = "yes" if a["admin_approved"] else "PENDING"
        agent_rows += f"<tr><td>{esc(a['address'])}@sixel.email</td><td>{a['credit_balance']}</td><td>{approved}</td></tr>"

    return f"""<!DOCTYPE html>
<html><head><title>{esc(user['github_username'])} - Sixel-Mail Admin</title>{STYLE}</head>
<body>
<h1><a href="/admin/">admin</a> / <a href="/admin/owners">owners</a> / {esc(user['github_username'])}</h1>

<h2>Config</h2>
<form method="POST" action="/admin/owner/{user_id}/config" style="display:flex;gap:8px;align-items:center;">
    <label>Max agents: <input type="number" name="max_agents" value="{max_agents}" min="1" max="100"></label>
    <button type="submit">Save</button>
</form>

<h2>Agents ({len(agents)} / {max_agents})</h2>
<table>
    <tr><th>Address</th><th>Credits</th><th>Approved</th></tr>
    {agent_rows}
</table>

</body></html>"""


@router.post("/owner/{user_id}/config")
async def admin_update_owner_config(user_id: str, request: Request):
    await _require_admin(request)
    pool = await get_pool()

    user = await pool.fetchrow("SELECT id FROM users WHERE id = $1", user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    form = await request.form()
    max_agents = int(form.get("max_agents", 5))
    if max_agents < 1 or max_agents > 100:
        raise HTTPException(status_code=400, detail="max_agents must be 1-100")

    await pool.execute("""
        INSERT INTO owner_config (user_id, max_agents, updated_at)
        VALUES ($1, $2, now())
        ON CONFLICT (user_id) DO UPDATE SET max_agents = $2, updated_at = now()
    """, user_id, max_agents)

    logger.info("Admin set max_agents=%d for user %s", max_agents, user_id)
    return RedirectResponse(f"/admin/owners?saved=1", status_code=303)
