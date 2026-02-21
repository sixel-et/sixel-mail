import html
import logging

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from app.db import get_pool
from app.routes.signup import get_user_id
from app.services.credits import add_credits

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/admin")

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
               a.agent_down_notified, a.nonce_enabled, a.created_at,
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
        agent_rows += f"""
        <tr>
            <td><a href="/admin/agent/{a['id']}">{addr}@sixel.email</a></td>
            <td>{esc(a['github_username'])}</td>
            <td>{a['credit_balance']}</td>
            <td><span style="color:{status_color}">{status}</span></td>
            <td>{a['msg_count']} ({a['unread_count']} unread)</td>
            <td>{nonce}</td>
        </tr>"""

    flash = ""
    if request.query_params.get("credited"):
        flash = '<div class="flash">Credits added successfully.</div>'

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

<h2>All agents</h2>
<table>
    <tr><th>Address</th><th>Owner</th><th>Credits</th><th>Last seen</th><th>Messages</th><th>Nonce</th></tr>
    {agent_rows}
</table>

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

    # Messages (last 50)
    messages = await pool.fetch("""
        SELECT id, direction, subject, body, is_read, encrypted, created_at
        FROM messages WHERE agent_id = $1
        ORDER BY created_at DESC LIMIT 50
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
        msg_rows += f"""
        <tr>
            <td>{time_str}</td>
            <td>{arrow}{read_mark}</td>
            <td>{subj}</td>
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
    nonce_str = "enabled" if agent.get("nonce_enabled") else "disabled"
    created_str = agent["created_at"].strftime("%Y-%m-%d %H:%M")

    flash = ""
    if request.query_params.get("credited"):
        flash = '<div class="flash">Credits added successfully.</div>'

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
    <tr><td><strong>API key</strong></td><td>{key_info}</td></tr>
    <tr><td><strong>Created</strong></td><td>{created_str}</td></tr>
</table>

<h3>Add credits</h3>
<form method="POST" action="/admin/credits" style="display:flex;gap:8px;align-items:center;">
    <input type="hidden" name="agent_id" value="{agent_id}">
    <input type="number" name="amount" value="100" min="1" max="10000">
    <input type="text" name="reason" value="admin_grant" style="font-family:monospace;font-size:14px;padding:6px;width:150px;">
    <button type="submit">Add credits</button>
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
