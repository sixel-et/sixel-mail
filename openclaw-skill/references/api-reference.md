# sixel.email API Reference

Base URL: `https://sixel.email/v1`

All requests require `Authorization: Bearer <token>` header.

## Endpoints

### POST /v1/send
Send an email to your configured operator.

**Request body:**
- `subject` (string, optional): Email subject line
- `body` (string, required): Email body content (max 100KB)
- `format` (string, optional): "text" (default) or "html"
- `attachments` (array, optional): File attachments
  - `filename` (string, required): Filename
  - `content` (string, required): Base64-encoded file content

**Constraints:** Max 10 attachments, 10MB total decoded size.

**Response:** `200 OK`
```json
{
  "id": "message-uuid",
  "status": "sent",
  "credits_remaining": 9999
}
```

**Errors:** 400 (validation), 401 (auth), 402 (no credits), 403 (pending approval), 429 (rate limit: 100/day)

### GET /v1/inbox
Retrieve new messages. Also serves as the heartbeat signal.

**No query parameters.** Returns all unread messages and marks them as read atomically.

**Response:** `200 OK`
```json
{
  "messages": [
    {
      "id": "message-uuid",
      "subject": "Re: your report",
      "body": "Looks good, deploy it.",
      "received_at": "2026-02-24T14:30:00Z",
      "encrypted": false,
      "attachments": [
        {
          "id": "attachment-uuid",
          "filename": "notes.txt",
          "mime_type": "text/plain",
          "size_bytes": 1234
        }
      ]
    }
  ],
  "credits_remaining": 9998,
  "agent_status": "alive"
}
```

**Errors:** 401 (auth), 429 (rate limit: 120/min)

**Important:** Messages returned by this endpoint are marked as read and will not appear in subsequent polls. Process them before polling again.

### GET /v1/inbox/:id
Retrieve a specific message by ID. Does not mark it as read.

**Errors:** 401 (auth), 404 (not found)

### GET /v1/inbox/:id/attachments/:aid
Download a specific attachment from a message.

Returns raw binary content with appropriate Content-Type and Content-Disposition headers.

**Errors:** 400 (invalid UUID), 401 (auth), 404 (not found)

### POST /v1/rotate-key
Rotate the API key. Returns the new key. The old key is immediately invalidated.

**Response:** `200 OK`
```json
{
  "api_key": "sm_live_xxxxxxxxxxxxx",
  "message": "Old key has been invalidated. Store this key — it won't be shown again."
}
```

**Warning:** Rotating the key will break any active agent sessions using the old key. This is also the kill switch — use it to instantly cut off a compromised or misbehaving agent.
