from fastapi import APIRouter
from fastapi.responses import HTMLResponse

router = APIRouter()


@router.get("/best-practices", response_class=HTMLResponse)
async def best_practices():
    return """<!DOCTYPE html>
<html><head>
<title>Best Practices — sixel.email</title>
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
    h2 { font-size: 16px; margin-top: 40px; border-bottom: 1px solid #ddd; padding-bottom: 4px; }
    h3 { font-size: 14px; margin-top: 28px; color: #333; }
    pre {
        background: #f5f5f5;
        padding: 16px;
        overflow-x: auto;
        font-size: 13px;
        line-height: 1.5;
    }
    code {
        background: #f5f5f5;
        padding: 2px 5px;
        font-size: 13px;
    }
    .tip {
        border-left: 3px solid #1a1a1a;
        padding-left: 16px;
        margin: 16px 0;
        color: #444;
    }
    .warn {
        border-left: 3px solid #c44;
        padding-left: 16px;
        margin: 16px 0;
        color: #444;
    }
    .footer { margin-top: 48px; color: #999; font-size: 13px; }
    .footer a { color: #666; }
    a { color: #1a1a1a; }
</style>
</head>
<body>

<h1><a href="/" style="text-decoration: none; color: inherit;">sixel.email</a></h1>
<p class="tagline">Best practices for agent email integration.</p>

<h2>The basics</h2>

<h3>Give your agent minimal instructions</h3>

<p>The entire integration is 5 lines in your agent's system prompt or config:</p>

<pre>You have an email address for contacting your operator.
API: https://sixel.email/v1
Token: sm_live_xxxxx
POST /v1/send to email. GET /v1/inbox to check for replies.
Poll /v1/inbox every 60s while waiting.</pre>

<p>That's it. Don't over-specify. The agent figures out when to email (stuck, needs
approval, has results) and what to say. You're adding a capability, not a workflow.</p>

<h3>Use the inbox poll as the heartbeat</h3>

<p>Every <code>GET /v1/inbox</code> call updates your agent's heartbeat.
If the agent stops polling, you get a notification email. This means you don't
need a separate health check &mdash; inbox polling <em>is</em> the health check.</p>

<div class="tip">
<strong>Recommended interval: 60 seconds.</strong> Fast enough to catch replies promptly.
Slow enough to not waste resources. The poll is free &mdash; only sends and receives cost credits.
</div>

<h3>One allowed contact</h3>

<p>Each agent can only email one address: the one you set during setup. This is
the leash. Your agent can't be tricked into emailing anyone else, and it can't
be spammed by strangers. Inbound email from any other sender is rejected at the
edge before it touches the API.</p>

<h2>Sleep/wake patterns</h2>

<h3>The agent doesn't need to stay busy</h3>

<p>The most useful pattern: agent does work, emails you when done or stuck,
then polls <code>/v1/inbox</code> in a loop until you reply. The agent is "asleep" &mdash;
consuming no inference, just one HTTP GET per minute.</p>

<pre># Pseudocode: sleep until reply
send_email("Finished the analysis. Results attached. What next?")
while True:
    response = poll_inbox()
    if response.messages:
        handle(response.messages[0])
        break
    sleep(60)</pre>

<p>This turns a synchronous back-and-forth into an async conversation.
You reply when you're ready &mdash; hours later, next morning, whenever.
The agent wakes up and continues.</p>

<h3>Surviving context loss</h3>

<p>Long-running agents will hit context limits. When the context compresses
or the session restarts, the agent loses awareness of what it was waiting for.
Two mitigations:</p>

<ol>
    <li><strong>Write state to disk before sleeping.</strong> What are you waiting for?
    What was the last thing you sent? Save it in a file the agent reads on startup.</li>
    <li><strong>Check inbox on restart.</strong> If there's an unread message, the reply
    already arrived while you were down. Handle it before doing anything else.</li>
</ol>

<h2>Multi-session coordination</h2>

<p>This is where it gets interesting. If you run multiple agent sessions
(different projects, different specializations), they can share an inbox.</p>

<h3>The pattern: hubless teams</h3>

<p>Instead of one agent handling email, run a lightweight watcher script alongside
your sessions. The watcher is pure bash &mdash; no inference, no LLM calls:</p>

<ol>
    <li><strong>Watcher</strong> polls the inbox, stores new emails as files on disk</li>
    <li><strong>Watchdog</strong> detects which sessions are idle, wakes them via terminal injection</li>
    <li>Each session reads the email, decides whether to <strong>contribute</strong> or <strong>pass</strong></li>
    <li>Sessions write their response as a JSON file in a shared directory</li>
    <li>Watcher waits for contributions (configurable delay), assembles them, sends one reply</li>
</ol>

<p>No session is the "lead." Any session can contribute. The watcher handles I/O.
The result is an agent team with no central orchestrator, no custom framework,
and no shared context window.</p>

<pre># On-disk structure for each inbound email
state/outbound/&lt;email-id&gt;/
  email.json              # the inbound email
  status.json             # delivery tracking
  responses/
    session-1.json        # { type: "contribution", content: "..." }
    session-2.json        # { type: "pass" }</pre>

<h3>Wake-up via terminal injection</h3>

<p>If your sessions run in tmux (standard for Claude Code, common for other agents),
the watchdog can wake them by injecting text into the terminal:</p>

<pre>tmux send-keys -t session-name "New email: subject here" -l
tmux send-keys -t session-name Enter</pre>

<p>The session sees this as user input and responds. No custom API, no webhooks,
no framework integration. Just text in a terminal.</p>

<div class="tip">
<strong>Key detail:</strong> Send the message text with <code>-l</code> (literal mode) and
<code>Enter</code> as a separate keystroke. Long strings with embedded newlines don't
register reliably in tmux.
</div>

<h3>Peer-to-peer between sessions</h3>

<p>Sessions can also talk directly to each other, independent of email. Messages are
JSON files in a git-tracked directory. Delivery is: write file, commit, push, ring
the recipient's doorbell via tmux. Git gives you persistence, sync across machines,
and a full audit trail readable by the human operator.</p>

<h2>Security</h2>

<h3>The threat model</h3>

<p>The leash (one allowed contact) means the agent can't be weaponized for spam
or social engineering. But the inbound side needs protection too &mdash; can someone
send your agent a malicious email?</p>

<ul>
    <li><strong>Spoofing:</strong> Cloudflare Email Routing enforces DMARC at the SMTP level.
    Spoofed senders are rejected before the email reaches the API. We publish
    <code>p=reject</code> DMARC policy.</li>
    <li><strong>Unknown senders:</strong> The allowed-contact check happens at the edge
    (Cloudflare Worker). Email from anyone other than your allowed contact is rejected
    with no processing, no storage, no credit deduction.</li>
    <li><strong>Prompt injection via email:</strong> This is the real risk. If someone
    compromises your email account, they can send instructions to your agent. The
    allowed-contact check can't help here &mdash; the sender looks legitimate.</li>
</ul>

<h3>TOTP encryption (optional)</h3>

<p>For defense against compromised-account attacks, agents can enable TOTP encryption.
When enabled:</p>

<ol>
    <li>You include a 6-digit TOTP code on the first line of your email</li>
    <li>Your message is encrypted before it enters the system</li>
    <li>Your agent decrypts locally using the shared TOTP secret</li>
    <li>Emails without a valid code are rejected before reaching the agent</li>
</ol>

<p>This means a compromised email account can't send instructions to your agent
unless the attacker also has your TOTP secret.</p>

<div class="warn">
<strong>Important:</strong> Only enable TOTP after your agent's code can handle decryption.
If TOTP is enabled but your agent reads the inbox raw, it will receive ciphertext.
</div>

<h2>Common mistakes</h2>

<h3>Polling too fast</h3>
<p>The API rate-limits inbox polls. 60 seconds is the sweet spot. Polling every
second doesn't get you replies faster &mdash; it gets you rate-limited.</p>

<h3>Not seeding the seen-ID list</h3>
<p>If your agent restarts and re-reads the inbox, it will see messages it already
handled (the inbox marks messages as read on fetch, but network issues can cause
re-delivery). Keep a local list of message IDs you've processed. Check it before
acting on any message.</p>

<h3>Sending without a subject</h3>
<p>Subjects aren't required by the API, but your email client will bury subjectless
messages. Always include a subject &mdash; your future self will thank you when scanning
a long thread.</p>

<h3>Ignoring the credit balance</h3>
<p>Every <code>/v1/inbox</code> response includes <code>credits_remaining</code>.
If your agent notices credits getting low, it should tell you. Don't let it discover
it's out of credits when it has something important to say.</p>

<h3>Treating email like chat</h3>
<p>Email is async. Your agent should send one well-composed message, then wait.
Don't send five messages in a row. Don't poll for 10 seconds and then send a
follow-up asking if you got the first one.</p>

<h2>FAQ</h2>

<h3>Can the agent email anyone?</h3>
<p>No. Only the one allowed contact you set during setup. This is by design.</p>

<h3>Can I change the allowed contact?</h3>
<p>Not yet. Contact support. This will be self-service soon.</p>

<h3>What happens if my agent goes down?</h3>
<p>If the agent stops polling <code>/v1/inbox</code>, you'll get a notification email
after a configurable timeout. When the agent comes back and resumes polling,
you'll get a recovery notification.</p>

<h3>Can multiple agents share an address?</h3>
<p>One address = one agent = one API key. But multiple sessions can share the same
API key and coordinate responses (see Multi-session coordination above).</p>

<h3>Is polling really free?</h3>
<p>Yes. <code>GET /v1/inbox</code> is free. You only pay $0.01 per message sent or
received. Polling once per minute for a month is zero cost.</p>

<h3>What if I email the agent from the wrong address?</h3>
<p>Rejected at the edge. No credit deduction, no storage, no notification to
the agent. It's as if the email was never sent.</p>

<div class="footer">
    <p><a href="/">sixel.email</a> &mdash;
    Built by <a href="https://github.com/sixel-et">sixel-et</a> &mdash;
    <a href="mailto:support@sixel.email">support@sixel.email</a></p>
</div>

</body></html>"""
