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

<h3>When the operator goes dark</h3>

<p>Your agent emails the operator. No reply for hours. What should it do?</p>

<p>Don't assume the operator saw the message. Don't send follow-ups. The agent should
have a fallback mode: continue with non-destructive work it can do without approval,
or gracefully idle (poll the inbox, do nothing else). The worst outcome is an agent
that escalates its own urgency &mdash; sending repeated messages, making assumptions,
or taking actions it was waiting for approval on.</p>

<div class="tip">
<strong>Design for silence.</strong> If you give your agent tasks that require approval
at certain gates, also give it a list of things it <em>can</em> do without approval.
When the operator doesn't respond, the agent works that list instead of stalling or
improvising.
</div>

<h2>Attachments</h2>

<h3>Sending attachments</h3>

<p>Include an <code>attachments</code> array in your <code>POST /v1/send</code> request.
Each attachment is a JSON object with <code>filename</code> and <code>content</code> (base64-encoded).</p>

<pre>{
  "subject": "Analysis results",
  "body": "Here are the results.",
  "attachments": [
    {"filename": "results.csv", "content": "aWQsbmFtZSxzY29yZQ=="}
  ]
}</pre>

<p>Limits: 10MB total decoded size, max 10 files per message.</p>

<h3>Receiving attachments</h3>

<p><code>GET /v1/inbox</code> includes attachment metadata on each message:</p>

<pre>"attachments": [
  {"id": "uuid", "filename": "photo.jpg", "mime_type": "image/jpeg", "size_bytes": 164883}
]</pre>

<p>Download the content with <code>GET /v1/inbox/{message_id}/attachments/{attachment_id}</code>.
Returns raw bytes with the correct <code>Content-Type</code> header.</p>

<h2>Multi-session coordination</h2>

<p>If you run multiple agent sessions (different projects, different specializations),
they can share a single inbox and coordinate responses without a central orchestrator.</p>

<h3>Sixel Teams (reference architecture)</h3>

<p>We published a reference architecture:
<a href="https://github.com/sixel-et/sixel-teams">sixel-et/sixel-teams</a>.
The core pattern is hubless coordination &mdash; a lightweight watcher handles email I/O,
wakes sessions, collects contributions, and sends one assembled reply. No framework,
no shared context window, no LLM calls in the coordination layer.</p>

<p>The reference implementation uses tmux and bash scripts. The <em>architecture</em> is
harness-agnostic &mdash; the same watcher/contributor/assembler pattern works whether your
agent sessions are tmux panes, Docker containers, or framework-managed processes.
Adapt the coordination layer to your stack; the email integration stays the same.</p>

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
    <li><strong>Prompt injection via email:</strong> If someone compromises your email
    account, they could try to send instructions to your agent. Door Knock nonces
    add a barrier &mdash; the attacker must also see the nonce in the auto-reply to
    your inbox &mdash; but if your inbox is compromised, treat the channel as compromised.
    Use the kill switch.</li>
</ul>

<h3>Door Knock nonce authentication</h3>

<p>Door Knock is <strong>opt-in</strong> &mdash; toggle it during signup or on your
<code>/account</code> page. Without it, emails from your allowed contact are accepted
directly. With it enabled:</p>

<p>Every outbound email from your agent includes a <code>Reply-To</code> address with a
single-use nonce: <code>agent+nonce@sixel.email</code>. When you hit reply, the nonce
validates your response automatically. No codes, no apps, no extra steps.</p>

<p>If you want to email your agent without a prior message to reply to (a "knock"),
just send to <code>agent@sixel.email</code>. The agent ignores the content but
auto-replies with a fresh nonce in the Reply-To. Reply to <em>that</em>, and your
message goes through. Three emails, zero friction.</p>

<div class="warn">
<strong>Nonces expire after 30 minutes.</strong> If you don't reply within that window,
the nonce is no longer valid. Send a new knock to get a fresh one.
</div>

<p>This means an attacker with a compromised email account can send a knock, but
the auto-reply goes to <em>your</em> inbox &mdash; they'd need to also compromise
your inbox to see the nonce. If that's happened, you have bigger problems than
agent email.</p>

<h3>Channel kill switch</h3>

<p>Set up a kill switch from <code>/account</code>. You get an allstop email address
that deactivates the channel instantly. Save it as a phone contact &mdash; the setup
page gives you a QR code. If anything goes wrong, send one email to that address
and the channel shuts down. Reactivation requires a live session or the account dashboard.</p>

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

<h3>Reading email bodies without checking for binary</h3>
<p>If your human pastes an image into an email, the body field can contain 200KB+
of base64-encoded image data. An agent that reads or greps this content without
checking can enter a hot loop &mdash; regex engines hit catastrophic backtracking
on binary data, and the session becomes unrecoverable.</p>

<div class="warn">
<strong>Rule: read a small slice first.</strong> Before processing any email body,
check the first few lines. If it looks like base64 or binary data, stop. Use the
attachments endpoint to get file content separately.
</div>

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
<p>Yes. <code>GET /v1/inbox</code> is free. You only pay credits per message sent or
received (1 credit each). Every account starts with 10,000 free credits &mdash; that's
5,000 round-trip conversations. An agent that exchanges 20 messages a day with its
operator uses about 600 credits a month. For most use cases, 10,000 credits
lasts months.</p>

<h3>Can agents send and receive attachments?</h3>
<p>Yes. Up to 10 files per message, 10MB total. Send with base64-encoded content
in the <code>attachments</code> array. Receive metadata in the inbox response,
download via the attachment endpoint. See Attachments section above.</p>

<h3>Do I need Door Knock nonces?</h3>
<p>It's optional. Without it, any email from your allowed contact goes through
directly. With it, replies are validated by a single-use nonce in the Reply-To
address. Toggle it on <code>/account</code>. If you're not worried about email
account compromise, you probably don't need it.</p>

<h3>What if I email the agent from the wrong address?</h3>
<p>Rejected at the edge. No credit deduction, no storage, no notification to
the agent. It's as if the email was never sent.</p>

<h3>How is this different from just using Gmail?</h3>
<p>Gmail doesn't give your agent an API. You'd need to set up OAuth, parse MIME yourself,
build a polling loop around IMAP, and handle authentication refresh. sixel.email is
5 lines of config: one endpoint to send, one to receive, one API key. The inbox poll
doubles as a heartbeat &mdash; if your agent stops checking, you get notified. And the
one-allowed-contact model means your agent can't be tricked into emailing anyone else.</p>

<h3>How is this different from other agent email services?</h3>
<p>Most agent email services give you a general-purpose email API. sixel.email is
opinionated: one agent, one contact, prepaid credits, no subscription. The leash
(one allowed contact) is the product, not a limitation. If you need an agent that
emails arbitrary recipients, this isn't the right tool. If you want a controlled
channel between your agent and you, it is.</p>

<h2>Support</h2>
<p>Questions, bugs, feedback: <strong><a href="mailto:support@sixel.email">support@sixel.email</a></strong>.
That's a real inbox monitored by a human.</p>

<div class="footer">
    <p><a href="/">sixel.email</a> &mdash;
    Built by <a href="https://github.com/sixel-et">sixel-et</a> &mdash;
    <a href="mailto:support@sixel.email">support@sixel.email</a></p>
</div>

</body></html>"""
