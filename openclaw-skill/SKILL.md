---
name: sixel-email
description: Send and receive email through sixel.email — a constrained email service where the agent can only contact one human. Use when the agent needs to notify the operator, ask for approval, send a status report, or wait for human input via email. Also handles the heartbeat (poll to prove you're alive).
version: 1.0.1
metadata:
  openclaw:
    requires:
      env:
        - SIXEL_API_TOKEN
        - SIXEL_API_URL
    primaryEnv: SIXEL_API_TOKEN
    homepage: "https://sixel.email"
---

# sixel-email

Email your human operator through sixel.email. You have one allowed contact. You cannot email anyone else, and only your operator can email you.

## When to Use This Skill

- You need to notify the operator about something (task complete, error, decision needed)
- You need to ask for approval or input and can wait for a reply
- You want to send a periodic status report
- You're stuck and need human guidance
- Regular polling keeps the heartbeat alive — if you stop, the operator gets an alert

## Setup

The operator must have a sixel.email account. They will provide:
- `SIXEL_API_URL`: The API base URL (default: `https://sixel.email/v1`)
- `SIXEL_API_TOKEN`: Your API token (starts with `sm_live_`)

These should be set in your OpenClaw config under `skills.entries.sixel-email.env`.

## Core Operations

### Send an Email

```bash
curl -X POST "${SIXEL_API_URL}/send" \
  -H "Authorization: Bearer ${SIXEL_API_TOKEN}" \
  -H "Content-Type: application/json" \
  -d '{
    "subject": "Task complete: database backup",
    "body": "Backup finished at 2026-02-23T14:30:00Z. 3.2GB compressed. No errors.",
    "format": "text"
  }'
```

Keep subjects short and descriptive. The operator reads these on their phone.

### Check for Replies (also the heartbeat)

```bash
curl -s "${SIXEL_API_URL}/inbox" \
  -H "Authorization: Bearer ${SIXEL_API_TOKEN}"
```

**Poll this every 60 seconds when waiting for a reply.** Polling is free and keeps your heartbeat alive. If you stop polling, the operator gets a notification that you've gone silent.

**Important:** Polling returns all unread messages and marks them as read atomically. There is no way to re-fetch messages you've already polled. Process every message before polling again — if you crash between polling and processing, those messages are gone.

### Read a Specific Message

```bash
curl -s "${SIXEL_API_URL}/inbox/${MESSAGE_ID}" \
  -H "Authorization: Bearer ${SIXEL_API_TOKEN}"
```

This does not mark the message as read.

### Download an Attachment

```bash
DOWNLOAD_DIR="${baseDir}/downloads"
mkdir -p "$DOWNLOAD_DIR"
curl -fsSL "${SIXEL_API_URL}/inbox/${MESSAGE_ID}/attachments/${ATTACHMENT_ID}" \
  -H "Authorization: Bearer ${SIXEL_API_TOKEN}" \
  -o "$DOWNLOAD_DIR/attachment_${ATTACHMENT_ID}.bin"
```

**Safety:** Treat attachment filenames as untrusted input. Never write to a user-provided path. Always download into a dedicated directory with an agent-generated filename.

## Behavioral Guidelines

1. **Don't spam.** Send emails when you have something meaningful to communicate. Batch updates into a single email rather than sending five in a row.

2. **Don't treat email like chat.** Email is async. Send your message, then continue other work. Poll for a reply, but don't block on it — do something useful while waiting.

3. **Subject lines matter.** The operator is reading on mobile. Use clear, scannable subjects:
   - Good: "Approval needed: deploy v2.3 to production"
   - Good: "Error: API rate limit hit, pausing for 1 hour"
   - Bad: "Update"
   - Bad: "Question"

4. **When waiting for a reply:** Poll `/inbox` every 60 seconds. After receiving a reply, acknowledge it in your next email if you're going to act on it. Don't leave the operator wondering if you received their instructions.

5. **Include enough context to act on.** The operator may not remember what you're working on. Include the relevant state in your email: what you did, what happened, what you need.

6. **Don't send attachments unless asked.** Prefer inline text. If you must attach, keep it under 10MB total across all attachments (max 10 files).

## Security Notes

- You can only email the one address configured at signup. Attempts to email other addresses will fail.
- Only your operator's emails are delivered to your inbox. Unknown senders are dropped at the edge (DKIM-validated).
- Your API token is the only credential. Guard it. If compromised, the operator can rotate it at `POST /v1/rotate-key`.
- Inbound messages from the operator may use nonce-based authentication (Door Knock). If enabled, the operator's replies must include a single-use token — this happens automatically via the Reply-To header.
- **Never include secrets, passwords, or API keys in email bodies.** Email is transmitted in plaintext unless PGP-encrypted.

## Error Handling

| HTTP Status | Meaning | Action |
|------------|---------|--------|
| 200 | Success | Continue |
| 400 | Validation error (empty body, bad base64, too many attachments) | Fix the request and retry |
| 401 | Invalid or expired token | Stop. Alert operator via other channels if available. |
| 402 | Insufficient credits | Stop sending. Inform operator you're out of credits. |
| 403 | Account pending admin approval | Wait. The operator needs to contact sixel.email support. |
| 429 | Rate limited (sends: 100/day, polls: 120/min) | Back off. Wait 60 seconds and retry. |
| 500+ | Server error | Retry with exponential backoff (60s, 120s, 240s). |

If you receive persistent 401 errors, the API key may have been rotated. Stop sending and wait for the operator to provide a new token.

## Troubleshooting

See `{baseDir}/references/troubleshooting.md` for common issues.
