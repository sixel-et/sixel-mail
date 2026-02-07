import html

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from app.db import get_pool
from app.routes.signup import get_user_id

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

        # Get API key prefix
        key_row = await pool.fetchrow(
            "SELECT key_prefix FROM api_keys WHERE agent_id = $1 ORDER BY created_at DESC LIMIT 1",
            agent["id"],
        )
        key_display = f"{esc(key_row['key_prefix'])}..." if key_row else "none"

        # Recent messages
        messages = await pool.fetch(
            """
            SELECT direction, subject, created_at FROM messages
            WHERE agent_id = $1 ORDER BY created_at DESC LIMIT 10
            """,
            agent["id"],
        )
        msg_lines = ""
        for msg in messages:
            arrow = "→" if msg["direction"] == "outbound" else "←"
            time_str = msg["created_at"].strftime("%I:%M%p")
            subj = esc(msg["subject"] or "(no subject)")
            msg_lines += f'    {arrow} "{subj}" ({time_str})<br>\n'

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

        agent_sections += f"""
<div style="border: 1px solid #ccc; padding: 16px; margin: 16px 0;">
    <h3>{address}@sixel.email</h3>
    <p>Status: {status} (last seen: {last_seen_str})</p>
    <p>Allowed contact: {esc(agent['allowed_contact'])}</p>
    <p>Credits: {agent['credit_balance']} messages</p>
    <p>API key: <code>{key_display}</code></p>
    <p><strong>Recent messages:</strong></p>
    <div style="font-size: 14px;">{msg_lines if msg_lines else "    No messages yet"}</div>
    <br>
    <a href="/topup?agent_id={agent_id}"><button>Add credit</button></a>
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
