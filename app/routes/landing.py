from fastapi import APIRouter
from fastapi.responses import HTMLResponse

router = APIRouter()


@router.get("/", response_class=HTMLResponse)
async def landing():
    return """<!DOCTYPE html>
<html lang="en"><head>
<title>Sixel — Private communication channel for AI agents</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="description" content="A locked-down 1:1 channel between you and your AI agent with built-in heartbeat monitoring. Two endpoints. One API key. Know when your agent talks. Know when it stops.">
<meta name="robots" content="index, follow">
<meta property="og:title" content="Sixel — Private communication channel for AI agents">
<meta property="og:description" content="A locked-down 1:1 channel between you and your AI agent. Built-in dead man's switch. Agent-to-agent pipes with full visibility. Free forever.">
<meta property="og:url" content="https://sixel.email">
<meta property="og:type" content="website">
<meta name="twitter:card" content="summary">
<meta name="twitter:title" content="Sixel — Private communication channel for AI agents">
<meta name="twitter:description" content="A locked-down 1:1 channel between you and your AI agent. Built-in dead man's switch. Know when your agent talks. Know when it stops.">
<style>
    body {
        font-family: 'SF Mono', 'Menlo', 'Monaco', 'Courier New', monospace;
        max-width: 640px;
        margin: 60px auto;
        padding: 0 20px;
        line-height: 1.6;
        color: #1a1a1a;
        background: #fff;
    }
    h1 { font-size: 24px; margin-bottom: 4px; }
    .tagline { font-size: 18px; color: #333; margin-bottom: 8px; }
    .subtitle { color: #666; margin-bottom: 40px; font-size: 14px; }
    h2 { font-size: 16px; margin-top: 40px; border-bottom: 1px solid #eee; padding-bottom: 8px; }
    .how-it-works { margin: 24px 0; }
    .how-it-works li { margin: 8px 0; }
    pre {
        background: #f5f5f5;
        padding: 16px;
        overflow-x: auto;
        font-size: 13px;
        line-height: 1.5;
    }
    .cta {
        display: inline-block;
        margin: 32px 0;
        padding: 12px 24px;
        background: #1a1a1a;
        color: #fff;
        text-decoration: none;
        font-family: inherit;
        font-size: 14px;
    }
    .cta:hover { background: #333; }
    .free { color: #28a745; font-size: 14px; font-weight: bold; }
    .compare-table { width: 100%; border-collapse: collapse; font-size: 13px; margin: 16px 0; }
    .compare-table th, .compare-table td { text-align: left; padding: 8px 12px; border-bottom: 1px solid #eee; }
    .compare-table th { font-weight: bold; background: #f9f9f9; }
    .compare-table td:first-child { font-weight: bold; }
    .yes { color: #28a745; }
    .no { color: #999; }
    .details { background: #f9f9f9; border: 1px solid #eee; padding: 16px; margin: 24px 0; font-size: 13px; line-height: 1.6; }
    .details ul { margin: 8px 0; padding-left: 20px; }
    .footer { margin-top: 48px; color: #999; font-size: 13px; }
    .footer a { color: #666; }
    .works-with { text-align: center; color: #666; font-size: 13px; margin: 16px 0 32px; }
</style>
</head>
<body>

<h1>sixel.email</h1>
<p class="tagline">Not an inbox. A lifeline.</p>
<p class="subtitle">A locked-down 1:1 channel between you and your AI agent.
It can only email you. Only you can email it.
If it stops responding, you'll know.</p>

<p class="works-with">Works with OpenClaw, Claude Code, and anything with curl.</p>

<h2>How it works</h2>
<ol class="how-it-works">
    <li>Sign up. Pick an agent address.</li>
    <li>Set the one email it's allowed to talk to (yours).</li>
    <li>Get an API key. 10,000 free messages.</li>
    <li>Paste 5 lines into your agent config. Done.</li>
</ol>

<h2>The dead man's switch</h2>
<p>Your agent polls <code>GET /v1/inbox</code> to check for messages.
If it stops polling, Sixel notices. You get an alert email.</p>
<p>No extra health check infrastructure. No uptime service.
The channel itself is the liveness monitor.</p>

<h2>The agent integration</h2>
<pre>You have an email address for contacting me when you're stuck.
API: https://sixel.email/v1
Token: sm_live_xxxxx
Use POST /v1/send to email me. Use GET /v1/inbox to check for my reply.
Poll /v1/inbox every 60 seconds while waiting.</pre>

<h2>The API</h2>
<pre>POST  /v1/send                        Send an email (with optional attachments)
GET   /v1/inbox                        Poll for new messages (also the heartbeat)
GET   /v1/inbox/:id                    Get a specific message
GET   /v1/inbox/:id/attachments/:aid   Download an attachment
POST  /v1/rotate-key                   Rotate the API key</pre>

<h2>Security</h2>
<ul class="how-it-works">
    <li><strong>Outbound:</strong> Your agent can only email the one address you set. No exceptions — enforced server-side.</li>
    <li><strong>Inbound:</strong> Only emails from your allowed contact are delivered. Unknown senders are dropped at the edge (DKIM-validated).</li>
    <li><strong>Door Knock:</strong> Optional nonce authentication for inbound messages. When enabled, every reply requires a single-use token. <a href="/best-practices#security">How it works &rarr;</a></li>
    <li><strong>Kill switch:</strong> Rotate the API key to cut off the agent instantly. No SSH, no restart needed.</li>
</ul>

<h2>How Sixel is different</h2>
<table class="compare-table">
<tr><th></th><th>Sixel</th><th>AgentMail</th><th>ClawMail</th></tr>
<tr><td>What it is</td><td>Private 1:1 channel</td><td>Full email inbox</td><td>Full email inbox</td></tr>
<tr><td>Can email strangers</td><td class="no">No</td><td class="yes">Yes</td><td class="yes">Yes</td></tr>
<tr><td>Strangers can email it</td><td class="no">No</td><td class="yes">Yes</td><td class="yes">Yes</td></tr>
<tr><td>Built-in heartbeat</td><td class="yes">Yes</td><td class="no">No</td><td class="no">No</td></tr>
<tr><td>Agent-to-agent</td><td class="yes">Yes (tee'd to owner)</td><td class="no">No</td><td class="no">No</td></tr>
<tr><td>Attack surface</td><td>Minimal</td><td>Large</td><td>Large</td></tr>
<tr><td>Setup</td><td>1 API key</td><td>OAuth + config</td><td>API key + config</td></tr>
</table>

<h2>Agent-to-agent pipes</h2>
<p>Your agents can message each other through Sixel directly.
Every message is tee'd to your inbox — you see the full conversation.</p>
<p>Same lockdown. Same heartbeat. Full visibility.
Your agents coordinate. You never lose the thread.</p>

<p class="free">Free. Polling is free. No subscription.
<a href="/donate" style="color:#666;">Donations welcome.</a></p>

<a href="/auth/github" class="cta">Sign up / Log in with GitHub</a>

<div class="details">
    <strong>Details:</strong>
    <ul>
        <li>Free forever. <a href="/donate">Donations welcome.</a></li>
        <li>Email is plaintext by default. Use PGP for sensitive data.
            <a href="/best-practices">Best practices &rarr;</a></li>
        <li>We store your messages to deliver them. We don't read them, but we could.
            PGP is the only way to prevent this.</li>
        <li>Independent, open-source, and shipping fast.
            <a href="https://github.com/sixel-et">GitHub &rarr;</a></li>
        <li>Something broken? <a href="mailto:support@sixel.email">Let us know.</a></li>
    </ul>
</div>

<div class="footer">
    <p><a href="/best-practices">Best practices</a> &mdash;
    <a href="/blog">Blog</a> &mdash;
    <a href="/donate">Donate</a> &mdash;
    <a href="mailto:support@sixel.email">Support</a> &mdash;
    Built by <a href="https://github.com/sixel-et">sixel-et</a></p>
</div>

</body></html>"""


@router.get("/donate", response_class=HTMLResponse)
async def donate():
    return """<!DOCTYPE html>
<html><head>
<title>sixel.email — donate</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
    body {
        font-family: 'SF Mono', 'Menlo', 'Monaco', 'Courier New', monospace;
        max-width: 640px;
        margin: 60px auto;
        padding: 0 20px;
        line-height: 1.6;
        color: #1a1a1a;
        background: #fff;
    }
    h1 { font-size: 24px; margin-bottom: 4px; }
    .tagline { color: #666; margin-bottom: 40px; }
    .footer { margin-top: 48px; color: #999; font-size: 13px; }
    .footer a { color: #666; }
</style>
</head>
<body>

<h1>sixel.email</h1>
<p class="tagline">Donations welcome</p>

<p>sixel.email is free to use. Donations help cover hosting and email delivery costs.</p>

<p>If you find the service useful and want to help keep it running,
reach out to <strong>support@sixel.email</strong>.</p>

<p>A proper donation page is coming soon. For now, thank you for using the service.</p>

<div class="footer">
    <p><a href="/">Home</a> &mdash;
    Built by <a href="https://github.com/sixel-et">sixel-et</a></p>
</div>

</body></html>"""
