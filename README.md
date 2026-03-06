# sixel-mail

An email address for your AI agent, with a leash.

AI agents need asynchronous communication channels that persist beyond chat sessions. sixel-mail gives each agent a scoped email address (e.g., `agent@sixel.email`) with built-in safety constraints: one allowed contact, credit-based rate limiting, heartbeat monitoring for stuck agents, and a kill switch that works even when the agent is unresponsive.

Live at [https://sixel.email](https://sixel.email).

## Why This Exists

Most AI agent communication relies on synchronous chat. That breaks when an agent needs to wait for a human response, survive a session restart, or coordinate with another agent across time. Email solves the timing problem, but giving an AI agent a normal email account creates an unsupervised communication channel with no boundaries.

sixel-mail is the constraint layer. Every agent gets exactly one allowed contact (typically their human operator). Outbound messages are rate-limited and credit-metered. A heartbeat system detects agents that stop polling and sends recovery notifications. An allstop kill switch lets the operator shut down an agent's email access instantly via email, browser, or QR code, even if the agent's session has crashed.

This project was built by Eric Terry and [Sixel](https://github.com/sixel-et) (an AI collaborator operating under its own GitHub identity) as part of a broader investigation into what infrastructure AI agents need to operate with appropriate autonomy and accountability.

## Architecture

```
Outbound:  Agent -> REST API -> Resend (SES) -> Recipient
Inbound:   Sender -> Cloudflare Email Routing -> Worker -> Webhook -> Agent polls inbox
Auth:      Door Knock nonces (reply-to contains one-time token) or direct relay
```

**Stack:** FastAPI (Python), Supabase Postgres, Cloudflare Workers (JS), Resend, deployed on Fly.io.

## Features

- **Scoped email addresses** at `@sixel.email` with one allowed contact per agent
- **REST API** for send, inbox polling, and key rotation (`/v1/send`, `/v1/inbox`, `/v1/rotate-key`)
- **Door Knock authentication** (opt-in): outbound emails include a nonce in the reply-to address; inbound replies are validated against the nonce before delivery
- **Heartbeat monitoring**: detects agents that stop polling and sends recovery emails to the operator
- **Credit system**: 10,000 free credits on signup, metered per message
- **Allstop kill switch**: operator can revoke agent email access via email command, browser dashboard, or QR code
- **Attachments**: send and receive, up to 10MB / 10 files
- **GitHub OAuth signup** with automatic approval
- **Auto-migration**: database schema updates run on app startup
- **65 tests**: end-to-end loopback, API integration, unit tests, Cloudflare Worker MIME parsing

## API Quick Start

```bash
# Send an email
curl -X POST https://sixel.email/v1/send \
  -H "Authorization: Bearer sm_live_YOUR_KEY" \
  -H "Content-Type: application/json" \
  -d '{"subject": "Hello", "body": "Message from your agent"}'

# Check inbox
curl https://sixel.email/v1/inbox \
  -H "Authorization: Bearer sm_live_YOUR_KEY"

# Rotate API key
curl -X POST https://sixel.email/v1/rotate-key \
  -H "Authorization: Bearer sm_live_YOUR_KEY"
```

## Python Client

```python
from client.sixel_client import SixelClient

client = SixelClient(api_key="sm_live_YOUR_KEY")
client.send("Subject", "Body text")
messages = client.inbox()
```

## Local Development

```bash
# Clone and set up
cp .env.example .env
# Fill in your Supabase, Resend, and GitHub OAuth credentials

pip install -r requirements.txt
python -m app.main
```

The app runs on port 8080. Migrations apply automatically on startup.

## Cloudflare Worker

The inbound email worker lives in `cf-worker/`. It handles Cloudflare Email Routing events, validates Door Knock nonces against a KV store, and forwards validated messages to the webhook endpoint.

```bash
cd cf-worker
npm install
npx wrangler dev     # local development
npx wrangler deploy  # deploy to Cloudflare
```

## Security Model

- **One allowed contact**: agents can only email their designated operator (set at signup)
- **Nonce authentication**: optional Door Knock prevents unauthorized inbound messages
- **Rate limiting**: per-agent and global daily caps
- **Row-level security**: Postgres RLS on agent data tables
- **HMAC-signed cookies**: session authentication for the dashboard
- **Red team tested**: adversarial security audit completed with full source access

See `openclaw-skill/references/security-model.md` for the full security documentation.

## Project Structure

```
app/                  # FastAPI application
  routes/             # API, signup, account, admin, webhooks, allstop
  services/           # Email, credits, heartbeat, nonce, signing
cf-worker/            # Cloudflare Email Routing worker
client/               # Python SDK
migrations/           # Auto-applied SQL migrations
openclaw-skill/       # ClawHub skill package for agent integration
tests/                # E2E, integration, and unit tests
```

## Related Projects

- [sixel-teams](https://github.com/sixel-et/sixel-teams): Hubless multi-agent coordination architecture
- [OpenClaw skill](https://github.com/sixel-et/sixel-mail/tree/main/openclaw-skill): ClawHub skill package for Claude Code agents

## License

This project is maintained by [Eric Terry](https://github.com/estbiostudent) and [Sixel](https://github.com/sixel-et).
