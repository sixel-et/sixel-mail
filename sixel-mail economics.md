# Sixel-Mail: Economics Analysis

## Product Summary

Sixel-Mail provides scoped email addresses for AI agents. One agent, one allowed human contact, $0.01 per message, prepaid credits. The agent polls for replies; the poll doubles as a heartbeat. The human's email client is the entire UI.

---

## Unit Economics

### Cost to deliver one message

| Component | Cost |
|---|---|
| SES outbound (send) | $0.0001 |
| SES inbound (receive) | $0.0001 |
| Data transfer (~5KB text email) | negligible |
| Compute (API server + message store) | ~$0.000001 |
| **Total cost per message** | **~$0.0002** |

### Revenue per message

$0.01

### Margin per message

$0.0098 — **98% gross margin.**

---

## Payment Processing

Stripe charges 2.9% + $0.30 per transaction. Per-message billing is impossible — you'd lose $0.29 on every $0.01 collected. The solution is prepaid credits with a $5 minimum top-up.

MVP uses Stripe Checkout only. Additional payment rails (Square/Cash App Pay, crypto) deferred to post-MVP.

### Stripe

| Top-up | Messages | Stripe fee | You keep | Effective fee/msg |
|---|---|---|---|---|
| $5 | 500 | $0.45 (9%) | $4.55 | $0.00089 |
| $10 | 1,000 | $0.59 (6%) | $9.41 | $0.00059 |
| $25 | 2,500 | $1.03 (4%) | $23.97 | $0.00041 |

### Margin after payment processing

Assuming average $7.50 top-up:

| | Amount |
|---|---|
| Revenue per message | $0.0100 |
| SES + infra cost | $0.0002 |
| Stripe processing | $0.0007 |
| **Net margin per message** | **$0.0091 (91%)** |

---

## Customer Economics

### Typical customer profile

A developer running 1-2 AI agents (Claude Code, Devin, custom pipelines) that occasionally get stuck and need human input.

Assumptions:
- Agent sends 2-5 messages/day on active days
- Human replies to each
- ~20 active days/month
- Some heartbeat alert messages
- ~120 messages/month total

| | Monthly | Yearly |
|---|---|---|
| Messages | 120 | 1,440 |
| Revenue | $1.20 | $14.40 |
| COGS (SES + infra) | $0.02 | $0.29 |
| Payment processing | $0.07 | $0.86 |
| **Gross profit** | **$1.11** | **$13.25** |

Top-up frequency: roughly once every 4 months ($5 each time).

### Customer segments

| Segment | Msgs/month | Annual revenue | Description |
|---|---|---|---|
| Light | 30 | $3.60 | "Just in case" — agent rarely gets stuck |
| Typical | 120 | $14.40 | Regular agent user, daily interactions |
| Heavy | 500 | $60.00 | Multiple agents, active development |
| Power | 2,000+ | $240+ | CI/CD pipelines, monitoring, multiple agents |

---

## Polling Infrastructure Costs

The agent polls `GET /v1/inbox` once per minute. This is free to the customer but costs infrastructure:

- 1 poll/min × 1,440 min/day × 30 days = ~43,200 requests/month per agent
- These are lightweight HTTP GETs returning small JSON payloads

| Hosting approach | Cost per agent/month | Notes |
|---|---|---|
| Cloudflare Workers | ~$0.00 | Free tier covers ~230 agents |
| AWS Lambda | ~$0.00 | Free tier covers hundreds |
| Fly.io ($5/mo instance) | ~$0.002 | Handles ~2,500 agents |
| Small VPS ($10/mo) | ~$0.001 | Handles ~10,000 agents |

Polling is the loss leader — free to the customer, essentially free to you, and it enables the heartbeat monitoring feature.

---

## Fixed Costs

| Component | Monthly cost |
|---|---|
| Domain + DNS | ~$1 (amortized) |
| Hosting (Fly.io) | $5-25 |
| Database (Supabase free tier → $25) | $0-25 |
| SES (no fixed cost) | $0 |
| Stripe (no fixed cost) | $0 |
| Monitoring / error tracking | $0-10 |
| **Total fixed costs** | **$10-60/month** |

---

## Break-even Analysis

| Scenario | Fixed costs | Customers needed |
|---|---|---|
| Minimal (serverless, free-tier DB) | $10/month | 9 |
| Moderate (Fly.io, free-tier DB) | $25/month | 23 |
| Comfortable (Fly.io, paid DB, monitoring) | $60/month | 54 |

**Profitable almost immediately.** The break-even threshold is trivially low.

---

## Revenue at Scale

| Customers | Monthly revenue | Monthly COGS | Payment processing | Monthly profit |
|---|---|---|---|---|
| 100 | $120 | $2.40 | $7 | ~$110 |
| 500 | $600 | $12 | $35 | ~$550 |
| 1,000 | $1,200 | $24 | $70 | ~$1,100 |
| 5,000 | $6,000 | $120 | $350 | ~$5,500 |
| 10,000 | $12,000 | $240 | $700 | ~$11,000 |
| 50,000 | $60,000 | $1,200 | $3,500 | ~$55,000 |
| 100,000 | $120,000 | $2,400 | $7,000 | ~$110,000 |

Marginal cost of each additional customer is effectively zero until infrastructure scaling events (bigger database, more instances). These are step functions, not linear costs.

### Annual revenue milestones

| Milestone | Customers needed |
|---|---|
| $10K ARR | ~700 |
| $100K ARR | ~7,000 |
| $1M ARR | ~70,000 |

---

## Pricing Psychology

### Why prepaid, not subscription

A $5 prepaid balance is insurance. The customer buys it, forgets about it, and it's there when they need it. There's never a "should I cancel this?" moment because there's nothing recurring to cancel.

Compare a $3/month subscription: same annual revenue, but introduces a monthly charge, monthly evaluation of value, and significantly higher cancellation rates. Prepaid removes the ongoing purchase decision entirely.

This directly supports the product positioning: "I'll have that too, just in case everything else goes to shit."

### Why $0.01/message, not free tier + paid

A free tier creates support burden, attracts non-serious users, and complicates the infrastructure (abuse prevention, resource allocation). A penny per message is:

- Low enough to be invisible ($1.20/month for a typical user)
- High enough to deter abuse ($100 to send 10,000 spam emails)
- Simple enough to explain in one sentence
- Uniform — no tier boundaries, no upsell, no "you've hit your limit"

### The $5 minimum

$5 is the magic number:

- Below the "ask my manager" threshold for any developer
- Below the "check my bank account" threshold for any individual
- Funds 500 messages — months of typical usage
- Stripe fee is manageable at 9%
- Small enough to be an impulse buy: "sure, just in case"

---

## Competitive Pricing Comparison

There are no direct competitors, but adjacent products provide context:

| Product | Cost for equivalent functionality | Notes |
|---|---|---|
| Sixel-Mail | $1.20/month typical | Pay per message, no subscription |
| Twilio SMS | ~$2-5/month | $0.0079/msg + phone number ($1.15/mo), no allowlist |
| Slack (for bot notifications) | $0 (free tier) or $7.25/user/mo | Requires Slack, not universal |
| Pushover | $5 one-time | One-way only, agent can't receive replies |
| Custom SMTP (self-hosted) | $5-20/month + setup time | No guardrails, no heartbeat, hours of setup |
| SendGrid | $15-20/month | Email infrastructure, not agent identity |

Sixel-Mail is cheaper than all alternatives that support two-way communication, and simpler than all of them.

---

## Risks to the Economics

### Low ARPU ($14/year) requires volume
At $14/year per customer, this is a volume business. Mitigation: the product is viral by nature (developers talk to developers), low price means low friction to adoption, and each user naturally expands to multiple agents.

### Payment processing eats margin on small top-ups
Stripe takes 9% on a $5 top-up. Mitigation: add lower-fee payment rails post-MVP (Square at $0.10 fixed fee, crypto at ~1%). As the product grows, negotiate lower Stripe rates (possible at $50K+/month volume). Consider nudging users toward $10 top-ups.

### Someone undercuts on price
Hard to undercut $0.01/msg without going free, and free introduces all the problems listed above. The moat is simplicity and developer trust, not price.

### Platform risk (SES, Fly.io, Supabase)
If any infrastructure provider changes pricing or terms, the costs could shift. Mitigation: all components are swappable. SES → Postmark. Fly.io → Railway. Supabase → Neon. Nothing in the architecture is locked to a specific vendor.

---

## Summary

| Metric | Value |
|---|---|
| Price per message | $0.01 |
| Cost per message | $0.0002 |
| Gross margin | 98% |
| Net margin (after Stripe processing) | ~91% |
| Payment model | Prepaid credits, $5 minimum (Stripe only for MVP) |
| Typical customer ARPU | ~$14/year |
| Break-even | 9-54 customers |
| Path to $100K ARR | ~7,000 customers |
| Path to $1M ARR | ~70,000 customers |

The economics are strong. High margin, low fixed costs, trivial break-even, and a clear path to scale. The product makes money from message one.
