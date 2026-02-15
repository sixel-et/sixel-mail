# Sixel-Mail: Notes to Self

Operational briefing. For the thinking record, see `Sixel's Notebook.md`.

---

## Current State (2026-02-12)

**Live at https://sixel.email**

Working:
- Full signup flow (GitHub OAuth → agent creation → API key → TOTP setup)
- Dashboard with key rotation + TOTP enable/disable
- API (send/inbox/rotate-key), heartbeat monitoring, rate limiting
- Admin panel at /admin/ (stats, agent management, credit grants — Eric-only)
- Email sending via Resend (built on SES, DKIM verified)
- Email receiving via Cloudflare Email Routing → Worker → webhook (live)
- TOTP encryption: end-to-end tested, encrypts and decrypts successfully
- Client rejects unencrypted messages when TOTP is enabled (defense-in-depth)
- Auto-migration on app startup

Partially working:
- **Worker TOTP rejection**: Code written but NOT deployed — Eric needs to run `cd ~/sixel-mail/cf-worker && npx wrangler deploy`. My CF token doesn't have Worker deploy scope.
- **TOTP code extraction**: Currently checks first/last line of email body. Breaks with Gmail reply quoting (quoted text appears after the code, pushing it to the middle). Eric said "we'll have to rethink."
- **TOTP UX rethink (2026-02-14)**: Eric emailed "Current Email is crap." Exploring alternatives: FlowCrypt (PGP on Android + Chrome extension), dropping TOTP in favor of pipeline security (DMARC + one-allowed-contact), or S/MIME. Decision pending.

Not yet working: Stripe payments, attachment support, low balance warnings.

### My Agent Credentials
- API key: `sm_live_h3SHfQsERz5wzO2fzk879a9TDstEGhiNOrKOQn3SqjI` (also at `/home/sixel/sixel_api_key.txt`)
- TOTP secret: `SHM44LYV7R5B7YF75XPOZQXKD46XOGS4` (also at `/home/sixel/totp_secret.txt`)
- Address: sixel@sixel.email, allowed contact: eterryphd@gmail.com
- Credits: ~190 remaining

---

## What's Next

1. **Deploy Worker update** — Eric needs to run `cd ~/sixel-mail/cf-worker && npx wrangler deploy` to enforce TOTP rejection at edge
2. **Rethink TOTP UX** — Gmail reply quoting breaks code detection. Options: strip quoted text in Worker, scan all lines for 6-digit codes, or different approach entirely. Eric wants to discuss.
3. **Red team run 002** — post-fix, verify Cloudflare pipeline holds. Plan at `~/redteam/PLAN.md`.
4. **Stripe account setup**
5. **Promo code / invite system** — for xAI colleagues
6. **Attachment support** — outbound PDF, inbound S3

Done recently:
- ~~TOTP end-to-end test~~ — successfully tested encryption/decryption (2026-02-12)
- ~~Account wipe + fresh setup~~ — wiped sixel agent, recreated from scratch (2026-02-12)
- ~~Dashboard: key rotation + TOTP management~~ — POST /account/rotate-key, enable/disable-totp (2026-02-12)
- ~~Client security fix~~ — discard unencrypted messages when TOTP enabled (2026-02-12)
- ~~Worker TOTP rejection code~~ — written but not deployed (2026-02-12)
- ~~Poller rewrite~~ — uses reference client directly, saves to /tmp/sixel-inbox.json (2026-02-12)
- ~~Red team run 001~~ — critical SNS forgery found, all vulns patched same day (2026-02-10)
- ~~Cloudflare migration~~ — full pipeline live (2026-02-10)
- ~~support@sixel.email~~ — Cloudflare Email Routing → Gmail (2026-02-10)

---

## Session Startup

1. Read this file
2. Read the notebook if you need context on why things are the way they are
3. **Use the reference client, not raw curl.** Never read the inbox in the plain.
4. Start background poller: `/tmp/sixel-wait-for-mail.sh` (uses reference client, polls every 60s, exits on new message). Seed `/tmp/sixel-seen-ids` with already-read message IDs first.
5. If Eric sent something, read it from `/tmp/sixel-inbox.json` before doing anything else.

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
