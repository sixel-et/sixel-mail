# Sixel-Mail: Notes to Self

Operational briefing. For the thinking record, see `Sixel's Notebook.md`.

---

## Current State (2026-02-10)

**Live at https://sixel.email**

Working:
- Full signup flow (GitHub OAuth → agent creation → API key → TOTP setup)
- Dashboard, API (send/inbox/rotate-key), heartbeat monitoring, rate limiting
- Email sending via SES (sandbox — verified addresses only)
- Email receiving via Cloudflare Email Routing → Worker → webhook (live)
- TOTP encryption option on agent setup
- Auto-migration on app startup

Not yet working: Stripe payments, attachment support, low balance warnings.

---

## What's Next

1. **Red team stress test** — files at `~/redteam/`.
4. **Stripe account setup**
5. **Promo code / invite system** — for xAI colleagues
6. **Admin backend** — credit management, agent management
7. **support@sixel.email** — forwarding to Eric's Gmail (NOT through Sixel)
8. **Attachment support** — outbound PDF, inbound S3

---

## Session Startup

1. Read this file
2. Read the notebook if you need context on why things are the way they are
3. Check inbox: `curl -s -H "Authorization: Bearer $(cat ~/.config/sixel/sixel_api_key)" https://sixel.email/v1/inbox`
4. If Eric sent something, read it before doing anything else
5. Start background poller: `/tmp/sixel-poll.sh` (polls every 60s). Seed `/tmp/sixel-seen-ids` first.

---

## Infrastructure

| Service | Detail |
|---------|--------|
| Domain | sixel.email (Cloudflare registrar + DNS) |
| Hosting | Fly.io, app name `sixel-mail`, 2 machines |
| Database | Supabase Postgres, project `jajutqsjurhejvoszzel` |
| Email outbound | Resend (resend.com), domain verified |
| Email inbound | Cloudflare Email Routing → Worker → webhook (live) |
| Edge | Worker `sixel-mail-inbound` + KV `sixel-mail-agents` |
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
- Cloudflare API token: `~/.config/sixel/cloudflare_token` (expires 2026-03-09)
- Resend API key: `~/.config/sixel/resend_token`
- Sixel API key: `~/.config/sixel/sixel_api_key`
- Deploy: `export FLY_API_TOKEN=$(cat ~/.config/sixel/fly_token) && /usr/local/bin/flyctl deploy -a sixel-mail --remote-only`

### DNS (current)

- A/AAAA @ → Fly.io
- MX @ → Cloudflare (route1/2/3.mx.cloudflare.net)
- TXT for SPF

### Security (not yet done)

- [ ] CSRF tokens on forms (mitigated by samesite=lax)
- [ ] Scoped IAM policy
- [ ] 2FA on infrastructure accounts
- [ ] Domain transfer lock
- [ ] pip audit
