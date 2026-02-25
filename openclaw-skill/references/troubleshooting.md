# Troubleshooting

## "401 Unauthorized" on every request
- Verify SIXEL_API_TOKEN is set correctly in your environment
- Check if the token was recently rotated — you may need a new one
- Ensure the token starts with `sm_live_`

## "402 Payment Required"
- Your agent has run out of credits
- Contact the operator to top up credits at https://sixel.email/account
- Free tier: 10,000 messages on signup

## "403 Forbidden"
- Your account is pending admin approval
- New accounts must be approved before they can send email
- The operator should contact support@sixel.email

## No messages appearing in inbox
- Confirm the operator is replying to the correct agent email address
- If Door Knock is enabled, the operator must reply to the nonce-bearing Reply-To address (this happens automatically in most email clients)
- Check if messages are being filtered by the operator's email provider
- Remember: GET /v1/inbox marks messages as read — if you already polled, those messages won't appear again

## Heartbeat alert triggered unexpectedly
- Your polling interval may be too long — ensure you're polling at least every 60 seconds
- Check for network issues between your agent and sixel.email
- If running behind a proxy, verify it's not caching or blocking the requests

## Attachments failing
- Verify total decoded size is under 10MB and you have at most 10 files
- Binary files must be base64-encoded in the request body
- Filenames cannot be empty

## Rate limited (429)
- Sends: max 100 per day per agent
- Polls: max 120 per minute per agent
- Back off and retry after 60 seconds
