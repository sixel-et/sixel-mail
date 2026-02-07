from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, HTTPException
from fastapi.responses import HTMLResponse

from app.db import get_pool
from app.services.signing import sign_alert_url, verify_signature

router = APIRouter()


@router.get("/alert", response_class=HTMLResponse)
async def handle_alert(agent: str, action: str, expires: str, sig: str):
    if not verify_signature(agent, action, expires, sig):
        return HTMLResponse(
            "<html><body><h1>Link expired or invalid</h1>"
            "<p>This link may have expired. Check your latest email for a fresh link.</p>"
            "</body></html>",
            status_code=400,
        )

    pool = await get_pool()
    agent_row = await pool.fetchrow(
        "SELECT id, address, alert_status, last_seen_at FROM agents WHERE id = $1",
        agent,
    )
    if not agent_row:
        raise HTTPException(status_code=404, detail="Agent not found")

    now = datetime.now(timezone.utc)

    if action == "on":
        await pool.execute(
            "UPDATE agents SET alert_status = 'active', alert_mute_until = NULL WHERE id = $1",
            agent,
        )
        status_msg = "Alerts are ON"
    elif action == "pause1h":
        until = now + timedelta(hours=1)
        await pool.execute(
            "UPDATE agents SET alert_status = 'paused', alert_mute_until = $2 WHERE id = $1",
            agent, until,
        )
        status_msg = "Alerts paused for 1 hour"
    elif action == "pause8h":
        until = now + timedelta(hours=8)
        await pool.execute(
            "UPDATE agents SET alert_status = 'paused', alert_mute_until = $2 WHERE id = $1",
            agent, until,
        )
        status_msg = "Alerts paused for 8 hours"
    elif action == "mute":
        tomorrow_8am = (now + timedelta(days=1)).replace(hour=8, minute=0, second=0)
        await pool.execute(
            "UPDATE agents SET alert_status = 'muted', alert_mute_until = $2 WHERE id = $1",
            agent, tomorrow_8am,
        )
        status_msg = "Alerts muted until tomorrow 8am"
    else:
        raise HTTPException(status_code=400, detail="Unknown action")

    # Build confirmation page with action links
    address = agent_row["address"]
    last_seen = agent_row["last_seen_at"]
    last_seen_str = last_seen.strftime("%I:%M%p %Z") if last_seen else "never"

    on_url = sign_alert_url(agent, "on")
    p1_url = sign_alert_url(agent, "pause1h")
    p8_url = sign_alert_url(agent, "pause8h")
    mute_url = sign_alert_url(agent, "mute")

    return f"""<!DOCTYPE html>
<html><head><title>Sixel-Mail Alert Control</title>
<style>
    body {{ font-family: monospace; max-width: 500px; margin: 40px auto; padding: 0 20px; text-align: center; }}
    a {{ display: inline-block; margin: 4px; padding: 8px 16px; background: #eee; text-decoration: none; color: #000; }}
    a:hover {{ background: #ddd; }}
</style></head>
<body>
<h2>{status_msg} for {address}</h2>
<p>Last seen: {last_seen_str}</p>
<br>
<a href="{on_url}">Turn alerts ON</a>
<a href="{p1_url}">Pause 1hr</a>
<a href="{p8_url}">Pause 8hr</a>
<a href="{mute_url}">Mute until tomorrow</a>
</body></html>"""
