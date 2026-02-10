# Sixel-Mail: Project Plan

---

# Part 1: Product

## One-liner

An email address for your AI agent, with a leash.

## The Problem

AI agents (Claude Code, Devin, Cursor background agents, custom pipelines) run for hours. They get stuck. Right now, they either block silently or you babysit them. There's no simple, universal way for an agent to say "hey, I need you" and for you to reply on your own time.

Email is the obvious channel — it's async, universal, works on every device, survives every outage. But you can't just hand an agent a Gmail account. It'll get phished, it'll spam people, it'll leak context to the wrong person. You need a scoped channel.

## The Product

1. You sign up.
2. You get an agent email address (e.g. `my-agent@sixel.mail`).
3. You set the **one** human email address it's allowed to talk to (yours).
4. You add $5 credit.
5. You get an API key.
6. Your agent sends and receives email through a dead-simple REST API.
7. If your agent goes down, you get an email.
8. You never leave your inbox.

That's it.

## Why Email

- Works on every phone, every laptop, every watch.
- Push notifications are built in. You already have them on.
- You can reply from anywhere — the bus, bed, a meeting.
- Survives Slack outages, webhook misconfigurations, tunnel expiry.
- It's the lowest common denominator. That's the point.

## The Leash

MVP: **one** allowed contact per agent address. Set it during signup. That's the entire access control model. No roles, no rules, no policies.

Emails to/from any address not on the allowlist get silently dropped. The agent can't spam. It can't get socially engineered. It's a sealed tube between your agent and you.

Later: maybe 2-5 allowed contacts. But start with one.

---

## API

```
POST   /v1/send         Send an email (to the allowed address)
GET    /v1/inbox         Poll for new messages (also the heartbeat)
GET    /v1/inbox/:id     Get a specific message
POST   /v1/rotate-key    Rotate the API key
```

Four endpoints. That's the whole API.

### Agent Setup

The entire integration. Paste this into a system prompt, a `.claude` config, or a README:

```
You have an email address for contacting me when you're stuck.
API: https://api.sixel.mail/v1
Token: sm_live_xxxxx
Use POST /v1/send to email me. Use GET /v1/inbox to check for my reply.
Poll /v1/inbox every 60 seconds while waiting.
```

No SDK. No package install. No config file. Any agent that can make an HTTP request can use it.

### Send

```bash
curl -X POST https://api.sixel.mail/v1/send \
  -H "Authorization: Bearer sm_live_xxxxx" \
  -H "Content-Type: application/json" \
  -d '{
    "subject": "Stuck on database migration",
    "body": "I hit a permission error on the prod DB. Can you paste the read-only credentials?"
  }'
```

You don't specify a recipient. There's only one. It's already configured.

```json
// Response 200
{
  "id": "msg_abc123",
  "status": "sent",
  "credits_remaining": 412
}

// Response 402
{
  "error": "insufficient_credits",
  "credits_remaining": 0,
  "topup_url": "https://sixel.mail/topup/agent_xyz"
}
```

### Poll (and Heartbeat)

```bash
curl https://api.sixel.mail/v1/inbox \
  -H "Authorization: Bearer sm_live_xxxxx"
```

Returns unread replies from the allowed human. **Also the heartbeat** — every poll updates `last_seen_at`.

```json
// Response 200
{
  "messages": [
    {
      "id": "msg_def456",
      "subject": "Re: Stuck on database migration",
      "body": "Here are the creds: ...",
      "received_at": "2025-02-05T14:32:00Z"
    }
  ],
  "credits_remaining": 411,
  "agent_status": "alive"
}
```

### Agent Loop

```python
send("I'm stuck on X, what should I do?")
while True:
    reply = poll()
    if reply:
        break
    sleep(60)
```

### Rotate Key

```json
// Response 200
{
  "api_key": "sm_live_new_key_here...",
  "message": "Old key has been invalidated. Store this key — it won't be shown again."
}
```

---

## The Heartbeat

The poll *is* the heartbeat. When the agent polls `/v1/inbox`, the server records "last seen: now." If the agent stops polling:

- **5 minutes of silence** (configurable) → server emails the human: *"Your agent stopped responding at 2:34pm EST."*
- **Agent comes back** → server emails: *"Your agent is back online."*

The human's email client is the monitoring dashboard. These are billable messages at a penny each.

---

## Email Format

All emails are **plain text only.** No HTML. URLs in plain text are automatically clickable in every major email client.

### Agent → Human Message

```
Subject: [my-agent] Stuck on database migration

Hey, I'm running the migration script for the users table
and hitting a permission error:

  ERROR: permission denied for schema public

I think I need the read-write credentials for the staging
database. Can you paste them in your reply?

---
Agent alive (last seen: just now)
Credits: 412 messages remaining

Turn alerts ON: https://api.sixel.mail/alert?a=on&agent=xxx&sig=yyy
Pause 1hr: https://api.sixel.mail/alert?a=pause1h&agent=xxx&sig=yyy
Pause 8hr: https://api.sixel.mail/alert?a=pause8h&agent=xxx&sig=yyy
Mute until tomorrow: https://api.sixel.mail/alert?a=mute&agent=xxx&sig=yyy

Add $5 credit: https://sixel.mail/topup?agent=xxx&amount=5&sig=yyy
```

### Agent Down Alert

```
Subject: [my-agent] stopped responding

Your agent my-agent@sixel.mail hasn't checked in since
2:34pm EST (5 minutes ago).

---
Agent OFFLINE (last seen: 2:34pm EST)
Credits: 412 messages remaining

Turn alerts ON: https://api.sixel.mail/alert?a=on&agent=xxx&sig=yyy
Pause 1hr: https://api.sixel.mail/alert?a=pause1h&agent=xxx&sig=yyy
Pause 8hr: https://api.sixel.mail/alert?a=pause8h&agent=xxx&sig=yyy
Mute until tomorrow: https://api.sixel.mail/alert?a=mute&agent=xxx&sig=yyy

Add $5 credit: https://sixel.mail/topup?agent=xxx&amount=5&sig=yyy
```

### Agent Back Online

```
Subject: [my-agent] is back online

Your agent my-agent@sixel.mail is responding again.
It was offline for 23 minutes.

---
Agent alive (last seen: just now)
Credits: 410 messages remaining

Turn alerts ON: https://api.sixel.mail/alert?a=on&agent=xxx&sig=yyy
Pause 1hr: https://api.sixel.mail/alert?a=pause1h&agent=xxx&sig=yyy
Pause 8hr: https://api.sixel.mail/alert?a=pause8h&agent=xxx&sig=yyy
Mute until tomorrow: https://api.sixel.mail/alert?a=mute&agent=xxx&sig=yyy

Add $5 credit: https://sixel.mail/topup?agent=xxx&amount=5&sig=yyy
```

### Low Balance Warning

```
Subject: [my-agent] 47 messages remaining

Your agent my-agent@sixel.mail is running low on credits.

Add $5 credit: https://sixel.mail/topup?agent=xxx&amount=5&sig=yyy
Add $10 credit: https://sixel.mail/topup?agent=xxx&amount=10&sig=yyy

---
Agent alive (last seen: just now)
Credits: 47 messages remaining

Turn alerts ON: https://api.sixel.mail/alert?a=on&agent=xxx&sig=yyy
Pause 1hr: https://api.sixel.mail/alert?a=pause1h&agent=xxx&sig=yyy
Pause 8hr: https://api.sixel.mail/alert?a=pause8h&agent=xxx&sig=yyy
Mute until tomorrow: https://api.sixel.mail/alert?a=mute&agent=xxx&sig=yyy
```

### Footer Rules

The footer is **mandatory on every outbound email.** The agent cannot suppress, modify, or inject content into it. It's appended server-side. This is both UX and security.

The "Turn alerts ON" link is always present. If alerts are already on, clicking it is a harmless no-op. This is the universal undo button.

---

## Email-as-UI: Alert Controls

When the human clicks a footer link, their browser opens and the server returns a simple confirmation page:

```
✓ Alerts are ON for my-agent

Your agent was last seen 30 seconds ago.

[Turn alerts ON] [Pause 1hr] [Pause 8hr] [Mute until tomorrow]
```

No login. No form. No confirmation dialog. One click, done, close the tab. The confirmation page includes the same action links so you can fix a mis-click without going back to email.

Links are HMAC-signed URLs:
- Can't forge (requires server's secret key)
- Can't tamper (changing any parameter invalidates the signature)
- Can expire (30-day validity)
- Stateless (server recomputes and compares, no database lookup)

---

## Account Page

One page. Not a dashboard, not a nav bar with sections. One page you visit maybe once a month. Email is the daily interface.

```
sixel.mail — your account

my-agent@sixel.mail
  Status: 🟢 alive (last seen: 12 seconds ago)
  Allowed contact: you@gmail.com [change]
  Credits: 412 messages
  API key: sm_live_a1b2•••• [rotate] [reveal once]
  Alerts: active [pause 1hr] [pause 8hr]

  Recent messages:
    → "Stuck on database migration" (2:34pm)
    ← "Here are the creds..." (2:41pm)
    → "Thanks, migration complete" (2:43pm)

  [Add $5 credit] [Add $10 credit]

+ Create another agent

Billing history:
  Feb 5 — $5.00 (500 messages) — Stripe
  Jan 12 — $5.00 (500 messages) — Stripe
```

Exists for: key rotation, changing allowed contact, checking balance without waiting for email, creating additional agents, message history, billing history.

---

## Pricing

**$0.01 per message (sent or received).**

Includes agent messages, human replies, heartbeat alerts, system notifications. Polling is free.

### Payment: Prepaid Credits

No subscription. No monthly fee. Buy credit, use credit. One payment rail (Stripe Checkout):

| Top-up | Messages | Stripe fee | You keep |
|---|---|---|---|
| $5 | 500 | $0.45 (9%) | $4.55 |
| $10 | 1,000 | $0.59 (6%) | $9.41 |
| $25 | 2,500 | $1.03 (4%) | $23.97 |

Minimum top-up: $5. Funds 500 messages — probably 2-6 months for a typical agent.

Additional payment rails (Square/Cash App Pay, crypto) deferred to post-MVP.

---

## Signup & Onboarding Flow

```
1. Sign up with GitHub
2. Pick agent email name: [________]@sixel.mail
3. Enter your email: [________]
4. TOTP setup (optional but recommended):
   - Browser generates TOTP secret client-side (JavaScript)
   - QR code displayed for authenticator app (Google Authenticator, Authy, etc.)
   - Raw secret displayed for agent config [Copy]
   - Secret NEVER sent to our server — generated and displayed entirely in browser
5. Add $5 credit → Stripe Checkout
6. Here's your API key: sm_live_a1b2c3d4...   [Copy]
7. We sent a test email. Go mark it "not spam."
8. Paste this into your agent:                 [Copy]
   (includes API key + TOTP secret + reference client instructions)
9. That's it. You're done.
```

---

## Competitive Landscape

Nobody does this. Adjacent things:

- **SendGrid / Postmark / SES**: Email infrastructure. No agent identity. No allowlist. No monitoring.
- **Twilio**: SMS possible but complex. No scoped access control.
- **Slack bots**: Requires Slack. Not universal.
- **ntfy.sh / Pushover**: One-way push notifications. Agent can't hear back.
- **Custom SMTP**: Painful. No guardrails. No heartbeat.

---

## What to Skip for MVP

- Additional payment rails (Square/Cash App Pay, crypto)
- Webhooks (outbound push notifications)
- SMTP/IMAP access
- MCP server
- Multiple allowed contacts
- Custom domains
- Attachments (plain text is fine)
- Message threading
- Read receipts
- Auto-refill (manual top-up is fine)
- Any frontend framework (HTML files are fine)

---

# Part 2: Technical Specification

## Stack

| Layer | Choice | Why |
|---|---|---|
| Language | **Python 3.12** | Claude Code is excellent with Python. FastAPI is minimal. |
| Framework | **FastAPI** | Async. Auto-generates OpenAPI docs. No bloat. |
| Database | **Supabase Postgres** | Free tier (500MB). Hosted. No ops. |
| Email outbound | **Resend** | Built on SES infrastructure. Domain verified via DKIM. |
| Email inbound | **Cloudflare Email Routing → Email Worker → webhook** | DMARC enforced at SMTP. Allowed-contact checked at edge. TOTP encryption before forwarding. |
| Edge compute | **Cloudflare Email Workers** | Runs allowed-contact check + TOTP encryption at Cloudflare edge. |
| Hosting | **Fly.io** | Single command deploy. $5/mo. HTTPS built-in. |
| Payments (card) | **Stripe Checkout (one-time)** | Redirect, pay, webhook. No subscription logic. |
| Payments (future) | Square / crypto | Deferred to post-MVP |
| Auth (signup) | **GitHub OAuth** | Developers already have accounts. |
| Auth (API) | **Bearer token** | `sm_live_` prefixed, stored hashed. |
| Auth (email links) | **HMAC-signed URLs** | Stateless verification. No login needed. |
| Background jobs | **FastAPI background task** | Heartbeat checker. No separate worker. |

---

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│                     Human's Inbox                        │
│  (receives agent emails, heartbeat alerts, system msgs)  │
│  (replies go through Cloudflare Email Routing)           │
└─────────┬───────────────────────────────┬───────────────┘
          │ replies                        ▲ sends (plaintext)
          ▼                               │
┌─────────────────────┐         ┌─────────────────────┐
│ Cloudflare Email    │         │  Resend API          │
│ Routing (MX)        │         │  sends from agent@   │
│ Enforces DMARC      │         └─────────▲───────────┘
└─────────┬───────────┘                   │ httpx
          │                               │
          ▼                               │
┌─────────────────────┐                   │
│ Cloudflare Email    │                   │
│ Worker (JS)         │                   │
│ • Allowed-contact   │                   │
│   check             │                   │
│ • Extract TOTP code │                   │
│ • Encrypt body      │                   │
│ • Forward ciphertext│                   │
└─────────┬───────────┘                   │
          │ HTTPS POST                    │
          ▼                               │
┌─────────────────────────────────────────────────────────┐
│                   FastAPI Server (Fly.io)                 │
│                                                          │
│  POST /v1/send         → validate, deduct, send (Resend) │
│  GET  /v1/inbox         → return unread, update heartbeat │
│  GET  /v1/inbox/:id     → return specific msg             │
│  POST /v1/rotate-key    → new key, invalidate old         │
│  POST /webhooks/inbound → store ciphertext from CF Worker │
│  POST /webhooks/stripe  → handle card payment             │
│                                                           │
│  GET  /auth/github      → OAuth flow                      │
│  GET  /alert/*          → handle signed URL clicks        │
│  GET  /account          → account page                    │
│                                                          │
│  [Background] heartbeat_checker (every 60s)               │
└─────────────────────────┬───────────────────────────────┘
                          │
                          ▼
              ┌───────────────────────┐
              │  Supabase Postgres     │
              └───────────────────────┘

┌─────────────────────────────────────────────────────────┐
│                  Agent (local runtime)                    │
│                                                          │
│  Reference Client (best practice):                       │
│  • Pulls from /v1/inbox                                  │
│  • Decrypts with TOTP codes (current ± N windows)        │
│  • Surfaces only decrypted messages to agent              │
│  • Sends alert on failed decryption                      │
│  • Agent never sees raw/unverified content                │
└─────────────────────────────────────────────────────────┘
```

---

## Database Schema

```sql
CREATE TABLE users (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    github_id BIGINT UNIQUE NOT NULL,
    github_username TEXT NOT NULL,
    email TEXT NOT NULL,
    created_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE agents (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID REFERENCES users(id) NOT NULL,
    address TEXT UNIQUE NOT NULL,           -- e.g. 'my-agent' (we append @sixel.mail)
    allowed_contact TEXT NOT NULL,          -- the one email this agent can talk to
    credit_balance INTEGER DEFAULT 0,      -- in messages, 500 = $5.00 worth
    last_seen_at TIMESTAMPTZ,              -- updated on every poll (heartbeat)
    heartbeat_timeout INTEGER DEFAULT 300, -- seconds before "agent down" alert (5 min)
    alert_status TEXT DEFAULT 'active',    -- 'active', 'paused', 'muted'
    alert_mute_until TIMESTAMPTZ,          -- when mute/pause expires
    agent_down_notified BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE messages (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    agent_id UUID REFERENCES agents(id) NOT NULL,
    direction TEXT NOT NULL,               -- 'inbound' or 'outbound'
    subject TEXT,
    body TEXT NOT NULL,
    is_read BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE api_keys (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    agent_id UUID REFERENCES agents(id) NOT NULL,
    key_hash TEXT NOT NULL,                -- SHA-256 hash
    key_prefix TEXT NOT NULL,              -- first 8 chars for identification
    created_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE credit_transactions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    agent_id UUID REFERENCES agents(id) NOT NULL,
    amount INTEGER NOT NULL,               -- positive = top-up, negative = usage
    reason TEXT NOT NULL,                  -- 'stripe_topup', 'message_sent', 'message_received', 'heartbeat_alert'
    stripe_session_id TEXT,
    created_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX idx_messages_agent_unread ON messages(agent_id, is_read) WHERE direction = 'inbound';
CREATE INDEX idx_agents_heartbeat ON agents(last_seen_at) WHERE alert_status = 'active';
CREATE INDEX idx_agents_address ON agents(address);
CREATE INDEX idx_api_keys_prefix ON api_keys(key_prefix);
```

---

## API Endpoint Logic

### Authentication

Tokens are 32 random bytes, base62 encoded, `sm_live_` prefixed. Stored as SHA-256 hash.

Validation: extract prefix → look up by `key_prefix` → verify hash → return `agent_id`.

### POST /v1/send

1. Validate token → get agent.
2. Check `credit_balance >= 1`. If not, return 402.
3. Send via Resend from `{agent.address}@sixel.mail` to `agent.allowed_contact`.
4. Server appends mandatory footer (agent cannot control or suppress).
5. Store message (direction: 'outbound').
6. Deduct 1 credit atomically: `UPDATE agents SET credit_balance = credit_balance - 1 WHERE id = :id AND credit_balance >= 1 RETURNING credit_balance`.
7. Log in `credit_transactions`.

### GET /v1/inbox

1. Validate token → get agent.
2. **Update `last_seen_at = now()`.** (Heartbeat.)
3. If `agent_down_notified = TRUE`, set FALSE, send "agent is back" email.
4. Return messages where `direction = 'inbound'` and `is_read = FALSE`.
5. Mark returned messages as `is_read = TRUE`.

### POST /v1/rotate-key

1. Validate current token.
2. Generate new token, hash it, store it, delete old record.
3. Return new token (shown once).

### POST /webhooks/inbound (from Cloudflare Email Worker)

1. **Verify shared secret** (Worker includes auth header; confirms request is from our Worker, not arbitrary).
2. Parse forwarded payload: `agent_address`, `from`, `subject`, `body` (ciphertext if TOTP-enabled, plaintext if not).
3. Look up agent by address.
4. Check `credit_balance >= 1`. If not, drop and notify human.
5. Store message body directly (ciphertext or plaintext — server doesn't distinguish).
6. Deduct 1 credit. Log transaction.

Note: Allowed-contact check and DMARC enforcement happen upstream (Cloudflare Email Routing enforces DMARC at SMTP; Email Worker checks allowed contact). Our webhook is the third line of defense.

### POST /webhooks/ses (removed)

Formerly handled SES→SNS→webhook inbound pipeline. Removed after Cloudflare migration (2026-02-10). All inbound now goes through `/webhooks/inbound` via Cloudflare Email Worker. Dead code — endpoint can be deleted.

### POST /webhooks/stripe

1. **Verify Stripe webhook signature.**
2. Reject events older than 5 minutes.
3. Extract `agent_id` and `credit_amount` from metadata.
4. Add credits. Log transaction. Email confirmation.

### GET /alert

1. Validate HMAC signature and expiration.
2. Update `alert_status` and `alert_mute_until`.
3. Return HTML confirmation page with current status and action links.

---

## Heartbeat Checker

Background task, every 60 seconds:

```python
async def heartbeat_checker():
    while True:
        now = datetime.utcnow()

        overdue_agents = await db.fetch_all("""
            SELECT * FROM agents
            WHERE alert_status = 'active'
              AND last_seen_at IS NOT NULL
              AND last_seen_at < now() - (heartbeat_timeout * interval '1 second')
              AND agent_down_notified = FALSE
              AND (alert_mute_until IS NULL OR alert_mute_until < now())
        """)

        for agent in overdue_agents:
            await send_agent_down_email(agent)
            await db.execute(
                "UPDATE agents SET agent_down_notified = TRUE WHERE id = :id",
                {"id": agent.id}
            )

        # Un-mute expired mutes
        await db.execute("""
            UPDATE agents
            SET alert_status = 'active', alert_mute_until = NULL
            WHERE alert_mute_until IS NOT NULL AND alert_mute_until < now()
        """)

        await asyncio.sleep(60)
```

---

## HMAC Signed URLs

```python
import hmac, hashlib, time, urllib.parse

SECRET = os.environ["SIGNING_SECRET"]

def sign_alert_url(agent_id: str, action: str) -> str:
    expires = int(time.time()) + 86400 * 30  # 30 days
    payload = f"{agent_id}:{action}:{expires}"
    signature = hmac.new(
        SECRET.encode(), payload.encode(), hashlib.sha256
    ).hexdigest()[:16]
    params = urllib.parse.urlencode({
        "agent": agent_id, "action": action,
        "expires": expires, "sig": signature,
    })
    return f"https://api.sixel.mail/alert?{params}"
```

---

## Resend Setup (outbound email)

Resend (resend.com) handles all outbound email. Built on AWS SES infrastructure underneath, which means our domain builds SES sending reputation. If we later need direct SES access (4-9x cheaper at scale), we can reapply with real sending history.

1. **Domain verified** via DKIM (DNS records managed by Resend).
2. **API key** stored as Fly.io secret (`RESEND_API_KEY`).
3. **Send via** single `httpx` POST to `https://api.resend.com/emails`.
4. **No AWS credentials needed.** AWS is fully removed from the stack.

## Stripe Setup

Stripe Checkout in payment mode (one-time). Webhook listens for `checkout.session.completed`.

```python
def create_checkout_session(agent_id: str, amount_dollars: int):
    session = stripe.checkout.Session.create(
        mode="payment",
        line_items=[{
            "price_data": {
                "currency": "usd",
                "unit_amount": amount_dollars * 100,
                "product_data": {"name": f"Sixel-Mail Credit ({amount_dollars * 100} messages)"},
            },
            "quantity": 1,
        }],
        metadata={"agent_id": agent_id, "credit_amount": amount_dollars * 100},
        success_url="https://sixel.mail/topup/success",
        cancel_url="https://sixel.mail/topup/cancel",
    )
    return session.url
```

---

## Deliverability

**Infrastructure (handle once):** SPF/DKIM/DMARC from day one. Clean domain. Warm up before launch. Resend handles IP reputation.

**Per-user (handle once):** First email might hit spam. Human marks "not spam." Done forever. Onboarding includes: "Check your inbox and spam folder. Mark it as safe."

**Naturally spam-proof:** One agent, one human, a few msgs/day, strict allowlist. Invisible to spam detection.

---

## Project Structure

```
sixel-mail/
├── app/
│   ├── main.py              # FastAPI app, startup, background tasks
│   ├── config.py             # env vars, settings
│   ├── models.py             # SQL models
│   ├── auth.py               # GitHub OAuth + API key validation
│   ├── routes/
│   │   ├── api.py            # /v1/send, /v1/inbox, /v1/inbox/:id, /v1/rotate-key
│   │   ├── webhooks.py       # /webhooks/inbound (CF Worker), /webhooks/stripe
│   │   ├── alerts.py         # /alert (signed URL handler + confirmation page)
│   │   ├── account.py        # /account
│   │   └── signup.py         # /auth/github, /setup, /topup
│   ├── services/
│   │   ├── email.py          # Resend send + email templates + footer generation
│   │   ├── credits.py        # Credit balance management
│   │   ├── heartbeat.py      # Heartbeat checker background task
│   │   └── signing.py        # HMAC URL signing/verification
│   └── templates/
│       ├── signup.html       # Signup/onboarding page
│       ├── account.html      # Account page
│       └── alert_confirm.html
├── migrations/
│   └── 001_initial.sql
├── requirements.txt
├── fly.toml
├── Dockerfile
├── .env.example
└── README.md
```

## Environment Variables

```bash
DATABASE_URL=postgresql://...@db.supabase.co:5432/postgres
RESEND_API_KEY=re_...
STRIPE_SECRET_KEY=sk_live_...        # not yet configured
STRIPE_WEBHOOK_SECRET=whsec_...      # not yet configured
GITHUB_CLIENT_ID=...
GITHUB_CLIENT_SECRET=...
SIGNING_SECRET=...
API_BASE_URL=https://sixel.email
MAIL_DOMAIN=sixel.email
CF_WORKER_SECRET=...                 # shared secret: Worker ↔ webhook auth
CF_ACCOUNT_ID=...                    # Cloudflare account ID (for KV API)
CF_KV_NAMESPACE_ID=...               # KV namespace (agent→contact mappings)
CF_API_TOKEN=...                     # Cloudflare API token (KV writes)
```

## Deployment

```dockerfile
FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080"]
```

```toml
# fly.toml
app = "sixel-mail"
[http_service]
  internal_port = 8080
  force_https = true
```

---

# Part 3: Security

## Abuse Prevention

- **Rate limit: 100 messages/day per agent.** Hard cap.
- **Rate limit: 10 agents per user.**
- **Plain text only.** No HTML. Eliminates phishing with spoofed buttons/forms.
- **Mandatory footer.** Every outbound email branded as sixel-mail. Not removable by agent.
- **Auto-disable on complaint.** If recipient marks as spam, disable agent.
- **Stripe identity trail.** Every account has a payment on file.
- **One recipient per agent.** Can't blast.
- **$0.01/message.** 10,000 spam emails = $100.

## Agent Token Security

- Stored as SHA-256 hashes. Never plaintext.
- Shown once. No "show again." Only rotate.
- Rotation endpoint: `POST /v1/rotate-key`.
- `sm_live_` prefix: detectable by GitHub secret scanning. Register with partner program.
- **Limited blast radius:** leaked key can only email one person.

## Inbound Email Spoofing

The most subtle risk. Email `From:` headers are trivially forgeable. An attacker could send fake replies to the agent — effectively prompt injection via email.

### Layer 1: Spoofed sender (protectable)

Someone forges the allowed contact's email address. The email didn't come from the contact's mail provider at all. SPF/DKIM/DMARC catch this because the sending server isn't authorized for that domain.

Mitigations (layered, defense in depth):
1. **DMARC enforcement at SMTP** (Cloudflare Email Routing). Spoofed emails rejected before they reach our code.
2. **Allowed-contact check at edge** (Cloudflare Email Worker). Wrong sender → rejected before reaching our server.
3. **TOTP encryption** (optional). Even if layers 1 and 2 fail, the agent's reference client can't decrypt a message without a valid TOTP code → discards it.
4. **Reply-chain validation (later).** Only accept replies to previous outbound messages.
5. **Documentation.** Tell developers: treat email replies like user input.

### Layer 2: Compromised sender account (not protectable by us)

If the allowed contact's email account is compromised (stolen password, session hijack, compromised device), the attacker sends email that passes every authentication check because it IS legitimately sent through the contact's mail provider. SPF passes. DKIM passes. DMARC passes. To the agent, it's indistinguishable from the real person.

This matters more here than in most systems because:
- The "one allowed contact" design creates implicit high trust. The agent (and the developer building on the agent) assumes the identity of the sender. The channel feels private and verified.
- The simplicity of the system buries this assumption. There's no visible authentication ceremony, no login screen, no MFA prompt. Email arrives, it's from the right address, it's trusted. The intimacy of the channel makes the trust assumption invisible.
- AI agents may act on email instructions with less skepticism than a human would. A human might notice something "off" about a message from a compromised account. An agent follows instructions.

We cannot solve this. It is the same boundary every email-dependent system operates at. But we should:
1. **Document it explicitly** for developers building on sixel-mail. "Your agent's allowed contact is an email address, not a verified identity. If that email account is compromised, your agent will follow instructions from the attacker."
2. **Recommend 2FA on the contact's email account** in onboarding/docs.
3. **Consider optional confirmation flows for high-stakes actions** — e.g., agent emails "You asked me to delete all data. Reply CONFIRM to proceed." This doesn't prevent the attack but adds friction.
4. **Log everything.** If a compromise is detected after the fact, full message history enables damage assessment.

## Payment Security

- Stripe webhook signature verification on every request.
- Replay rejection (Stripe timestamp check).
- Atomic credit deduction: `UPDATE ... WHERE credit_balance >= 1 RETURNING credit_balance`.

## External Intrusion

- 2FA on all accounts: Fly.io, Cloudflare, Stripe, Supabase, GitHub, Resend, registrar.
- No SSH to production. Deploy only via `fly deploy`.
- Least-privilege API tokens (scoped Cloudflare, scoped Resend).
- Domain registrar transfer lock.
- Cloudflare Worker auth on inbound webhooks.
- Secrets as Fly.io secrets (encrypted at rest, never in code).
- Minimal dependencies. `pip audit` in CI.

## Security Checklist

**Must-have (ship-blocking):**
- [ ] API keys stored as SHA-256 hashes
- [ ] Stripe webhook signature verification
- [ ] Cloudflare Email Worker auth on inbound webhook
- [ ] DMARC enforcement at SMTP (Cloudflare Email Routing)
- [ ] Allowed-contact check at edge (Cloudflare Email Worker)
- [ ] TOTP encryption in Email Worker (for TOTP-enabled agents)
- [ ] Atomic credit deduction
- [ ] HMAC-signed alert URLs with expiration
- [ ] Rate limit: 100 msgs/day per agent
- [ ] Rate limit: 10 agents per user
- [ ] Rate limit: 120 polls/min per agent
- [ ] HTTPS only
- [ ] 2FA on all infrastructure accounts
- [ ] Least-privilege access on all services
- [ ] Plain text email only
- [ ] Mandatory footer on all outbound
- [ ] Domain registrar transfer lock

**Should-have (first month):**
- [ ] Key rotation endpoint
- [ ] Register `sm_live_` with GitHub secret scanning
- [ ] Auto-disable agent on Resend complaint/bounce webhook
- [x] SPF/DKIM soft-fail warning in body (handled by Cloudflare DMARC enforcement)
- [ ] `pip audit` in CI
- [ ] Basic request logging (not message content)

**Later:**
- [ ] True E2E encryption via `sixel.email/e` static page
- [ ] Reply-chain validation
- [ ] IP allowlisting for API keys
- [ ] Usage anomaly detection

---

# Part 4: Marketing

## Principle

No funnels, no drip campaigns, no content calendars. Put the product where people with the problem are, at the moment they're feeling the problem.

## Launch Day (1 hour)

**1. Hacker News "Show HN"**

```
Show HN: Sixel-Mail – An email address for your AI agent ($0.01/msg)
```
```
I built this because my Claude Code agent keeps getting stuck
and I don't know about it until I check back hours later.

Sixel-Mail gives your agent an email address with a leash:
- One allowed contact (you). Agent can't email anyone else.
- $0.01 per message. Polling is free.
- If your agent stops responding, you get an email.
- Everything is controlled from your inbox. No dashboard.

API is 4 endpoints. Integration is 5 lines in your agent config.

https://sixel.mail
```

Post between 8-9am ET, Tuesday or Wednesday.

**2. Tweet/X**

```
gave my AI agent an email address.

it can only email me. costs $0.01/msg. if it goes
down, i get an email. the whole UI is my inbox.

4 API endpoints. 5 lines of config. that's the product.

https://sixel.mail
```

**3. Reddit:** r/ChatGPT, r/ClaudeAI, r/LocalLLaMA, r/SideProject. Lead with the Claude Code use case.

## Week 1-2 (30 min/week)

- Open source a tiny client library (pip/npm). 50 lines wrapping the API. Gets you a GitHub repo and a package.
- Drop helpful comments in relevant GitHub issues/discussions.
- Answer "how do I get my agent to notify me" questions on Stack Overflow/Reddit.

## Ongoing (Sixel Can Do This)

| Task | How |
|---|---|
| Monitor HN/Reddit/GitHub for relevant threads | Search APIs, daily |
| Draft responses to relevant questions | Sixel drafts, you approve |
| Write changelog posts from git commits | Sixel drafts, you post |
| Track mentions of sixel-mail | Search alerts |

The product dogfoods its own marketing — sixel uses sixel-mail to email you about marketing opportunities.

## What NOT to Do

- No paid ads (ARPU too low)
- No blog/content marketing machine
- No Product Hunt (wrong audience)
- No email newsletter
- No branding exercise

## Budget: $0

---

# Part 5: Build History

*What we actually built and when. Originally a plan; now a record. Infrastructure has since changed — SES replaced by Resend (outbound) and Cloudflare (inbound). See Parts 2 and 7 for current architecture.*

### Phase 1: Can an agent send me an email? (Day 1)
SES domain verification, DNS records, FastAPI `POST /v1/send`. Hardcoded everything. First email delivered.

### Phase 2: Can I reply? (Day 1-2)
SES inbound via SNS topic → webhook. Supabase DB. `GET /v1/inbox`. First end-to-end round-trip.

### Phase 3: Auth and credits (Day 2-3)
API key generation + validation. Credit balance tracking + atomic deduction.

### Phase 4: Signup and payment (Day 3-4)
GitHub OAuth. Signup page. Stripe Checkout scaffolding. Full flow: sign up → pay → API key → send.

### Phase 5: Heartbeat and email UI (Day 4-5)
Heartbeat via `last_seen_at`. Agent down/back emails. Signed URL footer links. Alert controls.

### Phase 6: Account page (Day 5-6)
Account page, key rotation, credit refill links.

### Phase 7: Polish and security (Day 6-7)
SPF/DKIM/DMARC enforcement on inbound. Rate limiting. Error handling, logging.

### Phase 8: Cloudflare migration + Resend (Day 10)
Inbound moved to Cloudflare Email Routing → Email Worker → webhook. Outbound moved to Resend. AWS fully removed. TOTP encryption implemented. See Part 7.

---

# Part 6: Launch Readiness Checklist

Every box must be checked before launch.

## 1. Core Email Flow

### Outbound (agent → human)
- [ ] `POST /v1/send` with valid token delivers email to allowed contact
- [ ] Email arrives in inbox (not spam) after initial "not spam" marking
- [ ] Email contains correct subject and body
- [ ] Email contains mandatory footer with all links
- [ ] Footer links are clickable in Gmail
- [ ] Footer links are clickable in Apple Mail (iOS)
- [ ] Footer links are clickable in Outlook
- [ ] Email `From` shows as `agent-name@sixel.mail`
- [ ] Insufficient credits returns 402 with top-up URL
- [ ] Missing/invalid auth token returns 401

### Inbound (human → agent)
- [ ] Reply from allowed contact gets stored
- [ ] `GET /v1/inbox` returns the reply
- [ ] Reply from non-allowed address is silently dropped
- [ ] Reply from spoofed address (failing SPF/DKIM) is rejected
- [ ] Inbound deducts 1 credit
- [ ] Inbound with 0 credits is dropped (human notified)
- [ ] `GET /v1/inbox` marks messages as read
- [ ] `GET /v1/inbox/:id` returns specific message

### Round-trip
- [ ] Full cycle: curl send → email → human replies → curl poll → reply returned
- [ ] Completes in under 60 seconds end-to-end
- [ ] 3 consecutive round-trips without issues

## 2. Heartbeat

### Agent alive detection
- [ ] `GET /v1/inbox` updates `last_seen_at`
- [ ] Account page shows correct "last seen" time

### Agent down detection
- [ ] Agent stops polling → "agent down" email after configured timeout
- [ ] Down alert sent only once (not repeated)
- [ ] Agent resumes → "agent is back" email sent
- [ ] Correct downtime duration in recovery email
- [ ] Agent that never polled (null `last_seen_at`) does NOT trigger alert

### Alert controls
- [ ] "Turn alerts ON" → confirmation page, alerts active
- [ ] "Pause 1hr" → suppressed, auto-resume after 1 hour
- [ ] "Pause 8hr" → suppressed, auto-resume after 8 hours
- [ ] "Mute until tomorrow" → suppressed, resume at 8am local
- [ ] "Turn alerts ON" when already on → harmless no-op
- [ ] 25-day-old email link still works
- [ ] 31-day-old email link fails gracefully
- [ ] Confirmation page shows correct status with action links
- [ ] Tampered signed URL returns error, not crash

## 3. Payments

### Stripe
- [ ] "Add $5" redirects to Stripe Checkout
- [ ] Completing payment adds 500 credits
- [ ] Credits appear within 5 seconds of webhook
- [ ] Confirmation email sent
- [ ] Canceling checkout does NOT add credits
- [ ] Invalid webhook signature rejected
- [ ] Replayed webhook does not double-credit

### Credit deduction
- [ ] Sending deducts 1 credit
- [ ] Receiving deducts 1 credit
- [ ] Heartbeat alerts deduct 1 credit each
- [ ] Low balance warning deducts 1 credit
- [ ] `credit_transactions` log is accurate
- [ ] Race condition: 10 simultaneous sends with 5 credits → exactly 5 succeed
- [ ] Balance never goes negative

### Low balance warning
- [ ] Warning sent when balance drops below 50
- [ ] Includes top-up link
- [ ] Sent only once per threshold crossing

## 4. Signup & Onboarding

- [ ] GitHub OAuth creates user correctly
- [ ] Returning user logs in (no duplicate)
- [ ] Agent address creation works
- [ ] Duplicate addresses rejected
- [ ] Invalid characters rejected
- [ ] API key generated, displayed once, stored as hash
- [ ] Payment redirects back correctly
- [ ] Credits loaded before API key shown
- [ ] Test email sent automatically
- [ ] Config snippet is copyable
- [ ] **Full flow under 5 minutes:** login → create → pay → API key → test email → mark safe → curl send → receive → reply → curl poll

## 5. Account Page

- [ ] Shows agent status with last seen time
- [ ] Shows allowed contact with change option
- [ ] Change allowed contact works
- [ ] Shows credit balance (matches DB)
- [ ] Shows masked API key
- [ ] Rotate generates new key, invalidates old immediately
- [ ] New key works immediately
- [ ] Shows recent messages (correct direction, content, timestamps)
- [ ] Top-up link works
- [ ] "Create another agent" works
- [ ] Billing history shows all top-ups
- [ ] Requires authentication
- [ ] User A cannot see User B's data

## 6. Security

### Authentication
- [ ] Valid key → 200. Invalid/missing key → 401.
- [ ] Key for Agent A cannot access Agent B
- [ ] Rotated key returns 401

### Webhook verification
- [x] Inbound webhook: valid Worker auth header accepted; invalid rejected
- [x] Inbound webhook: requests without auth header rejected
- [ ] Valid Stripe signature accepted; invalid rejected

### Signed URLs
- [ ] Valid + unexpired → accepted
- [ ] Tampered agent ID → rejected
- [ ] Tampered action → rejected
- [ ] Expired → rejected
- [ ] Missing params → rejected

### Email security (inbound via Cloudflare)
- [ ] Allowed contact + DMARC PASS → accepted
- [ ] Spoofed sender (DMARC FAIL) → rejected at SMTP by Cloudflare
- [ ] Non-allowed address → rejected by Email Worker
- [ ] TOTP-enabled agent: body encrypted before reaching our server
- [ ] TOTP-enabled agent: message without TOTP code → forwarded plaintext (backwards compatible)
- [ ] Outbound SPF record valid
- [x] Outbound DKIM signature valid (Resend, verified)
- [ ] DMARC record published

### TOTP encryption
- [ ] TOTP secret generated client-side (never sent to server)
- [ ] QR code renders correctly for standard authenticator apps
- [ ] Worker extracts 6-digit code from first or last line
- [ ] Worker encrypts body with extracted code
- [ ] Worker strips TOTP line before encryption
- [ ] Reference client decrypts with current TOTP window ± N
- [ ] Reference client sends alert on failed decryption
- [ ] Reference client does NOT include gibberish in alert

### Rate limits
- [ ] >100 msgs/day → rate limited
- [ ] >120 polls/min → rate limited
- [ ] >10 agents → rejected
- [ ] Clear error with retry info

### Data isolation
- [ ] User A cannot see/modify User B's agents
- [ ] User A cannot poll User B's inbox
- [ ] User A cannot send as User B's agent

## 7. Infrastructure

### DNS
- [x] MX records → Cloudflare Email Routing (`route1/2/3.mx.cloudflare.net`)
- [x] DKIM records for Resend (verified)
- [ ] SPF TXT includes Resend sending IPs
- [ ] DMARC TXT published
- [x] Domain resolves to Fly.io
- [x] HTTPS certificate valid and auto-renewing

### Cloudflare
- [x] Email Routing enabled for sixel.email
- [x] Email Worker deployed and active (`sixel-mail-inbound`)
- [x] Worker → webhook auth secret configured
- [x] KV namespace created with agent→contact mappings (`sixel-mail-agents`)
- [x] Catch-all routing rule: `*@sixel.email` → Worker
- [x] support@sixel.email → eterryphd@gmail.com forwarding
- [ ] DMARC enforcement confirmed (spoofed email rejected at SMTP) — needs red team verification

### Resend (outbound)
- [x] Domain verified (DKIM)
- [ ] Bounce/complaint webhook configured
- [ ] Sending limits understood (Resend free tier: 100/day, paid: 50K/mo)

### Database
- [ ] All tables and indexes exist
- [ ] Connection string in Fly.io secrets
- [ ] Handles 10 simultaneous requests

### Hosting
- [ ] Deploys successfully
- [ ] HTTPS enforced
- [ ] Health check works
- [ ] Restarts cleanly after crash
- [ ] Heartbeat task survives restart
- [ ] All env vars set as secrets
- [ ] No secrets in code or logs

## 8. Edge Cases

- [ ] Empty body → handled
- [ ] 100KB body → rejected with clear error
- [ ] Unicode/emoji in body → delivered correctly
- [ ] Whitespace-only reply → handled
- [ ] Reply with attachments → text body delivered, attachments ignored
- [ ] Two agents, same allowed contact → both work independently
- [ ] Poll with 0 messages → empty array, not error
- [ ] Rapid polling (10x/sec) → rate limited, not crashed
- [ ] Stripe webhook before redirect → credits still added
- [ ] Server restart → heartbeat checker resumes
- [ ] Down → back → down again → correct email sequence

## 9. Pre-Launch Ops

- [ ] Domain registrar transfer lock enabled
- [ ] 2FA: Fly.io
- [ ] 2FA: Cloudflare
- [ ] 2FA: Resend
- [ ] 2FA: Stripe
- [ ] 2FA: Supabase
- [ ] 2FA: GitHub
- [ ] 2FA: Domain registrar
- [ ] IAM is least-privilege
- [ ] Can redeploy from scratch in < 1 hour
- [ ] Access to all accounts from phone

## 10. Smoke Test

The final gate. Do this last.

- [ ] **Sign up fresh.** GitHub → create agent → pay $5 → get API key.
- [ ] **Configure a real agent** (Claude Code) with the config snippet.
- [ ] **Let it get stuck.** Wait for the email.
- [ ] **Reply from your phone.** Agent receives reply and continues.
- [ ] **Kill the agent.** Wait 5 minutes. Receive "agent down" email.
- [ ] **Click "Pause 1hr"** from the email. Verify confirmation page.
- [ ] **Restart the agent.** Receive "agent is back" email.
- [ ] **Check account page.** Messages, credits, status all correct.
- [ ] **Every email had:** correct footer, working links, accurate credit count.

If this works from your phone while away from your desk, ship it.

---

## Go / No-Go

| Section | Status |
|---|---|
| 1. Core Email Flow | ☐ PASS |
| 2. Heartbeat | ☐ PASS |
| 3. Payments | ☐ PASS |
| 4. Signup & Onboarding | ☐ PASS |
| 5. Account Page | ☐ PASS |
| 6. Security | ☐ PASS |
| 7. Infrastructure | ☐ PASS |
| 8. Edge Cases | ☐ PASS |
| 9. Pre-Launch Ops | ☐ PASS |
| 10. Smoke Test | ☐ PASS |

**All 10 PASS → launch.**
**Any FAIL → fix, retest, reassess.**

---

# Part 7: Cloudflare Inbound Architecture & TOTP Encryption

*Migration completed 2026-02-10. AWS fully removed from the stack.*

## Why We Moved

SES checked SPF/DKIM/DMARC but did not enforce — it delivered all email regardless of verdict. Both authentication (is the sender who they claim to be?) and authorization (is the sender allowed to talk to this agent?) were enforced solely in our Python webhook handler. One bug in that code and both checks failed.

The migration pushed both checks below our application layer.

## Current Inbound Architecture

| Layer | Provider | Responsibility |
|-------|----------|---------------|
| 1. MX / SMTP | Cloudflare Email Routing | Receives email, enforces DMARC, rejects spoofed senders at SMTP level |
| 2. Email Worker | Cloudflare (our JS code) | Checks sender against allowed contact. If TOTP-enabled: extracts TOTP code from body, encrypts body, strips code. Forwards to our webhook. |
| 3. Webhook | Our server (Fly.io) | Stores message body (ciphertext or plaintext). Third line of defense, not first. |
| 4. API | Our server (Fly.io) | Serves stored messages to agents. No change to interface. |
| 5. Agent | Agent's local runtime | Reference client decrypts with TOTP, surfaces only verified messages. |

## What Changed (from SES)

- **MX record**: now `route1/2/3.mx.cloudflare.net` (Cloudflare Email Routing) — completed 2026-02-10
- **SPF TXT record**: updated to include Cloudflare
- **SES receipt rule**: removed (SES no longer receives inbound)
- **SNS topic**: removed
- **AWS entirely removed**: no AWS credentials in the stack. Outbound migrated to Resend.
- **Webhook handler**: simplified — no SNS signature verification, no SPF/DKIM/DMARC checking (Cloudflare handles both). Receives pre-processed payload from Email Worker.
- **Cloudflare Email Worker**: JavaScript at Cloudflare edge. Checks allowed contact, handles TOTP encryption, forwards to our webhook. Deployed and live.
- **TOTP setup on agent creation**: Browser generates secret client-side, never touches server. Implemented.

## What Didn't Change

- Outbound email (Resend API, domain verified via DKIM)
- API endpoints (same interface, body may be ciphertext)
- Database schema (body column stores whatever the Worker forwarded)
- Dashboard, payments, heartbeat

---

## TOTP Encryption

### The Problem

If our server is compromised, an attacker can read all messages and inject prompt injection content into agent inboxes. All current security checks are enforced in our code — they're only as strong as our code is correct.

### The Solution

TOTP-based encryption with the Cloudflare Email Worker as the encryption boundary.

1. At agent setup, browser generates a TOTP shared secret **client-side** (JavaScript). Displays QR code for authenticator app. Displays raw secret for agent config. **Secret never touches our server.**
2. Agent stores the TOTP shared secret locally (credential file, not in our database).
3. To email the agent, human pastes the current 6-digit TOTP code at the top or bottom of their message body.
4. Cloudflare Email Worker extracts the TOTP code, encrypts the body with it, strips the code, forwards only ciphertext to our server.
5. Our server stores ciphertext — never sees plaintext.
6. Agent's reference client generates recent TOTP codes from the shared secret, tries each to decrypt. One works → message is authentic and readable. None work → alert sent, message discarded.

### Key Distribution (setup, once)

```
┌──────────────────────────────────────────────────────────────────┐
│                    User's Browser (setup page)                    │
│                                                                   │
│   JavaScript generates TOTP shared secret client-side             │
│   Secret NEVER leaves the browser via network                     │
│                                                                   │
│   ┌─────────────┐              ┌──────────────────┐              │
│   │  QR Code     │              │  Raw Secret Text  │             │
│   │  (on screen) │              │  (on screen)      │             │
│   └──────┬──────┘              └────────┬─────────┘              │
│          │                              │                         │
└──────────┼──────────────────────────────┼─────────────────────────┘
           │ eyes → camera                │ eyes → clipboard
           ▼                              ▼
┌────────────────────┐         ┌────────────────────────┐
│  Authenticator App  │         │  Agent Config File      │
│  (phone)            │         │  (local machine)        │
│                     │         │                         │
│  Generates 6-digit  │         │  Generates 6-digit      │
│  TOTP codes every   │         │  TOTP codes to attempt  │
│  30 seconds         │         │  decryption             │
└────────────────────┘         └────────────────────────┘

    HUMAN endpoint                  AGENT endpoint

    The shared secret exists at these two endpoints and nowhere else.
    Our server, database, and Cloudflare never possess the secret.
```

### Inbound Message Flow (per message)

```
┌─────────────────────────────────────────────────────────┐
│  Human writes email                                      │
│                                                          │
│  "Here are the DB creds: postgres://...                  │
│   847291"  ← TOTP code from authenticator app            │
│                                                          │
│  Sees: plaintext + TOTP code                             │
└──────────────────────┬──────────────────────────────────┘
                       │
          ┌────────────▼─────────────┐
          │  Gmail / mail provider    │
          │  Sees: plaintext + code   │
          └────────────┬─────────────┘
                       │ SMTP
          ┌────────────▼─────────────┐
          │  Cloudflare Email Routing │
          │  DMARC enforcement        │
          │  Sees: plaintext + code   │
          │  (rejects spoofed sender) │
          └────────────┬─────────────┘
                       │
          ┌────────────▼──────────────────────────────────┐
          │  Cloudflare Email Worker                       │
          │                                                │
          │  1. KV lookup: agent exists? sender allowed?   │
          │  2. Extract "847291" from body                  │
          │  3. Derive AES-256 key:                        │
          │     PBKDF2(code, salt=agent+date) → 256-bit    │
          │  4. Encrypt body (minus code line):             │
          │     AES-256-GCM → iv + ciphertext + auth tag   │
          │  5. Base64 encode                               │
          │                                                │
          │  Sees: plaintext briefly in Worker memory       │
          │  Forwards: base64(iv + ciphertext + tag)        │
          └────────────┬──────────────────────────────────┘
                       │ HTTPS POST + shared secret
          ┌────────────▼──────────────────────────────────┐
          │  Our Server (Fly.io)                           │
          │                                                │
          │  Stores in database:                           │
          │    body = "nK7x2mQ9f4...Rz8wA=="              │
          │    encrypted = true                            │
          │                                                │
          │  Sees: ciphertext only. Cannot decrypt.        │
          └────────────┬──────────────────────────────────┘
                       │ GET /v1/inbox
          ┌────────────▼──────────────────────────────────┐
          │  Agent Reference Client (local)                │
          │                                                │
          │  Has: TOTP shared secret from setup            │
          │  1. Generate TOTP codes for current ± N windows│
          │     (e.g. 847291, 193847, 502916)              │
          │  2. For each code:                              │
          │     PBKDF2(code, salt=agent+date) → key        │
          │     Attempt AES-256-GCM decrypt                │
          │  3. One succeeds → plaintext recovered          │
          │     "Here are the DB creds: postgres://..."    │
          │     None succeed → alert human, discard msg    │
          │                                                │
          │  Sees: plaintext (after successful decryption)  │
          │  Decryption IS authentication.                  │
          └───────────────────────────────────────────────┘

WHAT EACH PARTY SEES:

  Human's mail provider:  plaintext + TOTP code
  Cloudflare (SMTP):      plaintext + TOTP code (briefly, in memory)
  Cloudflare Worker:      plaintext + TOTP code → ciphertext (briefly, in memory)
  Our server:             ciphertext only ←── THIS IS THE POINT
  Our database:           ciphertext only
  Agent client:           ciphertext → plaintext (after local decryption)

ATTACK SCENARIOS:

  Server compromised:     attacker reads ciphertext → useless
  Database breached:      attacker reads ciphertext → useless
  Prompt injection email: no valid TOTP → decryption fails → agent discards
  TOTP code intercepted:  decrypts ONE message, expires in 30s, no forward access
  Cloudflare compromised: same trust boundary as Gmail (sees plaintext already)
```

### Outbound Flow (asymmetric — plaintext)

```
┌───────────────────────────┐
│  Agent sends via API       │
│  POST /v1/send             │
│  body = plaintext          │
└─────────────┬─────────────┘
              │
┌─────────────▼─────────────┐
│  Our Server                │
│  Sees: plaintext           │  ← known weakness
│  Sends via Resend API      │
└─────────────┬─────────────┘
              │
┌─────────────▼─────────────┐
│  Human's Inbox             │
│  Sees: plaintext           │
└───────────────────────────┘

  Outbound is NOT encrypted. Known, accepted asymmetry.
  Server compromise → outbound messages readable.
  Agent replies may leak context about encrypted inbound.
  Future mitigation: static decrypt page at sixel.email/e
```

### What This Achieves

- **Our server compromised** → attacker sees ciphertext. Useless.
- **Database breached** → ciphertext. Useless.
- **Prompt injection via inbox** → injected message isn't encrypted with a valid TOTP code → agent's client fails to decrypt → discards. Injection impossible.
- **TOTP code in email body** → expires in 30 seconds. Captured from logs, it decrypts one message but gives no forward access.

### Trust Boundaries

- Cloudflare sees plaintext briefly in Worker memory (acceptable — same trust level as Gmail seeing plaintext now).
- TOTP shared secret exists only at the endpoints: human's authenticator app + agent's local config. Never in our infrastructure.
- TOTP secret generated client-side in user's browser at setup. Never touches our server. The one-time exchange is analog: eyes (read QR/secret) → camera (scan) → clipboard (copy to agent config).
- **Decryption IS authentication.** No separate validation step needed.

### Outbound: Plaintext Asymmetry

Agent → human email remains **unencrypted plaintext**. There's no good UX for the human to decrypt agent emails with current tooling — you can't ask someone to punch a TOTP code into a decrypt page every time they get an email.

This means:
- If our server is compromised, outbound messages are readable
- Agent replies may leak context about encrypted inbound content
- This is a known, accepted asymmetry

**Future mitigation:** A static encrypt/decrypt page at `sixel.email/e` — human decrypts in-browser. Doesn't change the architecture, just adds a static HTML page. But it adds friction, so it's opt-in and later.

### TOTP Is Optional

TOTP encryption is opt-in at agent setup. Agents without TOTP work exactly as before — plaintext in, plaintext stored, plaintext out. The one-allowed-contact check and DMARC enforcement still apply. TOTP is for users who want the additional guarantee that even a compromised server can't read or inject messages.

### How TOTP Works (for reference)

TOTP (RFC 6238): shared secret + current time ÷ 30 seconds → HMAC-SHA1 → truncate to 6 digits. Both sides run the same math independently. No server communication needed. Any standard authenticator app works (Google Authenticator, Authy, 1Password, Bitwarden, etc.). The QR code is a standard URL: `otpauth://totp/sixel.email:agent-name?secret=BASE32SECRET&issuer=sixel.email`

---

## Agent Best Practices (Reference Client)

**Core principle: the agent never reads raw email.** It reads through a local decryption client that gates all access.

The reference implementation is a local client/library that:
1. Pulls messages from `/v1/inbox`
2. Attempts TOTP decryption on each message (current window ± N to account for delivery delay)
3. Surfaces only successfully decrypted messages to the agent
4. On failed decryption: sends an alert to the allowed contact ("I received a message I couldn't decrypt"). Does NOT include the undecryptable content in the alert (it could be crafted to inject via the alert text).
5. If failures repeat, escalates the warning — possible tampering, not just clock drift.

**Why this matters:** The agent literally cannot be prompt-injected through email because it never has access to unverified content. The client is the gatekeeper.

**We can't enforce this** — users can bypass the client and call the API directly. But we ship the reference implementation, make it the easy/default path, and document why it matters.

### Agent Setup Instructions

The config snippet shown at agent creation includes:
1. API endpoint + token (same as before)
2. TOTP shared secret (if enabled)
3. Reference client usage (or clear instructions to build the equivalent)
4. **"Never call `/v1/inbox` directly from agent code. Use the decryption client."**

---

## Cloudflare Email Worker Design

### Responsibilities

1. **Receive email** from Cloudflare Email Routing
2. **Check allowed contact**: look up agent by `To` address, verify `From` matches allowed contact. Reject if no match.
3. **Check TOTP status**: does this agent have TOTP enabled?
   - If no: forward plaintext body to our webhook
   - If yes: extract TOTP code from body (first or last line matching `/^\d{6}$/`), encrypt body with the code as key, strip the code, forward ciphertext
4. **Forward to webhook**: HTTPS POST to our server with auth header + processed payload

### Allowed-Contact Lookup

The Worker needs to know which agents exist and who their allowed contacts are. Options:
- **(a) Call our API** from the Worker — simplest but adds latency and creates a dependency on our server being up
- **(b) Cloudflare KV** — replicate agent→contact mappings. Fast reads, eventual consistency. Needs sync mechanism.
- **(c) Cloudflare D1** — SQLite at the edge. Second database to maintain.

Decision: **(b) Cloudflare KV**. Our server pushes updates to KV on agent create/update. KV reads are fast (<1ms at edge). Eventual consistency is fine — agent creation isn't time-critical. Sync is a single API call on agent mutation.

### TOTP Encryption in the Worker

When the Worker detects a TOTP code in the email body:
1. Extract the 6-digit code (regex: first or last non-empty line matching `^\d{6}$`)
2. Derive an AES-256 key from the code using PBKDF2 (salt = agent address + message date)
3. Encrypt the body (minus the TOTP line) with AES-256-GCM
4. Forward: `{agent_address, from, subject, body: base64(iv + ciphertext + tag), encrypted: true}`

When no TOTP code is found:
- Forward plaintext: `{agent_address, from, subject, body: original_body, encrypted: false}`

### DNS (current)

```
MX  @  → route1.mx.cloudflare.net (priority 84)
MX  @  → route2.mx.cloudflare.net (priority 31)
MX  @  → route3.mx.cloudflare.net (priority 73)
A/AAAA @ → Fly.io
DKIM records → Resend (verified)
```

SES MX record, SNS topic, SES receipt rule — all removed.

---

## Upgrade Path: True E2E Encryption

If we later build a static page at `sixel.email/e`:
- Human encrypts in-browser before sending → pastes ciphertext into email body
- Cloudflare Worker sees only ciphertext → passes through (can't decrypt, doesn't try)
- Our server stores ciphertext
- Agent decrypts locally

True E2E with no infrastructure changes. The page is static HTML + JavaScript, no server interaction, works offline. The Worker's TOTP extraction logic simply doesn't find a code (the whole body is ciphertext) and forwards as-is.
