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
    .price { color: #666; font-size: 14px; }
    .footer { margin-top: 48px; color: #999; font-size: 13px; }
    .footer a { color: #666; }
</style>
</head>
<body>

<h1>sixel.email</h1>
<p class="tagline">An email address for your AI agent, with a leash.</p>

<p>Your agent gets an email address. It can only email you.
If it stops responding, you get an email. The whole UI is your inbox.</p>

<h2>How it works</h2>
<ol class="how-it-works">
    <li>Sign up. Pick an agent address.</li>
    <li>Set the one email it's allowed to talk to (yours).</li>
    <li>Add $5 credit. Get an API key.</li>
    <li>Paste 5 lines into your agent config. Done.</li>
</ol>

<h2>The agent integration</h2>
<pre>You have an email address for contacting me when you're stuck.
API: https://api.sixel.email/v1
Token: sm_live_xxxxx
Use POST /v1/send to email me. Use GET /v1/inbox to check for my reply.
Poll /v1/inbox every 60 seconds while waiting.</pre>

<h2>The API</h2>
<pre>POST  /v1/send        Send an email (to the allowed address)
GET   /v1/inbox        Poll for new messages (also the heartbeat)
GET   /v1/inbox/:id    Get a specific message
POST  /v1/rotate-key   Rotate the API key</pre>

<p class="price">$0.01 per message. Polling is free. No subscription.</p>

<a href="/auth/github" class="cta">Sign up / Log in with GitHub</a>

<div class="footer">
    <p>Built by <a href="https://github.com/sixel-et">sixel-et</a></p>
</div>

</body></html>"""
