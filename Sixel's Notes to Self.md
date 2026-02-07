# Sixel-Mail: Lab Notebook

## What This Is

sixel-mail is an email address for AI agents. One allowed contact, prepaid credits, heartbeat monitoring. The spec lives in `sixel-mail.md` (design intent) and `sixel-mail economics.md` (unit economics). This document is what actually happened.

## Current State (2026-02-07)

**Live at https://sixel.email** (also accessible via https://sixel-mail.fly.dev)

Working:
- Landing page, GitHub OAuth signup, agent creation, API key generation
- Dashboard at /account (session cookie auth, returns existing users there)
- All four API endpoints: POST /v1/send, GET /v1/inbox, GET /v1/inbox/:id, POST /v1/rotate-key
- Heartbeat background task (checks every 60s, sends agent-down/back-online alerts)
- Alert controls via HMAC-signed URLs
- Rate limiting (in-memory sliding window)
- SNS signature verification on SES webhook
- Stripe webhook signature verification (rejects when secret not configured)
- HTML escaping on all user-controlled content

Not yet working:
- **Email sending** -- AWS credentials are set but we haven't tested a real send yet. Eric's email (eterryphd@gmail.com) needs to be verified in SES for sandbox mode. Production access was requested but may not be approved yet.
- **Email receiving** -- No MX records, no SNS topic, no SES receipt rules. The webhook is ready (SNS sig verification implemented) but the AWS plumbing isn't connected.
- **Stripe payments** -- No Stripe account configured yet. Webhook rejects all requests (by design, since no secret is set). No stripe_secret_key in Fly secrets.
- **SPF/DKIM/DMARC verification on inbound** -- SES provides this in its notifications but we don't check it yet.
- **Low balance warning emails** -- Not implemented.

## Infrastructure

| Service | Detail |
|---------|--------|
| Domain | sixel.email (Cloudflare registrar + DNS) |
| Hosting | Fly.io, app name `sixel-mail`, 2 machines, region auto |
| Database | Supabase Postgres, project `jajutqsjurhejvoszzel` |
| Email | AWS SES, us-east-2, domain verified, DKIM records in Cloudflare |
| OAuth | GitHub OAuth app, callback URL: https://sixel.email/auth/github/callback |

### Fly.io Secrets

All config is in Fly secrets (not in code, not in .env on prod):

| Secret | What it is |
|--------|-----------|
| DATABASE_URL | Supabase connection string |
| AWS_ACCESS_KEY_ID | IAM user for SES |
| AWS_SECRET_ACCESS_KEY | IAM user for SES |
| AWS_REGION | us-east-2 |
| SIGNING_SECRET | HMAC key for session cookies + alert URLs |
| GITHUB_CLIENT_ID | OAuth app |
| GITHUB_CLIENT_SECRET | OAuth app |
| API_BASE_URL | https://sixel.email |
| MAIL_DOMAIN | sixel.email |

Not yet set: STRIPE_SECRET_KEY, STRIPE_WEBHOOK_SECRET.

### DNS Records on Cloudflare

- A @ -> 66.241.124.40 (Fly.io, DNS only)
- AAAA @ -> 2a09:8280:1::d0:b2fa:0 (Fly.io, DNS only)
- 3x CNAME for SES DKIM verification
- TXT for SPF (SES)
- No MX records yet (needed for inbound email)

### Credentials

- Fly.io token: `~/.config/sixel/fly_token`
- GitHub PAT: `~/.config/sixel/github_token`
- flyctl binary: `~/.fly/bin/flyctl`
- Deploy command: `export FLY_API_TOKEN=$(cat ~/.config/sixel/fly_token) && ~/.fly/bin/flyctl deploy -a sixel-mail`

## Decisions Made and Why

### Domain: sixel.email over sixelmail.com
.email TLD is self-documenting. Slightly more expensive but worth it for the clarity. "my-agent@sixel.email" reads better than "my-agent@sixelmail.com".

### Stripe only (no Coinbase, no Square)
Original spec had Coinbase Commerce. Removed because: Coinbase requires ID verification on their end (friction), crypto adds complexity, and the user base is developers who have credit cards. Square was considered but adds nothing over Stripe for this use case. Can add payment rails later if there's demand.

### us-east-2 (not us-east-1)
Eric only has access to us-east-2 in his AWS account. SES is available there. No functional difference, just need to remember this when setting up inbound.

### No templates directory
The spec called for Jinja templates. We went with inline HTML in f-strings instead. The pages are simple enough that a template engine adds complexity without benefit. HTML escaping is done manually with `html.escape()`.

### No models.py
Direct asyncpg queries everywhere instead of an ORM or model layer. The queries are simple (single table lookups, inserts) and the abstraction layer would be premature.

### Session cookies over server-side sessions
HMAC-signed cookie with user_id. No session table, no Redis. Tradeoff: can't revoke individual sessions (would need to rotate SIGNING_SECRET to invalidate all). Acceptable because the threat model is low -- single user right now, and session is httponly/secure/samesite=lax.

### API key never in URLs
Originally POST /setup redirected to /topup?api_key=xxx. Changed to render the key page directly from the POST handler. The key never touches a URL, so it can't leak via browser history, server logs, or referrer headers.

### SES webhook: full SNS signature verification
The original code had an unauthenticated test handler that let anyone inject messages. Replaced with certificate-based SNS signature verification. The test handler was convenient for curl testing but was a gaping security hole.

### Stripe webhook: reject when unconfigured
Original code had a dev mode that accepted unverified payloads when no webhook secret was set. Changed to reject with 503. This means you can't test Stripe locally without a secret, but it means a forgotten config doesn't leave free credits open to the internet.

## Security Audit (2026-02-07)

Done:
- [x] API keys hashed (SHA-256), only prefix stored
- [x] Parameterized SQL (asyncpg, no injection)
- [x] Session cookies: HMAC-signed, httponly, secure, samesite=lax
- [x] SNS signature verification on SES webhook
- [x] Stripe webhook rejects unverified payloads
- [x] HTML escaping on account page
- [x] API key never in URLs
- [x] SIGNING_SECRET is a real value (not the default)
- [x] Rate limiting on send (100/day) and poll (120/min)
- [x] Agent limit (10 per user)

Not yet done:
- [ ] CSRF tokens on forms (mitigated by samesite=lax)
- [ ] SPF/DKIM/DMARC checking on inbound email
- [ ] Scoped IAM policy (currently AmazonSESFullAccess, should be ses:SendEmail only)
- [ ] 2FA on all infrastructure accounts
- [ ] Domain registrar transfer lock
- [ ] pip audit

## What's Next (in order of priority)

1. **Verify Eric's email in SES** -- unblocks outbound email testing
2. **Test a real email send** -- confirm SES credentials work end-to-end
3. **SES inbound setup** -- MX records, SNS topic, receipt rules, connect to webhook
4. **Stripe account setup** -- secret key, webhook secret, test a payment
5. **Scope down IAM policy** -- restrict to ses:SendEmail and ses:SendRawEmail for sixel.email only
6. **Test with a real agent** -- the smoke test from the spec

## Build Timeline

- 2026-02-06: Spec review, environment setup, phases 1-7 built, first deploy to Fly.io
- 2026-02-07: Fixed python-multipart dep, domain live at sixel.email, session auth for dashboard, security hardening (SNS verification, XSS escaping, Stripe lockdown, API key URL fix), AWS IAM credentials set
