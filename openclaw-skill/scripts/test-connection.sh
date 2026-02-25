#!/bin/bash
# Test sixel.email connectivity and authentication

if [ -z "$SIXEL_API_TOKEN" ]; then
  echo "ERROR: SIXEL_API_TOKEN is not set"
  echo "Set it in your OpenClaw config: skills.entries.sixel-email.env.SIXEL_API_TOKEN"
  exit 1
fi

SIXEL_API_URL="${SIXEL_API_URL:-https://sixel.email/v1}"

echo "Testing connection to ${SIXEL_API_URL}..."

response=$(curl -s -w "\n%{http_code}" "${SIXEL_API_URL}/inbox" \
  -H "Authorization: Bearer ${SIXEL_API_TOKEN}")

http_code=$(echo "$response" | tail -1)
body=$(echo "$response" | sed '$d')

case "$http_code" in
  200)
    echo "Connection successful. Authentication valid."
    echo "  Response: ${body}"
    ;;
  401)
    echo "Authentication failed. Check your SIXEL_API_TOKEN."
    ;;
  403)
    echo "Account pending approval. Contact your operator."
    ;;
  *)
    echo "Unexpected response: HTTP ${http_code}"
    echo "  Body: ${body}"
    ;;
esac
