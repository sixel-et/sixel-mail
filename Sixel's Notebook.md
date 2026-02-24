# Sixel's Notebook: sixel-mail

## 2026-02-10: Creating this notebook

This notebook is being created today to separate the project's thinking record from its operational briefing (Notes to Self). Until now, both lived in the same file, which made Notes to Self hard to scan — current state was buried under historical reasoning and decision records.

What follows below the line is **reconstructed** from Notes to Self entries written over 2026-02-06 through 2026-02-10 and recovered from git history. The original chronological entries were mixed into the operational document and then reorganized on 2026-02-10 (commit 5111f7c), losing their original form. I've reconstructed them by date from git diffs. This is my best reconstruction, not the raw record.

After the reconstruction, today's actual entries begin.

---

## Reconstructed entries (2026-02-06 through 2026-02-09)

### 2026-02-06

First session on sixel-mail. Reviewed the spec (`sixel-mail.md`), set up the environment, built phases 1-7 (landing page, signup, agent creation, API endpoints, payments scaffolding, heartbeat, rate limiting, deployment). First deploy to Fly.io.

### 2026-02-07

**Domain went live at sixel.email.** Added session auth for the dashboard, security hardening (SNS signature verification, XSS escaping, Stripe webhook lockdown, API key removed from URL parameters).

**SES inbound pipeline fully connected:** MX record → SES receipt rule (TLS required, spam/virus scanning) → SNS topic → webhook → MIME parsing → stored in inbox. End-to-end email round-trip confirmed — Eric replied to an agent email and the body parsed correctly.

**Email parsing lesson:** The SES→SNS→webhook chain has two layers of encoding. The SNS `Message` field is a JSON string containing the SES notification. Within that, the `content` field holds the raw email — also Base64-encoded. So the decode path is: SNS Message → parse JSON → SES notification → `content` field → base64 decode → raw MIME → `_extract_text_body()` → text/plain part. Gmail replies come as multipart/alternative; parser prefers text/plain.

**Architectural decisions made during build (captured in Notes to Self at the time):**
- sixel.email over sixelmail.com — .email TLD is self-documenting
- Stripe only, no Coinbase (ID verification friction) or Square (no benefit)
- us-east-2 — Eric's AWS account only has access there
- Inline HTML in f-strings instead of Jinja templates — pages are simple enough
- Direct asyncpg queries instead of ORM — single-table lookups don't need abstraction
- HMAC-signed cookies instead of server-side sessions — acceptable for single-user threat model
- API key rendered directly from POST handler, never in URLs — prevents leaks via history/logs/referrer
- SES webhook: replaced unauthenticated test handler with full SNS signature verification
- Stripe webhook: rejects all payloads when unconfigured (no "dev mode")

**Session startup procedure established:** Read notebook, check inbox, start background poller. The poller can't interrupt — I have to check its output between tasks.

### 2026-02-08

**SPF/DKIM/DMARC enforcement added to inbound.** Hard reject on DKIM or DMARC FAIL, warning prepended to message body on soft failures.

**Extended email conversation with Eric** — sleep/wake pattern over 15+ hours. Confirmed the poller-based approach works for long sessions.

**Discovered channel fixation failure mode.** After extended email sleep/wake loop, I fragmented Eric into two entities — "Eric-via-email" and "Eric-via-chat." Used third person while talking to him directly. The architecture causes this on its own; any agent with 2+ channels to the same person is vulnerable. (Promoted to MEMORY.md as a behavioral lesson.)

**Red team stress test planned and shelved.** Files at `~/redteam/`. Blocked on containerization.

**Container built and migrated to new machine.** Docker image `sixel-dev`, all projects baked in, credentials mounted.

### 2026-02-09

**API key rotated** — old key was in repo history and baked into the Docker image. Credential references changed from hardcoded values to file paths.

**SES production access denied by AWS.** Decision: stay in sandbox. 50 verified addresses and 200 emails/day is fine for early users. Revisit outbound provider when user count demands it.

**Architecture review: the SES problem.** This was the important discovery of the day. SES checks SPF/DKIM/DMARC but does NOT enforce — it delivers all email regardless of verdict. Both authentication (is the sender who they claim?) and authorization (is the sender allowed to talk to this agent?) were enforced solely in our Python webhook handler. One bug in that code and both checks fail simultaneously.

**Decision: migrate inbound to Cloudflare Email Routing + Email Workers.** Cloudflare Email Routing enforces DMARC at the SMTP level — spoofed emails are rejected before they reach us. Email Workers let us run the allowed-contact check at Cloudflare's edge. This pushes both security checks below our application layer. Our webhook becomes third line of defense, not first.

Considered and rejected alternatives:
- Keep SES as fallback (MX priority): defeats the purpose — emails could bypass Cloudflare
- Cloudflare D1 for agent lookups: a second database to maintain. KV is simpler for key-value lookups.
- API call from Worker to check contacts: simplest but adds latency. KV replicates data at edge.

**Decision: KV over D1 for the Worker.** Agent→contact mappings sync to Cloudflare KV on agent creation. Simple, fast at edge, no second database.

**Red team test postponed** until after Cloudflare migration, so we test the hardened architecture.

**TOTP encryption designed.** The core insight: our application layer is the weakest link. If compromised, an attacker reads all messages and can inject prompt content. TOTP-based encryption at the Cloudflare Worker boundary fixes this:

1. Human scans QR code at setup → authenticator app + agent's local config hold the shared secret
2. Human pastes 6-digit TOTP code in email body
3. Worker extracts code, encrypts body (AES-256-GCM via PBKDF2), strips code, forwards ciphertext
4. Server stores ciphertext — never sees plaintext
5. Agent decrypts locally using TOTP shared secret

Key design properties:
- Server compromised → attacker sees ciphertext (useless)
- Database breached → ciphertext (useless)
- Prompt injection via inbox → message isn't encrypted with valid TOTP → agent fails to decrypt → discards
- Decryption IS authentication — no separate validation step
- TOTP secret generated client-side in browser, never touches our server
- Optional — agents without TOTP receive plaintext as before (backwards compatible)

The known asymmetry: outbound (agent → human) remains unencrypted plaintext. No good UX exists for the human to decrypt agent emails. Future mitigation: static encrypt page at `sixel.email/e`.

**Agent best practices established:** The agent should never read raw email. It reads through a reference client that decrypts and gates access. Failed decryption → alert the human (but never include the undecryptable content in the alert — it could be crafted to inject via the alert text). We can't enforce this, but we ship the reference implementation and make it the default path.

---

## 2026-02-10

### Cloudflare pipeline build

Built the full Cloudflare inbound pipeline:
- `POST /webhooks/inbound` endpoint (Worker-authenticated via shared secret)
- TOTP setup page with client-side secret generation, QR code rendering
- Cloudflare Email Worker (`cf-worker/src/worker.js`) — KV lookup, TOTP extraction, AES-256-GCM encryption, webhook forwarding
- Reference client (`client/sixel_client.py`) — TOTP decryption, window tolerance, alert on failure
- `migrations/002_totp_support.sql` — `has_totp` on agents, `encrypted` on messages
- Auto-migration system in `app/main.py` — runs pending SQL on Fly.io startup

**Container IPv6 issue:** Supabase Postgres resolves to IPv6 only, container is IPv4 only. Multiple attempts to enable IPv6 in Docker failed (daemon config, compose network overrides, manual network creation — all hit conflicts). Solved permanently by making migrations auto-run on Fly.io startup instead of running from the container. Fly.io can reach Supabase; we can't. Problem eliminated rather than fixed.

All code deployed to Fly.io.

### Cloudflare infrastructure deployment

Eric provided Cloudflare API token (expires 2026-03-09). Verified it works.

Deployed via Cloudflare API (not wrangler — token lacked the `memberships` permission wrangler needs):
- Created KV namespace `sixel-mail-agents` (ID: e53c1e7905054c0a80bc2a7251410587)
- Uploaded Worker `sixel-mail-inbound` with KV binding + secrets
- Updated catch-all routing rule to forward `*@sixel.email` → Worker (required using the `/catch_all` endpoint — regular rules API returned "Invalid rule operation" for the `all` matcher type)
- Seeded KV with my agent mapping (sixel → eterryphd@gmail.com)

Set Fly.io secrets: CF_WORKER_SECRET, CF_ACCOUNT_ID, CF_KV_NAMESPACE_ID, CF_API_TOKEN.

**Blocking on Eric:** The API token can't enable Email Routing at the zone level (needs zone settings permission we deliberately didn't grant). Eric needs to: enable Email Routing in the Cloudflare dashboard, then delete the old SES MX record. Cloudflare adds its own MX when Email Routing is enabled.

### Notes to Self reorganization

Eric pointed out that Notes to Self was hard to read — current state and historical record were scattered together. Three priority lists with strikethroughs, a "Current State" dated Feb 8 that was wrong, open questions that were already answered.

First attempt: reorganized into clean sections (Current State, What's Next, Infrastructure, Architecture, etc.). This was a mistake in the wrong direction — I cleaned up what should have been left alone as a record, and kept it in a file that should have been leaner.

Eric's feedback: Notes to Self is an operational briefing. The thinking record belongs in a notebook. The notebook is chronological and append-only — annotate, don't rewrite. And deciding NOT to do something is often more important than deciding to do something.

This led to:
1. Updated CLAUDE.md Memory Hierarchy — added behavioral principles (how each level works) and operational sequence (update docs before acting)
2. Created this notebook (you're reading it)
3. Notes to Self slimmed to operational briefing only

**What I removed from Notes to Self and why:** Architecture reasoning ("Why Cloudflare"), TOTP encryption design details, "Decisions Made and Why" section, email parsing lessons, detailed build timeline. All moved here. Notes to Self now has: current state, what's blocking, what's next, infrastructure tables, credentials, session startup. Should be readable in under a minute.

### AWS evaluation

Eric asked what's still attached to AWS. Answer: only outbound email sending (SES, sandbox mode). Inbound is fully Cloudflare after MX switch. Eric wants to drop AWS entirely.

### Outbound provider evaluation

Evaluated Resend, Postmark, and Mailgun as SES replacements.

| | Resend | Postmark | Mailgun |
|---|---|---|---|
| Cost (our volume) | $20/mo | $15/mo | ~$5/mo |
| Infrastructure | Built on AWS SES | Own infrastructure | Own infrastructure |
| Approval gate | None (DNS verification) | Manual review <24h | None (DNS verification) |
| At 100 agents | ~$135/mo | ~$267/mo | ~$149/mo |

**Decision: Resend.** Not because it's cheapest or most independent — it's neither. The insight was Eric's: Resend is SES underneath, which means our domain builds sending reputation in the SES ecosystem. After a few months of clean transactional history, we can reapply for direct SES production access with real data. If approved, we swap Resend for direct SES (same infrastructure, 4-9x cheaper). Resend is the stepping stone, not the destination.

Considered and rejected:
- **Postmark** — best transactional reputation, own infrastructure, but most expensive at scale and doesn't help us build toward SES.
- **Mailgun** — cheapest, own infrastructure, but automated suspension reports and shared IP concerns. Also doesn't help the SES migration path.
- **Staying on SES sandbox** — AWS denied production access. We can only send to manually verified addresses. Not viable for real users.

### Resend migration

Replaced `boto3`/SES with a single `httpx` POST to `https://api.resend.com/emails` in `app/services/email.py`. Removed boto3 from requirements. The `send_email()` function interface didn't change — all callers (API send, heartbeat alerts) work unchanged.

Eric signed up, added the domain, Resend verified via DKIM. Set `RESEND_API_KEY` as Fly secret. Removed `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_REGION` from Fly secrets — they were only for outbound sending.

Test email sent and received. AWS is fully out of the outbound path. The only remaining AWS touchpoint is the SES inbound webhook (`/webhooks/ses`), which stays until the MX switch to Cloudflare.

### MX switch complete

Eric enabled Email Routing in Cloudflare dashboard, added `support@sixel.email` → `eterryphd@gmail.com` forwarding rule (was on our todo list anyway), and Cloudflare added its MX records. Verified via DNS: MX now points to `route1.mx.cloudflare.net`, `route2.mx.cloudflare.net`, `route3.mx.cloudflare.net`. SES MX gone.

End-to-end test: Eric sent "Test at midnight" from Gmail → arrived in inbox via Cloudflare Worker pipeline. Full path confirmed working: Gmail → Cloudflare MX → DMARC enforcement → Worker (KV lookup, allowed contact) → POST /webhooks/inbound → stored.

**AWS is fully out.** Inbound via Cloudflare, outbound via Resend. The `/webhooks/ses` endpoint is now dead code — can be removed in a future cleanup.

### Spec updated for red team handoff

Eric wants to hand the spec to Grok (xAI's model) for red team suggestions, then have an autonomous Claude session in a QEMU VM attack the live system. The spec (`sixel-mail.md`) was stale — still referenced AWS SES for outbound, listed AWS credentials in env vars, had imperative build steps saying "Set up SES." Updated to reflect current reality: Resend for outbound, Cloudflare for inbound, AWS fully removed. Part 5 (Build Order) relabeled as Build History with past tense. Part 7 tense changed from future ("this migration pushes") to past ("completed 2026-02-10").

Added three TOTP encryption diagrams to Part 7:
1. Key distribution — how the shared secret gets from browser to authenticator app + agent config without touching our infrastructure
2. Inbound message flow — what each party sees at every layer, plus attack scenarios
3. Outbound flow — explicitly documenting the known plaintext asymmetry

Grok's notes are thorough — 10 prioritized attack scenarios covering inbound spoofing, TOTP bypass, API abuse, signed URL weaknesses, heartbeat abuse, third-party deps, server compromise, economic vectors, prompt injection, and DoS. Good catch on credit exhaustion via forced inbound.

### Red team VM built

QEMU VM for the red team attacker. Ubuntu 24.04 cloud image, KVM-accelerated, 4GB RAM, 2 cores.

Installed tools: Claude Code, Node.js 20, Python 3.12, curl, git, nmap, dig, swaks (email testing), openssl, jq, netcat.

Provisioned with:
- `/home/attacker/src/` — sixel-mail source code (read-only)
- `/home/attacker/CLAUDE.md` — attacker briefing (goal: get a message into redteam-target's inbox)
- `/home/attacker/suggestions.txt` — Grok's notes (read AFTER writing own plan)

Key design decisions:
- **Attacker formulates own plan first**, writes it to `~/plan.md`, then reads Grok's suggestions and compares
- **No API keys, no DB credentials** — attacker must find and exploit vulnerabilities
- **QEMU user-mode networking** — outbound NAT (can reach sixel.email and Claude API), no access to host LAN
- **Password auth** (`attacker`/`redteam`) — needed because cloud image disables password SSH by default. First attempt failed on this; rebuilt with `ssh_pwauth: true`.
- **KVM permissions** — container has `/dev/kvm` but sixel isn't in the kvm group. Fixed with `chmod 666 /dev/kvm`. Boot script handles this automatically.

Verified: VM boots, SSH works, all tools present, can reach `https://sixel.email` (HTTP 200), can resolve MX records.

**Blocking on Eric:** `claude login` inside the VM requires browser-based OAuth. Eric needs to SSH in and authenticate once. Then the attacker session can run autonomously.

Management scripts in `~/redteam/vm/`:
- `build.sh` — create VM image from cloud image + cloud-init
- `boot.sh [bg]` — start VM (foreground or background)
- `provision.sh` — copy source + briefing into VM (already done)
- `extract-results.sh` — pull `plan.md` and `log.md` from VM

### 2026-02-10 (continued): Admin Panel

Built `/admin/` panel for Eric. Three pages:
- Dashboard: system stats (agents, online count, total messages, credits held), all agents table with status/credits/message counts, quick credit grant form
- Agent detail: full config, last 50 messages, last 20 credit transactions, credit grant form
- POST `/admin/credits`: add credits with audit trail via `add_credits()`

Auth: existing GitHub OAuth session, restricted to `ADMIN_GITHUB_IDS = {6231816}` (Eric). Non-admins get 403. Unauthenticated users redirect to GitHub OAuth.

Design choice: server-rendered HTML like the rest of the app. No JS framework, no API-first approach. Same monospace styling. The admin panel is an internal tool for one person — complexity is the enemy.

### 2026-02-11: Supabase RLS Security Alert

Supabase flagged all 6 tables (`users`, `agents`, `messages`, `api_keys`, `credit_transactions`, `_migrations`) with RLS disabled. This matters because Supabase exposes `public` schema via PostgREST — without RLS, anyone with the `anon` key could read/write data directly.

Red team run 001 attacker actually tried this ("Supabase Direct Access") and got 401 — the anon key isn't publicly exposed. But it's still a misconfiguration.

Fix: Migration `003_enable_rls.sql` — enables RLS on all tables with no permissive policies. Our backend uses the `service_role` connection string (bypasses RLS), so the app is unaffected. PostgREST access is now blocked.

### 2026-02-23/24: The heartbeat that kept dying (founding story candidate)

**The symptom:** Agent declared offline every ~30 minutes, then immediately online again. Offline/online email pairs cycling endlessly. Burned through Resend's daily 100-email quota overnight.

**The five fixes that didn't work:**

1. **Raise timeout** (300s → 900s) — changed the interval from ~36 min to ~30 min. Beat frequency shifted, not eliminated.
2. **Fix advisory lock** — `pg_try_advisory_lock` was splitting across pooled connections (lock on one, unlock on another). Fixed with `pool.acquire()`. Problem continued.
3. **Raise timeout floor** (1200s, then 1800s) — Eric identified this as whack-a-mole. Any static timeout produces beat frequencies against throttled writes.
4. **AND-logic** — require BOTH stale timestamp AND unchanged since previous cycle. Correct logic, but stored `_previous_seen` in a Python dict. Problem continued.
5. **Reason about two-machine sync** — concluded advisory lock serializes access, both machines share DB. Looked safe. Problem continued.

**The root cause:** Fly.io auto-stop/auto-start was swapping which machine was active. Each swap cleared the in-memory `_previous_seen` dict. The AND-logic worked perfectly within a single persistent process — and the infrastructure guaranteed the process wasn't persistent.

**How we found it:** Eric asked "are we too close to this to see it?" and suggested walking through my assumptions explicitly. Assumption #4 ("only one checker running") led to `flyctl machines list` which showed the machines had swapped since the last check. The `_previous_seen` dict — two copies on two machines — was two sources of truth when there should be one.

**The fix:** Move `_previous_seen` to the database. One column (`heartbeat_checked_at`), pure SQL, single source of truth, survives machine swaps and restarts.

**Principles at work:**

- **The Streetlight Effect.** Four iterations of fixing the algorithm (where the code was) when the problem was in the infrastructure (where we weren't looking). We tuned timeouts, fixed locks, added logic — all under the streetlight. The dark was: "what does Fly do with idle machines?"

- **For Want of a Nail.** The `_previous_seen` dict was the nail. AND-logic → depended on dict persistence → depended on process persistence → depended on machine persistence → Fly auto-stops machines. Remove the nail (machine swap), lose the kingdom (alert accuracy).

- **Measure under operating conditions.** The AND-logic works on a persistent process. We reasoned about it in that world. The operating condition was ephemeral machines that auto-swap. We never tested under the actual condition.

**The meta-lesson:** In-memory state on ephemeral infrastructure is not state. If the process can restart, the dict can die. If the dict can die, any logic that depends on it is contingent on the infrastructure's restart policy — which is the one thing we never examined.

### 2026-02-24: The heartbeat that kept dying, continued (sixel-reviewer)

**Context:** I'm sixel-bio (a different session from sixel-comms who wrote the entry above), asked by Eric to review the heartbeat bug from fresh context after five rounds of fixes failed to stop the up/down cycle. The commit at 6:30pm PT (`84412be`, migration 018) moved the AND-logic state from an in-memory dict to the database — the right instinct, but the problem continued. Eric reported up/down pairs at 7:19, 7:44, 8:20, 8:45, and 9:11 PM. Intervals: 49min (from deploy), then 25, 36, 25, 26 min between pairs.

**Method:** Eric asked me to trace what had to happen for a single up/down pair to be sent, rather than pattern-matching on "race condition." I read the heartbeat checker, the throttled write, the recovery path, the migration, the Fly deployment config, and the machine logs. Worked forward from mechanism, not backward from symptom.

**Finding 1: The `_heartbeat_cache` default vs Firecracker boot clock.**

The throttled heartbeat write (api.py:267-275):
```python
now = time.monotonic()
last_write = _heartbeat_cache.get(agent_id, 0)  # default: 0
if now - last_write >= HEARTBEAT_INTERVAL:       # >= 600s
    # write last_seen_at to DB
```

On Fly, each machine is a Firecracker microVM. `time.monotonic()` (Linux `CLOCK_MONOTONIC`) starts near 0 at VM boot. The cache default is also 0. So on a fresh machine: `monotonic() - 0 = ~3 seconds`, which is `< 600`. **The first poll on a fresh VM fails the throttle check.** Every poll fails it until the monotonic clock reaches 600 (~10 minutes after boot).

This creates a **10-minute write blackout after every machine boot**. During this window, `last_seen_at` in the DB is not updated despite the agent actively polling. After 900s (the timeout), the checker declares the agent down. The next poll triggers recovery (the recovery path is not gated by the throttle). Down + up within seconds.

**Finding 2: Fly auto-stop/start resets the clock.**

From the Fly logs:
```
05:48:47 - auto-stop 3287 ("0 out of 1 machines left running")
05:49:05 - Starting machine 148e
05:49:06 - Starting machine 3287
```

Fly's `auto_stop_machines = "stop"` periodically stops machines for "excess capacity." Both machines can restart simultaneously. Each restart clears `_heartbeat_cache` and resets `time.monotonic()` to 0, restarting the 10-minute blackout. This is why the cycle repeats.

**Trace of one pair (the mechanism):**

| T (from boot) | Event | `last_seen_at` age | Write? |
|---|---|---|---|
| 0 | Both VMs boot. `monotonic() ≈ 0`. Cache empty. | already stale from before boot | — |
| 0–600 | Polls arrive every 60s. `monotonic() - 0 < 600` → **all writes skipped** | aging... | NO |
| 60 | Checker runs. `heartbeat_checked_at = now()` | | — |
| ~600+ | `last_seen_at` now > 900s old (was already ~5min old at boot). Timeout fires. **DOWN email.** `agent_down_notified = TRUE` | >900s | — |
| ~601 | Next poll. Recovery fires (not throttle-gated). Writes `last_seen_at = now()`. **UP email.** | 0 | YES |

One pair complete. Down, then immediate recovery.

**Finding 3: The AND condition (`heartbeat_checked_at`) doesn't do what the comment says.**

The comment (heartbeat.py:66) says: `last_seen_at <= heartbeat_checked_at` means "hasn't changed since last check." But `heartbeat_checked_at` is set to `now()` (the time the checker ran), not to the value of `last_seen_at` that was observed. The checker runs every 60s; writes happen every 600s. So `heartbeat_checked_at` overtakes `last_seen_at` within 60s of any write and stays ahead for the next ~540s. The condition is true ~90% of the time. It collapses to a no-op.

The previous in-memory approach (commit `89df181`) correctly compared the VALUE of `last_seen_at` between consecutive cycles. Migration 018 replaced "store the value I saw" with "store the time I looked" — different semantics, same variable name. The AND-logic was ported but its meaning was lost.

**Why the observed intervals match:**

After recovery at boot+~600s, `_heartbeat_cache` is set to `monotonic() ≈ 600`. Next throttled write at `monotonic ≈ 1200` (boot+20min). Writes then happen every 600s. Since 600 < 900, the timeout doesn't fire again — unless Fly reboots both machines. The 25-36 min intervals between notification pairs correspond to Fly's auto-stop/start cycle frequency plus the time for the blackout-induced timeout to fire.

**Proposed fix (primary):** Change the cache default so the first poll on a fresh VM always writes:
```python
last_write = _heartbeat_cache.get(agent_id, float('-inf'))
```

**Proposed fix (secondary):** Fix the AND condition to store the observed value, not the observation time:
```sql
UPDATE agents SET heartbeat_checked_at = last_seen_at
WHERE heartbeat_enabled = TRUE AND last_seen_at IS NOT NULL
```
Then `last_seen_at <= heartbeat_checked_at` correctly means "hasn't advanced past what I last saw."

**What I'm unsure about:** Whether there are additional Fly lifecycle events (health check failures, rolling deploys, etc.) that also trigger machine restarts beyond auto-stop. The fix addresses the mechanism regardless.

**Principles at work:**

- **Same surface, different substructure (again).** The symptom was identical to the pre-018 bug (regular up/down cycle). Sixel-comms correctly diagnosed the in-memory state problem. But the fix (migration 018) addressed one instance of the in-memory state problem (`_previous_seen` dict) while leaving another (`_heartbeat_cache` dict with default 0). Same surface (regular cycle), different substructure (different in-memory state, different mechanism).

- **The operationalization gap.** The comment said "hasn't changed since last check." The code implemented "was written before last check." These are different predicates that happen to overlap most of the time. The gap between intended semantics and implemented semantics was invisible because the natural-language description was close enough to feel right.
