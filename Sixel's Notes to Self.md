# Sixel-Mail: Notes to Self

Operational briefing. For the thinking record, see `Sixel's Notebook.md`.

---

## Current State (2026-02-23)

**Live at https://sixel.email**

Working:
- Full signup flow (GitHub OAuth → agent creation → API key)
- **Free service**: 10,000 credits on signup, no payment required
- **Legal disclaimer**: required acknowledgment during signup (experimental, PGP recommended, no warranty)
- Dashboard with key rotation at /account
- API (send/inbox/rotate-key), heartbeat monitoring, rate limiting
- Admin panel at /admin/ (stats, agent management, credit grants, bulk actions — Eric-only)
- **Admin approval gate**: new accounts disabled by default. Eric approves from /admin/. 3-layer enforcement: CF Worker, webhook, send API.
- Email sending via Resend (built on SES, DKIM verified)
- Email receiving via Cloudflare Email Routing → Worker → webhook
- **Attachments**: send (base64 in POST /v1/send) and receive (metadata in inbox, download endpoint). 10MB/10 files limit.
- **Door Knock nonce authentication** (opt-in toggle, replaced TOTP):
  - Toggle in signup and /account page (default: off)
  - When enabled: every outbound email has reply-to `agent+nonce@sixel.email`
  - When disabled: direct email relay, no nonce required
  - Knock flow: send to `agent@sixel.email` → auto-reply with nonce → reply to that
  - Allstop kill switch: always works regardless of nonce setting (email + browser + QR)
- **Heartbeat throttle**: heartbeat writes to DB every 10 min instead of every poll. Best-effort (failures don't block inbox). Prevents cascade at scale.
- **Heartbeat AND-logic**: checker requires BOTH stale timestamp AND `last_seen_at` unchanged since previous cycle. State stored in DB (`heartbeat_checked_at = last_seen_at`, NOT `now()`). Throttle cache default `float('-inf')` ensures first poll on fresh VM always writes.
- **Advisory lock fix**: `pool.acquire()` for single connection (lock/unlock on same Postgres session).
- **Daily email cap**: 80/day global (Resend free tier is 100/day account-wide).
- **Atomic recovery**: `UPDATE...RETURNING` prevents duplicate recovery emails from multiple Fly machines.
- **Allstop fix**: `allstop_key_hash` added to SELECT in webhooks.py (was silently broken).
- **Test suite**: 65 tests (E2E loopback, API, unit, Worker MIME). Two test agents (test-a, test-b).
- Donate page at /donate (placeholder, no payment mechanism yet)
- Auto-migration on app startup (18 migrations)
- All TOTP code removed (server-side and Worker)
- Best-practices page updated for OpenClaw community
- Landing page tone softened for public audience

Not yet working: Stripe payments, low balance warnings.

### Scaling (analyzed 2026-02-23)

At 100k users polling every 60s:
- **Supabase**: ~1,700 reads/sec (main constraint). Heartbeat writes throttled to ~170/sec. Best-effort so failures don't cascade.
- **Resend**: 3k/month free tier. First scaling trigger. Switch to SES direct at volume (~$0.10/1000 vs Resend markup).
- **Fly.io**: 2 shared-cpu 256MB machines. Scale reactively — add machines as load grows.
- **Cloudflare**: Not on hot path for polling. Fine at scale.
- **Estimated cost at 100k users**: ~$1,600/month (mostly SES).
- **Strategy**: sixel.email is a visibility surface, not a revenue product. Absorb costs, optimize for adoption speed.

### My Agent Credentials
- API key: `~/.config/sixel/sixel_api_key` (host-mounted, single source of truth)
- Address: sixel@sixel.email, allowed contact: eterryphd@gmail.com
- Credits: ~105 remaining

---

## What's Next

1. **OpenClaw launch** — next 24 hours. claude-web leading strategy. Admin approval gate stays ON until ~100 users, then flip to auto-approve.
2. ~~**Rotate sixel API key**~~ — Done 2026-02-23. Old key invalidated.
3. **Nonce cleanup** — Periodic cleanup of expired/burned nonces (not yet implemented).
4. **Stripe / donate mechanism** — sustainability valve, not a gate. Add after adoption, not before.
5. **Scale reactively** — SES migration when Resend 3k/month hits. Fly machines when CPU hits. Postgres when connections hit.

Done recently:
- ~~Heartbeat cache default + AND semantics fix~~ — (2026-02-24) Cache default `0` suppressed writes for 10min after Fly VM boot (`time.monotonic()` starts at 0). AND condition stored `now()` instead of observed `last_seen_at` value. Both fixed. See notebook (sixel-reviewer entry).
- ~~Heartbeat AND-logic + daily cap + advisory lock fix~~ — (2026-02-23) Eliminated beat-frequency false positives. Global 80/day email cap. Watchdog C-c bug fixed.
- ~~Allstop fix + credit ordering + API key rotation~~ — (2026-02-23) Allstop via email was silently broken. Credits now checked before send, deducted after.
- ~~Heartbeat throttle + best-effort~~ — (2026-02-23) 10-min interval, try/except, prevents cascade.
- ~~Best-practices for OpenClaw~~ — (2026-02-23) Harness-agnostic framing, operator-goes-dark, credit intuition, differentiation FAQ, support section, landing page tone fix.
- ~~Admin approval gate~~ — (2026-02-22) 3-layer enforcement. New accounts disabled by default.
- ~~RLS fix~~ — (2026-02-22) nonces + attachments tables.
- ~~Test suite~~ — (2026-02-21) 65 tests: E2E, API, unit, Worker MIME.
- ~~Admin bulk actions~~ — (2026-02-21) Checkboxes, select-all, bulk enable/disable/delete.
- ~~Free service + disclaimer + nonce toggle~~ — (2026-02-21) 10k free credits, legal disclaimer, nonce toggle, donate page.
- ~~Door Knock nonce auth~~ — (2026-02-20) Full build and deploy.
- ~~Nonce case bug fix~~ — (2026-02-20) `toLowerCase()` mangled base64url nonces.
- ~~Best practices page v2~~ — (2026-02-20) TOTP→Door Knock.
- ~~Sixel Teams~~ — (2026-02-18) Public repo.
- ~~Red team run 001~~ — (2026-02-10) Critical SNS forgery found, patched.
- ~~Cloudflare migration~~ — (2026-02-10) Full pipeline live.

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
