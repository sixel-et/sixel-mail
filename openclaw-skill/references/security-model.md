# sixel.email Security Model

## Constraints by Design

1. **One-way addressing**: The agent can only email the address configured at signup. The API enforces this server-side — there is no "to" field in the send endpoint.

2. **Inbound filtering**: Only emails from the agent's allowed contact are delivered. Unknown senders are rejected at the edge by the Cloudflare Worker. DKIM signatures are validated.

3. **API key scoping**: All access (send, receive, rotate) requires the API key. No anonymous access.

4. **Inbound authentication (Door Knock)**: Optional nonce-based verification for inbound messages. When enabled, outbound emails include a Reply-To address with a single-use nonce token. The operator's reply must include this nonce, which is validated and burned on use. Nonces expire after 30 minutes.

5. **Kill switch**: Rotating the API key instantly cuts off the agent. No SSH access or gateway restart required.

## Threat Model

| Threat | Mitigation |
|--------|-----------|
| Agent sends email to unintended recipient | Impossible — recipient is hardcoded server-side |
| Attacker sends crafted email to agent's address | DKIM validation + allowed contact check + optional Door Knock nonce |
| API key leaked | Rotate immediately via POST /v1/rotate-key |
| Agent compromised, spams operator | Operator rotates key; rate limit: 100 emails/day |
| Man-in-the-middle | Use PGP encryption for sensitive content |
| Prompt injection via email body | Defend at the agent level; sixel.email authenticates the sender, not the content |

## Comparison to Full Email Access

Traditional email skills give agents access to read, send, and manage email for any address. This creates:
- Data exfiltration risk (agent reads sensitive emails)
- Impersonation risk (agent sends as the human)
- Spam/abuse risk (agent emails arbitrary recipients)

sixel.email eliminates all three by design. The agent has its own address, its own inbox, and can only talk to one person.
