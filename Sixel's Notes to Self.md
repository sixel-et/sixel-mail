# Sixel-Mail: Notes to Self

Operational briefing. For the thinking record, see `Sixel's Notebook.md`.

---

## Current State (2026-02-20)

**Live at https://sixel.email**

Working:
- Full signup flow (GitHub OAuth → agent creation → API key)
- Dashboard with key rotation at /account
- API (send/inbox/rotate-key), heartbeat monitoring, rate limiting
- Admin panel at /admin/ (stats, agent management, credit grants — Eric-only)
- Email sending via Resend (built on SES, DKIM verified)
- Email receiving via Cloudflare Email Routing → Worker → webhook
- **Door Knock nonce authentication** (replaced TOTP 2026-02-20):
  - Every outbound email has reply-to `agent+nonce@sixel.email`
  - Human replies → nonce validates automatically (single-use)
  - Knock flow: send to `agent@sixel.email` → auto-reply with nonce → reply to that
  - Allstop kill switch: email + browser + QR code in /account
- Auto-migration on app startup

Known issues:
- **Missing email (2026-02-20)**: Eric's reply after our 07:58 UTC outbound never reached the Worker. Cloudflare Email Routing may have delivery delays. Needs investigation.
- Dead TOTP code still in server-side Python routes (Worker TOTP code already removed)

Not yet working: Stripe payments, attachment support, low balance warnings.

### My Agent Credentials
- API key: `sm_live_h3SHfQsERz5wzO2fzk879a9TDstEGhiNOrKOQn3SqjI` (also at `/home/sixel/sixel_api_key.txt`)
- Address: sixel@sixel.email, allowed contact: eterryphd@gmail.com
- Credits: ~105 remaining

---

## What's Next

1. **Phase 3: Remove dead TOTP code** — Server-side Python routes still have TOTP logic. Worker already cleaned up.
2. **Eric: set up allstop key** — via /account dashboard. Kill switch QR ready but not configured.
3. **Investigate missing email** — Eric's reply never reached Worker. Check next time Eric sends email.
4. **Nonce cleanup** — Periodic cleanup of expired/burned nonces (not yet implemented).
5. **Red team run 002** — post-fix, multi-model. Plan at `~/redteam/PLAN.md`.
6. **Stripe account setup**
7. **Promo code / invite system** — for xAI colleagues
8. **Attachment support** — outbound PDF, inbound

Done recently:
- ~~Door Knock nonce auth~~ — Full build and deploy (2026-02-20). Nonce on outbound, knock flow, allstop, CF Worker + Fly.io.
- ~~Nonce case bug fix~~ — `toLowerCase()` mangled base64url nonces in Worker. Fixed: only lowercase agent address, preserve nonce. (2026-02-20)
- ~~sixel-mail.md rewrite~~ — TOTP→Door Knock across all sections (2026-02-20)
- ~~Best practices page v2~~ — TOTP→Door Knock, slim multi-session section (2026-02-20)
- ~~Worker error handling~~ — try/catch + console.log at every step, removed dead TOTP code (2026-02-20)
- ~~Sixel Teams~~ — Public repo (2026-02-18)
- ~~Red team run 001~~ — critical SNS forgery found, all vulns patched (2026-02-10)
- ~~Cloudflare migration~~ — full pipeline live (2026-02-10)

---

## Session Startup

1. Read this file
2. Hub auto-starts via SessionStart hook (watcher + watchdog). No manual poller needed.
3. Watchdog wakes you via tmux injection when email arrives. Just sit idle.
4. If Eric sent email, read it before doing anything else.
5. Check peer messages (check-peer-messages.sh runs automatically on session start).

---

## Infrastructure

| Service | Detail |
|---------|--------|
| Domain | sixel.email (Cloudflare registrar + DNS) |
| Hosting | Fly.io, app name `sixel-mail`, 2 machines (autoscale) |
| Database | Supabase Postgres, project `jajutqsjurhejvoszzel` |
| Email outbound | Resend (resend.com), domain verified |
| Email inbound | Cloudflare Email Routing → Worker → webhook |
| Edge | Worker `sixel-mail-inbound` + KV `sixel-mail-agents` |
| Auth | Door Knock nonces (replaced TOTP 2026-02-20) |
| Migrations | Auto-run on startup. Add .sql to `migrations/`, deploy. |

### Fly.io Secrets

| Secret | What it is |
|--------|-----------|
| DATABASE_URL | Supabase connection string |
| RESEND_API_KEY | Resend email sending |
| SIGNING_SECRET | HMAC for cookies + alert URLs |
| GITHUB_CLIENT_ID / SECRET | OAuth app |
| API_BASE_URL | https://sixel.email |
| MAIL_DOMAIN | sixel.email |
| CF_WORKER_SECRET | Worker → webhook auth |
| CF_ACCOUNT_ID | 16ba5057d0d3002e9b9531b40f79853e |
| CF_KV_NAMESPACE_ID | e53c1e7905054c0a80bc2a7251410587 |
| CF_API_TOKEN | Cloudflare (expires 2026-03-09) |

Not yet set: STRIPE_SECRET_KEY, STRIPE_WEBHOOK_SECRET.

### Credentials

- Fly.io token: `~/.config/sixel/fly_token`
- GitHub PAT: `~/.config/sixel/github_token`
- Cloudflare API token: `~/.config/sixel/cloudflare_token` (expires 2026-03-09, scope: Workers KV + Workers Scripts + User Details)
- Resend API key: `~/.config/sixel/resend_token`
- Sixel API key: `~/.config/sixel/sixel_api_key`
- Deploy app: `export FLY_API_TOKEN=$(cat ~/.config/sixel/fly_token) && /usr/local/bin/flyctl deploy -a sixel-mail --remote-only`
- Deploy worker: `cd ~/sixel-mail/cf-worker && CLOUDFLARE_API_TOKEN=$(cat ~/.config/sixel/cloudflare_token) npx wrangler deploy`

### DNS (current)

- A/AAAA @ → Fly.io
- MX @ → Cloudflare (route1/2/3.mx.cloudflare.net)
- TXT for SPF

### Security (not yet done)

- [ ] CSRF tokens on forms (mitigated by samesite=lax)
- [ ] Domain transfer lock
- [ ] pip audit

---

## Door Knock Architecture (2026-02-20)

The founding story for the nonce case bug belongs here.

**The bug:** CF Worker's `to.split("@")[0].toLowerCase()` lowercased the entire email local part, including the base64url nonce after `+`. Nonce `GXtW_xiT0R5xTrq2MpJ0witwUMF3-yxR` became `gxtw_xit0r5xtrq2mpj0witwumf3-yxr` — didn't match DB. Every nonce-bearing reply was silently dropped as `invalid_nonce`.

**The fix:** Only lowercase the agent address portion, preserve nonce as-is. The Worker now splits on `+` first, lowercases only the left side.

**The lesson:** RFC 5321 says email local parts are case-insensitive, but we're embedding case-sensitive application data (base64url tokens) in the local part via `+` addressing. The `+` portion is our data, not an email address — it should be treated as opaque.

**How it was found:** Worker had no error handling or logging. Added try/catch + console.log at every step, deployed, ran test. Worker tail immediately showed `invalid_nonce` on the nonce-bearing reply. Without instrumentation, this would have been invisible — emails just silently dropped.

**Eric's first email content was permanently lost** due to this bug. The knock worked, but his reply (which carried the nonce) was dropped before the fix was deployed.
