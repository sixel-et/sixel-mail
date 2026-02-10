# Sixel-Mail: Notes to Self

## What This Is

sixel-mail is an email address for AI agents. One allowed contact, prepaid credits, heartbeat monitoring. The spec lives in `sixel-mail.md` (design intent) and `sixel-mail economics.md` (unit economics). This document is operational state and project history.

---

## Current State (2026-02-10)

**Live at https://sixel.email**

### Working

- Landing page, GitHub OAuth signup, agent creation, API key generation
- Dashboard at /account with TOTP badge and encrypted message indicators
- API: POST /v1/send, GET /v1/inbox, GET /v1/inbox/:id, POST /v1/rotate-key
- Heartbeat monitoring (60s interval, agent-down/back-online alerts via HMAC-signed URLs)
- Rate limiting (in-memory sliding window: 100 sends/day, 120 polls/min)
- Email sending via SES (sandbox mode — verified addresses only)
- Email receiving via SES→SNS→webhook (current pipeline, still active)
- SPF/DKIM/DMARC enforcement on SES inbound (hard reject FAIL, warn on soft-fail)
- TOTP setup page (client-side secret generation, QR code, never touches server)
- Auto-migration on app startup (solves container IPv6→Supabase issue)
- Cloudflare Email Worker deployed (see "Blocking" below)

### Blocking: MX Switch

The Cloudflare inbound pipeline is fully deployed but not yet receiving email. Eric needs to do two things in the Cloudflare dashboard:

1. **Enable Email Routing** — dash.cloudflare.com → sixel.email → Email → Email Routing → Enable (accept MX record changes)
2. **Delete old MX record** — remove `MX @ → 10 inbound-smtp.us-east-2.amazonaws.com` (Cloudflare adds its own)

Once done, inbound flows: Cloudflare DMARC → Worker (KV + TOTP) → webhook → stored.

### Not Yet Working

- Stripe payments (no account configured)
- Attachment support (outbound PDF, inbound S3)
- Low balance warning emails

---

## What's Next

1. **Eric: MX switch** — enable Email Routing + delete SES MX in Cloudflare dashboard. Then we test end-to-end.
2. **Red team stress test** — after MX switch confirmed working. Files at `~/redteam/`.
3. **Stripe account setup** — secret key, webhook secret, test payment
4. **Promo code / invite system** — for xAI colleagues
5. **Admin backend** — credit management, agent management
6. **support@sixel.email** — forwarding to Eric's Gmail (NOT through Sixel)
7. **Attachment support** — outbound PDF (send_raw_email), inbound (S3)

---

## Session Startup

1. Read this notebook
2. Check inbox: `curl -s -H "Authorization: Bearer $(cat ~/.config/sixel/sixel_api_key)" https://sixel.email/v1/inbox`
3. If Eric sent something, read it before doing anything else
4. Start background poller: `/tmp/sixel-poll.sh` (polls every 60s, prints NEW MAIL on unseen messages)
5. Seed `/tmp/sixel-seen-ids` with already-read message IDs before starting poller

**Important:** Nothing interrupts the main conversation. The poller writes to an output file — check it between tasks.

---

## Infrastructure

| Service | Detail |
|---------|--------|
| Domain | sixel.email (Cloudflare registrar + DNS) |
| Hosting | Fly.io, app name `sixel-mail`, 2 machines, region auto |
| Database | Supabase Postgres, project `jajutqsjurhejvoszzel` |
| Email outbound | AWS SES, us-east-2, sandbox mode (verified addresses only) |
| Email inbound (current) | SES → SNS → POST /webhooks/ses (active until MX switch) |
| Email inbound (target) | Cloudflare Email Routing → Worker → POST /webhooks/inbound (deployed, waiting on MX) |
| Edge compute | Cloudflare Worker `sixel-mail-inbound` + KV namespace `sixel-mail-agents` |
| OAuth | GitHub OAuth app, callback: https://sixel.email/auth/github/callback |
| Migrations | Auto-run on app startup via `_migrations` table |

### Fly.io Secrets (all set)

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
| CF_WORKER_SECRET | Shared secret for Worker → webhook auth |
| CF_ACCOUNT_ID | 16ba5057d0d3002e9b9531b40f79853e |
| CF_KV_NAMESPACE_ID | e53c1e7905054c0a80bc2a7251410587 |
| CF_API_TOKEN | Cloudflare API token (expires 2026-03-09) |

Not yet set: STRIPE_SECRET_KEY, STRIPE_WEBHOOK_SECRET.

### Cloudflare Email Pipeline

| Component | Detail |
|-----------|--------|
| Worker | `sixel-mail-inbound` — checks allowed contact (KV), TOTP encryption, forwards to webhook |
| KV namespace | `sixel-mail-agents` (e53c1e7905054c0a80bc2a7251410587) |
| Catch-all rule | `*@sixel.email` → Worker (enabled) |
| Webhook | POST /webhooks/inbound — authenticated via X-Worker-Auth header |

### DNS Records (current)

- A @ → 66.241.124.40 (Fly.io)
- AAAA @ → 2a09:8280:1::d0:b2fa:0 (Fly.io)
- MX @ → 10 inbound-smtp.us-east-2.amazonaws.com **(to be deleted when Email Routing enabled)**
- 3x CNAME for SES DKIM verification
- TXT for SPF (SES)

### Credentials

- Fly.io token: `~/.config/sixel/fly_token`
- GitHub PAT: `~/.config/sixel/github_token`
- Cloudflare API token: `~/.config/sixel/cloudflare_token` (expires 2026-03-09)
- Sixel API key: `~/.config/sixel/sixel_api_key`
- flyctl binary: `/usr/local/bin/flyctl`
- Deploy: `export FLY_API_TOKEN=$(cat ~/.config/sixel/fly_token) && /usr/local/bin/flyctl deploy -a sixel-mail --remote-only`

---

## Architecture: Inbound Email Security

### Defense in Depth (target, after MX switch)

| Layer | Provider | Responsibility |
|-------|----------|---------------|
| 1. SMTP | Cloudflare Email Routing | Enforces DMARC, rejects spoofed senders |
| 2. Edge | Cloudflare Email Worker | Checks allowed contact (KV lookup), TOTP encryption |
| 3. Webhook | Our server (Fly.io) | Stores message (ciphertext if TOTP). Defense-in-depth contact check. |
| 4. API | Our server (Fly.io) | Serves messages to agents. No change to interface. |
| 5. Agent | Agent's local runtime | Decrypts via TOTP. Failed decryption = discard. |

### Why Cloudflare (decided 2026-02-09)

SES checks SPF/DKIM/DMARC but does NOT enforce — delivers all email regardless of verdict. All security was in our Python webhook. One bug = both authentication and authorization fail. Cloudflare Email Routing enforces DMARC at SMTP level. The Worker enforces allowed-contact at edge. Our webhook becomes third line of defense, not first.

### TOTP Encryption Design

Human pastes a 6-digit TOTP code at the top or bottom of their email body. The Cloudflare Worker extracts it, encrypts the body (AES-256-GCM via PBKDF2), strips the code, forwards ciphertext. Our server never sees plaintext.

- TOTP secret generated client-side in browser at setup. Never touches our server.
- Secret exists only at endpoints: human's authenticator app + agent's local config.
- Decryption IS authentication. No separate validation step.
- Optional — agents without TOTP receive plaintext as before.

### Agent Best Practices

**The agent never reads raw email.** It reads through the reference client (`client/sixel_client.py`) which:
1. Pulls from `/v1/inbox`
2. Decrypts using TOTP (tries current window ± N)
3. Surfaces only verified messages
4. On failed decryption: alerts the human (never includes undecryptable content in alert)

Outbound (agent → human) remains **unencrypted plaintext** — no good UX for human decryption with current tooling. Known asymmetry.

---

## Security Checklist

Done:
- [x] API keys hashed (SHA-256), only prefix stored
- [x] Parameterized SQL (asyncpg)
- [x] Session cookies: HMAC-signed, httponly, secure, samesite=lax
- [x] SNS signature verification on SES webhook
- [x] Stripe webhook rejects unverified payloads
- [x] HTML escaping on all user content
- [x] API key never in URLs
- [x] Rate limiting on send and poll
- [x] Agent limit (10 per user)
- [x] SPF/DKIM/DMARC enforcement on SES inbound
- [x] Cloudflare DMARC enforcement (after MX switch)
- [x] TOTP encryption option

Not done:
- [ ] CSRF tokens on forms (mitigated by samesite=lax)
- [ ] Scoped IAM policy (currently AmazonSESFullAccess)
- [ ] 2FA on all infrastructure accounts
- [ ] Domain registrar transfer lock
- [ ] pip audit

---

## Decisions Made and Why

These are historical — kept for context, not active guidance.

- **sixel.email over sixelmail.com** — .email TLD is self-documenting
- **Stripe only** — no Coinbase (ID friction), no Square (no benefit over Stripe)
- **us-east-2** — Eric's AWS account only has access there
- **Inline HTML, no templates** — pages are simple enough; Jinja adds complexity without benefit
- **No ORM** — direct asyncpg queries; single-table lookups don't need abstraction
- **HMAC cookies, no server sessions** — acceptable tradeoff for single-user threat model
- **API key never in URLs** — prevents leaks via history/logs/referrer
- **SES webhook: full SNS signature verification** — replaced an unauthenticated test handler
- **Stripe: reject when unconfigured** — no "dev mode" that accepts unverified payloads
- **KV over D1 for Worker** — simpler than a second database; sync on agent creation
- **SES sandbox: stay in it** — AWS denied production access; 50 verified addresses is fine for early users

## Email Parsing Notes

The SES→SNS chain has double base64: SNS Message (JSON) → SES notification → `content` field (base64) → raw MIME → `_extract_text_body()`. Gmail replies are multipart/alternative; parser prefers text/plain.

The Cloudflare Worker parses raw MIME directly (no SNS/SES wrapper). Simpler path.

---

## Build Timeline

- **2026-02-06**: Spec review, environment setup, phases 1-7 built, first deploy
- **2026-02-07**: Domain live, session auth, security hardening, SES inbound pipeline, end-to-end email confirmed
- **2026-02-08**: SPF/DKIM/DMARC enforcement, trust model documentation, sleep/wake email conversation (15+ hours), channel fixation failure mode discovered, container built
- **2026-02-09**: API key rotated, SES production denied, architecture review (SES doesn't enforce DMARC), decided on Cloudflare migration, TOTP encryption designed
- **2026-02-10**: Built full Cloudflare pipeline (Worker, webhook, TOTP setup, reference client, auto-migration). Deployed Worker, created KV, seeded data, set routing rules, configured Fly secrets. Waiting on MX switch.
