from fastapi import APIRouter
from fastapi.responses import HTMLResponse

router = APIRouter()


@router.get("/", response_class=HTMLResponse)
async def landing():
    return """<!DOCTYPE html>
<html><head>
<title>sixel.email — an email address for your AI agent</title>
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
    h2 { font-size: 16px; margin-top: 32px; }
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
    .warning { background: #fff3cd; border: 1px solid #ffc107; padding: 16px; margin: 24px 0; font-size: 13px; line-height: 1.6; }
    .warning ul { margin: 8px 0; padding-left: 20px; }
    .footer { margin-top: 48px; color: #999; font-size: 13px; }
    .footer a { color: #666; }
    .badge {
        float: right;
        transform: rotate(-8deg);
        background: #1a1a1a;
        color: #fff;
        padding: 10px 14px;
        font-size: 11px;
        line-height: 1.6;
        text-align: center;
        font-weight: bold;
        border-radius: 3px;
        box-shadow: 2px 3px 8px rgba(0,0,0,0.2);
        white-space: nowrap;
        margin: -10px 0 10px 20px;
    }
    .badge .label { color: #999; font-weight: normal; }
</style>
</head>
<body>

<h1>sixel.email</h1>
<p class="tagline">An email address for your AI agent, with a leash.</p>

<p>Your agent gets an email address. It can only email you, and only you can email it.
If it stops responding, you get an email. The whole UI is your inbox.</p>

<h2>How it works</h2>
<ol class="how-it-works">
    <li>Sign up. Pick an agent address.</li>
    <li>Set the one email it's allowed to talk to (yours).</li>
    <li>Get an API key. 10,000 free messages.</li>
    <li>Paste 5 lines into your agent config. Done.</li>
</ol>

<div class="badge">
    <span class="label">works with!</span><br>
    OpenClaw!<br>
    Claude Code!<br>
    <span class="label">anything with</span> curl!
</div>

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

<p class="free">Free. Polling is free. No subscription.
<a href="/donate" style="color:#666;">Donations welcome.</a></p>

<a href="/auth/github" class="cta">Sign up / Log in with GitHub</a>

<div class="warning">
    <strong>Good to know:</strong>
    <ul>
        <li>This is a small, independent service. We ship fast and fix fast. If something
            breaks, <a href="mailto:support@sixel.email">let us know</a>.</li>
        <li>Email is transmitted in plaintext. For sensitive communications,
            <strong>use PGP encryption</strong> (e.g., <a href="https://flowcrypt.com">FlowCrypt</a>
            for Gmail, or GPG for command-line agents).</li>
        <li>We store your messages to deliver them. We don't read them, but we could.
            PGP is the only way to prevent this.</li>
        <li>No warranty. Back up anything important.</li>
    </ul>
</div>

<div class="footer">
    <p><a href="/best-practices">Best practices</a> &mdash;
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
