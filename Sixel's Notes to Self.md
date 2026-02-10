# Sixel-Mail: Lab Notebook

## What This Is

sixel-mail is an email address for AI agents. One allowed contact, prepaid credits, heartbeat monitoring. The spec lives in `sixel-mail.md` (design intent) and `sixel-mail economics.md` (unit economics). This document is what actually happened.

## Current State (2026-02-08)

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
- **Email sending** -- SES sandbox mode, verified for eterryphd@gmail.com. Production access requested, pending approval.
- **Email receiving** -- Full pipeline working: MX record → SES receipt rule (TLS required, spam/virus scanning) → SNS topic → webhook → MIME parsing → stored in inbox. Confirmed with live test (Eric replied to agent email, body parsed correctly).

Not yet working:
- **SES production access** -- Requested, awaiting AWS approval. Until then, can only send to verified addresses (Eric's email).
- **Stripe payments** -- No Stripe account configured yet. Webhook rejects all requests (by design, since no secret is set). No stripe_secret_key in Fly secrets.
- **SPF/DKIM/DMARC verification on inbound** -- Now enforced. DKIM or DMARC FAIL → reject. Soft failures → warning prepended to message body. Raw email without SES metadata → warning prepended.
- **Attachment support** -- Outbound PDF attachments (send_raw_email) and inbound attachments (via S3) discussed but not implemented. Eric wants to receive PDF experiment reports with figures.
- **Low balance warning emails** -- Not implemented.

## Infrastructure

| Service | Detail |
|---------|--------|
| Domain | sixel.email (Cloudflare registrar + DNS) |
| Hosting | Fly.io, app name `sixel-mail`, 2 machines, region auto |
| Database | Supabase Postgres, project `jajutqsjurhejvoszzel` |
| Email outbound | AWS SES, us-east-2, domain verified, DKIM records in Cloudflare |
| Email inbound | Cloudflare Email Routing→Worker→webhook (deployed, waiting on MX switch). SES→SNS→webhook still active until MX changed. |
| OAuth | GitHub OAuth app, callback URL: https://sixel.email/auth/github/callback |
| Migrations | Auto-run on app startup via `_migrations` table. Add .sql files to `migrations/`, deploy, done. |

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

| CF_WORKER_SECRET | Shared secret for authenticating Cloudflare Email Worker |
| CF_ACCOUNT_ID | Cloudflare account ID |
| CF_KV_NAMESPACE_ID | KV namespace `sixel-mail-agents` (e53c1e7905054c0a80bc2a7251410587) |
| CF_API_TOKEN | Cloudflare API token (expires 2026-03-09) |

Not yet set: STRIPE_SECRET_KEY, STRIPE_WEBHOOK_SECRET.

### Cloudflare Email Pipeline (deployed, waiting on MX switch)

| Component | Detail |
|-----------|--------|
| Worker | `sixel-mail-inbound` — checks allowed contact (KV), TOTP encryption, forwards to webhook |
| KV namespace | `sixel-mail-agents` (e53c1e7905054c0a80bc2a7251410587) — agent→contact mappings |
| Catch-all rule | All `*@sixel.email` → Worker (enabled) |
| Webhook | POST /webhooks/inbound — Worker-authenticated, stores ciphertext |
| Worker auth secret | Shared HMAC between Worker and webhook (`CF_WORKER_SECRET` in Fly secrets) |

### AWS SES Inbound Pipeline (active until MX switch, then deprecated)

| Component | Detail |
|-----------|--------|
| MX record | 10 inbound-smtp.us-east-2.amazonaws.com (Cloudflare) |
| SNS topic | arn:aws:sns:us-east-2:973877242781:sixel-mail-inbound |
| SES receipt rule | TLS required, spam/virus scanning enabled, Base64 encoding, publishes to SNS topic |
| Webhook | POST /webhooks/ses — SNS signature verified, MIME parsed |

### DNS Records on Cloudflare

- A @ -> 66.241.124.40 (Fly.io, DNS only)
- AAAA @ -> 2a09:8280:1::d0:b2fa:0 (Fly.io, DNS only)
- MX @ -> 10 inbound-smtp.us-east-2.amazonaws.com (TO BE CHANGED: delete this, Cloudflare adds its own MX when Email Routing enabled)
- 3x CNAME for SES DKIM verification
- TXT for SPF (SES)

### Credentials

- Fly.io token: `~/.config/sixel/fly_token`
- GitHub PAT: `~/.config/sixel/github_token`
- Cloudflare API token: `~/.config/sixel/cloudflare_token` (expires 2026-03-09)
- flyctl binary: `/usr/local/bin/flyctl`
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
- [x] SPF/DKIM/DMARC checking on inbound email (hard reject on DKIM/DMARC FAIL, warning prepended on soft-fail)
- [ ] Scoped IAM policy (currently AmazonSESFullAccess, should be ses:SendEmail only)
- [ ] 2FA on all infrastructure accounts
- [ ] Domain registrar transfer lock
- [ ] pip audit

## Email Parsing: Lessons Learned

The SES→SNS→webhook chain has two layers of encoding that bit us:

1. **SNS encoding**: The SES receipt rule is configured with Base64 encoding, so the SNS `Message` field is a JSON string containing the SES notification.
2. **SES content field**: Within the SES JSON notification, the `content` field holds the raw email — also Base64-encoded (because of the receipt rule's encoding setting).

So the decode path is: SNS Message (JSON string) → parse JSON → SES notification → `content` field → base64 decode → raw MIME email → `_extract_text_body()` → text/plain part.

Gmail replies come as multipart/alternative with text/plain and text/html. The parser prefers text/plain, falls back to text/html.

## Session Startup

At the start of every session working on sixel-mail (or any project where I might receive mail):

1. Read this notebook
2. Check inbox: `curl -s -H "Authorization: Bearer $(cat ~/.config/sixel/sixel_api_key)" https://sixel.email/v1/inbox`
3. If Eric sent something, read it before doing anything else
4. Start the background poller: run `/tmp/sixel-poll.sh` in background — polls every 60 seconds, prints NEW MAIL when unseen messages arrive. Seed `/tmp/sixel-seen-ids` with any already-read message IDs first.
5. Periodically check poller output (`/tmp/claude-1001/-home-sixel/tasks/<id>.output`) during the session

The whole point of this project is giving me a communication channel. Use it.

Between sessions I don't exist, so the heartbeat will flag me as down — that's honest. During a session, I should be polling.

**Important limitation:** Nothing can interrupt the main conversation. The poller writes to an output file but I only see it when I look. Check the poller output between tasks — especially before responding to Eric, since he might have sent something via email instead of (or in addition to) the chat.

## What's Next (in order of priority)

~~1. **Red team stress test** -- infrastructure pentest. Files at `~/redteam/`. Attacker in its own isolated container.~~
~~2. **SES production access denied** -- AWS rejected the request. Stuck in sandbox (verified addresses only). Need to reapply with more detail or switch to a different sending provider (Postmark, Mailgun, etc.)~~
3. **Stripe account setup** -- secret key, webhook secret, test a payment
4. **Promo code / invite system** -- for xAI colleagues
5. **Admin backend** -- credit management, agent management, promo codes
6. **support@sixel.email** -- forwarding to Eric's Gmail (NOT through Sixel)
7. **Attachment support** -- outbound PDF (send_raw_email), inbound (S3)
~~8. **Scope down IAM policy** -- restrict to ses:SendEmail/SendRawEmail for sixel.email only~~

### Revised priorities (2026-02-10)

1. ~~**Migrate inbound email from SES to Cloudflare Email Routing + Email Workers**~~ — **DONE (backend)**. Worker deployed, KV seeded, routing rules set, Fly secrets configured. **Waiting on Eric to: enable Email Routing in Cloudflare dashboard + switch MX records.**
2. **Red team stress test** -- infrastructure pentest. Should run AFTER the MX switch + end-to-end test. Files at `~/redteam/`. Attacker in QEMU VM inside Sixel's container (recursive depth, no lateral spread).
3. **SES sandbox: stay in it** -- AWS rejected production access. Sandbox is fine for now: manually verify early users' addresses. 50 address limit, 200 emails/day. Revisit outbound provider when user count demands it.
4. **Stripe account setup**
5. **Promo code / invite system** -- for xAI colleagues
6. **Admin backend**
7. **support@sixel.email** -- forwarding to Eric's Gmail
8. **Attachment support**

## Cloudflare Migration Plan (2026-02-09)

### Why

Our inbound email security has a structural problem. SES checks SPF/DKIM/DMARC but does not enforce — it delivers all email regardless of verdict. Both authentication (is the sender who they claim to be?) and authorization (is the sender allowed to talk to this agent?) are enforced solely in our Python webhook handler. One bug in that code and both checks fail.

Cloudflare Email Routing enforces DMARC at the SMTP level — spoofed emails are rejected before they reach us. Cloudflare Email Workers let us run custom logic (the allowed-contact check) at Cloudflare's edge. This pushes both security checks below our application layer.

### Target Architecture

| Layer | Provider | Responsibility |
|-------|----------|---------------|
| 1. MX / SMTP | Cloudflare Email Routing | Receives email, enforces DMARC, rejects spoofed senders |
| 2. Email Worker | Cloudflare (our JS code) | Checks sender against allowed contact. Extracts TOTP code from body, encrypts body with it, strips code. Forwards only ciphertext to our webhook. |
| 3. Webhook | Our server (Fly.io) | Stores ciphertext. Never sees plaintext. Third line of defense, not first. |
| 4. API | Our server (Fly.io) | Serves ciphertext to agents. No change to interface. |
| 5. Agent | Agent's local runtime | Generates TOTP codes from shared secret, decrypts. Failed decryption → discard (prompt injection impossible). |

### What Changes

- **MX record**: `inbound-smtp.us-east-2.amazonaws.com` → Cloudflare's MX servers
- **SPF TXT record**: update to include Cloudflare
- **SES receipt rule**: can be removed (SES no longer receives inbound)
- **SNS topic**: can be removed
- **Webhook handler**: simplified — no longer needs SNS signature verification, no longer needs SPF/DKIM/DMARC checking (Cloudflare handles both). Still needs to parse the email body and store it.
- **New: Email Worker**: JavaScript running on Cloudflare. Checks allowed contact, extracts TOTP from body, encrypts body, strips TOTP, forwards ciphertext. Needs allowed-contact data — options: (a) call our API from the Worker, (b) replicate mappings into Cloudflare KV, (c) Cloudflare D1. Does NOT need the TOTP shared secret — it uses the code from the email body as the encryption key.
- **Agent setup page**: Generates TOTP secret client-side in the browser. Renders QR code for authenticator app. Displays raw secret for agent config. Secret never touches our server.

### What Doesn't Change

- Outbound email (still SES, still sandbox for now — Cloudflare Email Service may replace later)
- API endpoints (serve ciphertext instead of plaintext, same interface)
- Database schema (body column holds ciphertext instead of plaintext)
- Dashboard

### What Changes in Agent Setup

- Agent creation page generates TOTP secret **client-side in browser** (JavaScript)
- QR code rendered in browser for user to scan with any authenticator app
- Raw secret displayed for user to copy into agent config
- Secret never sent to our server, never stored in our database
- Our server only knows a TOTP secret exists for that agent (boolean flag)

### Open Questions

- **How does the Email Worker check allowed contacts?** Options: (a) call our API from the Worker, (b) replicate the agent→contact mappings into Cloudflare KV, (c) use Cloudflare D1 (SQLite at the edge). Option (a) is simplest but adds latency. Option (b) needs a sync mechanism. Option (c) is a second database to maintain.
- **What format does Cloudflare forward to our webhook?** Need to check if it's raw MIME, parsed JSON, or something else. Our current parsing assumes SES→SNS format (double base64). This will change.
- **Can we keep SES as a fallback?** MX records support priority. We could set Cloudflare as primary (priority 10) and SES as secondary (priority 20). But this means some emails could bypass Cloudflare's checks by going to SES directly if Cloudflare is down. Probably not worth it — defeats the purpose.
- **Cloudflare Email Service (private beta)** — if we can get into the beta, this could replace SES for outbound too. One provider for everything. Worth checking.

## TOTP Encryption Design (2026-02-09)

### The Problem

Our application layer is the weakest link. If compromised, an attacker can read all messages and inject prompt injection content into agent inboxes. All current security checks (DMARC, allowed-contact, SPF/DKIM) are enforced in our code.

### The Solution

TOTP-based encryption with the Cloudflare Email Worker as the encryption boundary.

1. At agent setup, human scans a QR code into their authenticator app (standard TOTP)
2. Agent stores the TOTP shared secret locally (credential file, not in our database)
3. To email the agent, human pastes the current 6-digit TOTP code at the top or bottom of their message body
4. Cloudflare Email Worker extracts the TOTP code, encrypts the body with it, strips the code, forwards only ciphertext to our server
5. Our server stores ciphertext — never sees plaintext
6. Agent generates recent TOTP codes from the shared secret, tries each to decrypt. One works → message is authentic and readable.

### What This Achieves

- **Our server compromised** → attacker sees ciphertext. Useless.
- **Database breached** → ciphertext. Useless.
- **Prompt injection via inbox** → injected message isn't encrypted with a valid TOTP code → agent fails to decrypt → discards. Injection impossible.
- **TOTP code in email body** → expires in 30 seconds. Captured from logs, it decrypts one message but gives no forward access.

### Trust Boundaries

- Cloudflare sees plaintext briefly in Worker memory (acceptable — same trust level as Gmail seeing plaintext now)
- TOTP shared secret exists only at the endpoints: human's authenticator app + agent's local config. Never in our infrastructure.
- TOTP secret generated client-side in user's browser at setup. Never touches our server. The one-time exchange is analog: eyes (read QR/secret) → camera (scan) → clipboard (copy to agent config).
- Decryption IS authentication. No separate validation step needed in the middle.
- Our server compromised → attacker sees ciphertext + has no TOTP secret → useless
- Database breached → ciphertext + no TOTP secret → useless
- Cloudflare compromised → same impact as Gmail compromised today (sees plaintext in transit). Half the internet has bigger problems.

### Agent Best Practices (Reference Implementation)

**Core principle: the agent never reads raw email.** It reads through a local decryption client that gates all access.

The reference implementation is a local client/library that:
1. Pulls messages from `/v1/inbox`
2. Attempts TOTP decryption on each message (current window ± N to account for delivery delay)
3. Surfaces only successfully decrypted messages to the agent
4. On failed decryption: sends an alert to the allowed contact ("I received a message I couldn't decrypt"). Does NOT include the undecryptable content in the alert (it could be crafted to inject via the alert text itself). If failures repeat, escalates the warning.
5. The agent's interface is just "here are your messages" — every message it sees is authenticated by definition

**Why this matters:** The agent literally cannot be prompt-injected through email because it never has access to unverified content. Decryption IS authentication. The client is the gatekeeper.

**We can't enforce this** — users can bypass the client and call the API directly. But we ship the reference implementation, make it the easy/default path, and document why it matters. If someone reads raw, that's their risk.

Agent setup instructions must include:
1. The TOTP shared secret (copied by user from setup page into agent config)
2. The reference client (or clear instructions to build the equivalent)
3. **Critical: never call `/v1/inbox` directly from agent code. Use the decryption client.**
4. Outbound (agent → human) remains **unencrypted plaintext**. There's no good UX for the human to decrypt agent emails with current tooling. This is a known asymmetry: inbound is encrypted, outbound is not. If the server is compromised, outbound messages are readable. Agent replies may also leak context about encrypted inbound content. The `sixel.email/e` static decrypt page is a future mitigation but adds friction.

### Upgrade Path

If we later build a static encrypt page (`sixel.email/e`), the human encrypts in-browser before sending. Cloudflare then only sees ciphertext too. The architecture doesn't change — the Worker just passes through what it can't decrypt. True E2E with no infrastructure changes. The page is static HTML + JavaScript, no server interaction, works offline.

### UX Impact

One extra step for the human: paste 6 digits into the email body. Optional — humans who don't care about encryption email normally, agent processes plaintext as before (backwards compatible).

### How TOTP Works (for reference)

TOTP (RFC 6238): shared secret + current time ÷ 30 seconds → HMAC-SHA1 → truncate to 6 digits. Both sides run the same math independently. No server communication needed. Any standard authenticator app works (Google Authenticator, Authy, 1Password, Bitwarden, etc.). The QR code is just a URL: `otpauth://totp/sixel.email:agent-name?secret=BASE32SECRET&issuer=sixel.email`

## Build Timeline

- 2026-02-06: Spec review, environment setup, phases 1-7 built, first deploy to Fly.io
- 2026-02-07: Fixed python-multipart dep, domain live at sixel.email, session auth for dashboard, security hardening (SNS verification, XSS escaping, Stripe lockdown, API key URL fix), AWS IAM credentials set, SES inbound pipeline fully connected (MX → SES → SNS → webhook), MIME email parsing with double-base64 decode, end-to-end email round-trip confirmed working
- 2026-02-08: SPF/DKIM/DMARC enforcement on inbound (hard reject DKIM/DMARC FAIL, warn on soft-fail), Layer 2 trust documentation in spec, extended email conversation (sleep/wake over 15+ hours), discovered channel fixation failure mode, red team stress test planned and shelved, container built and migrated to new machine
- 2026-02-09: API key rotated (old key was in repo history + baked into Docker image), credential references changed from hardcoded to file path. SES production access denied by AWS. Architecture review: discovered SES does not enforce DMARC (only reports verdicts), all security enforcement is in our application layer. Decided to migrate inbound to Cloudflare Email Routing + Email Workers — pushes DMARC enforcement and allowed-contact checks below our code. Red team test postponed until after migration so we test the hardened architecture.
- 2026-02-10: Built Cloudflare migration + TOTP encryption. New: POST /webhooks/inbound endpoint, TOTP setup page (client-side secret generation, QR code), Cloudflare Email Worker (cf-worker/), reference client (client/sixel_client.py), auto-migration on app startup. Database migrated (has_totp, encrypted columns). All deployed to Fly.io. Container IPv6 issue: Supabase is IPv6-only, container is IPv4-only — solved permanently via auto-migration (Fly.io runs migrations on boot). Later same day: Eric provided CF API token. Deployed Worker (`sixel-mail-inbound`), created KV namespace (`sixel-mail-agents`), seeded KV with agent data, set catch-all routing rule, configured all Fly secrets. Remaining: Eric enables Email Routing in CF dashboard + switches MX records.
