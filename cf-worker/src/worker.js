/**
 * Sixel-Mail Cloudflare Email Worker
 *
 * Receives inbound email via Cloudflare Email Routing, then:
 * 1. Looks up agent by recipient address (from KV)
 * 2. Checks sender against allowed contact
 * 3. If TOTP-enabled: extracts TOTP code from body, encrypts body, strips code
 * 4. Forwards processed message to our webhook
 *
 * Cloudflare Email Routing enforces DMARC at the SMTP level before
 * email reaches this Worker — spoofed senders are already rejected.
 */

import { EmailMessage } from "cloudflare:email";

export default {
  async email(message, env, ctx) {
    try {
      const from = message.from;
      const to = message.to;
      console.log(`Email received: from=${from}, to=${to}`);

      // Extract local part from recipient address, handle + addressing for nonces
      // Only lowercase the agent address — nonces are case-sensitive (base64url)
      const fullLocal = to.split("@")[0];
      const plusIndex = fullLocal.indexOf("+");
      const agentAddress = (plusIndex !== -1 ? fullLocal.substring(0, plusIndex) : fullLocal).toLowerCase();
      const noncePart = plusIndex !== -1 ? fullLocal.substring(plusIndex + 1) : null;
      console.log(`Parsed: agent=${agentAddress}, nonce=${noncePart ? 'present' : 'none'}`);

      // Look up agent in KV (using base address, without + portion)
      const agentData = await env.AGENTS.get(agentAddress, { type: "json" });
      if (!agentData) {
        console.log(`Unknown agent: ${agentAddress}`);
        message.setReject("Unknown recipient");
        return;
      }

      // Check allowed contact
      const senderEmail = extractEmail(from).toLowerCase();
      if (senderEmail !== agentData.allowed_contact) {
        console.log(`Sender ${senderEmail} not allowed (expected ${agentData.allowed_contact})`);
        message.setReject("Sender not authorized");
        return;
      }

      // Parse the email to extract subject and body
      const rawEmail = await streamToString(message.raw);
      const { subject, body } = parseEmail(rawEmail);
      console.log(`Parsed email: subject="${subject}", body_length=${body.length}`);

      // Forward to our webhook (include nonce if present from + addressing)
      const payload = {
        agent_address: agentAddress,
        from: senderEmail,
        subject: subject,
        body: body,
        encrypted: false,
      };
      if (noncePart) {
        payload.nonce = noncePart;
      }

      console.log(`Forwarding to webhook: ${env.WEBHOOK_URL}`);
      const response = await fetch(env.WEBHOOK_URL, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-Worker-Auth": env.WORKER_AUTH_SECRET,
        },
        body: JSON.stringify(payload),
      });

      const responseText = await response.text();
      console.log(`Webhook response: ${response.status} ${responseText}`);
    } catch (err) {
      console.error(`Worker error: ${err.message}\n${err.stack}`);
      message.setReject("Internal error");
    }
  },
};

/**
 * Extract email address from "Name <email>" format
 */
function extractEmail(addr) {
  const match = addr.match(/<([^>]+)>/);
  return match ? match[1] : addr;
}

/**
 * Read a ReadableStream into a string
 */
async function streamToString(stream) {
  const reader = stream.getReader();
  const decoder = new TextDecoder();
  let result = "";
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    result += decoder.decode(value, { stream: true });
  }
  result += decoder.decode();
  return result;
}

/**
 * Simple email parser — extracts Subject header and text/plain body
 */
function parseEmail(rawEmail) {
  // Split headers from body
  const headerEnd = rawEmail.indexOf("\r\n\r\n");
  const splitIndex =
    headerEnd !== -1 ? headerEnd : rawEmail.indexOf("\n\n");
  const headerPart =
    splitIndex !== -1 ? rawEmail.substring(0, splitIndex) : rawEmail;
  const bodyPart =
    splitIndex !== -1
      ? rawEmail.substring(splitIndex + (headerEnd !== -1 ? 4 : 2))
      : "";

  // Extract subject from headers
  let subject = "";
  const subjectMatch = headerPart.match(/^Subject:\s*(.+?)$/im);
  if (subjectMatch) {
    subject = subjectMatch[1].trim();
  }

  // For multipart emails, try to extract text/plain part
  const contentTypeMatch = headerPart.match(
    /^Content-Type:\s*multipart\/\w+;\s*boundary="?([^"\s;]+)"?/im
  );

  let body;
  if (contentTypeMatch) {
    body = extractTextPlain(bodyPart, contentTypeMatch[1]);
  } else {
    body = bodyPart;
  }

  return { subject, body: body || "(no body)" };
}

/**
 * Extract text/plain part from multipart MIME body
 */
function extractTextPlain(body, boundary) {
  const parts = body.split("--" + boundary);
  for (const part of parts) {
    if (part.trim() === "--" || part.trim() === "") continue;

    const partHeaderEnd = part.indexOf("\r\n\r\n");
    const partSplit =
      partHeaderEnd !== -1 ? partHeaderEnd : part.indexOf("\n\n");
    if (partSplit === -1) continue;

    const partHeaders = part.substring(0, partSplit);
    const partBody = part.substring(
      partSplit + (partHeaderEnd !== -1 ? 4 : 2)
    );

    if (partHeaders.match(/Content-Type:\s*text\/plain/i)) {
      return partBody.trim();
    }
  }
  // Fallback: return the whole body
  return body;
}

/**
 * Extract TOTP code from body and encrypt.
 *
 * Looks for a 6-digit code on the first or last non-empty line.
 * If found: derives AES-256-GCM key from the code, encrypts the body
 * (minus the TOTP line), returns base64(iv + ciphertext + tag).
 *
 * Returns null if no TOTP code found.
 */
async function extractAndEncrypt(body, agentAddress) {
  const lines = body.split("\n");
  const nonEmptyLines = [];
  const lineIndices = [];

  for (let i = 0; i < lines.length; i++) {
    if (lines[i].trim() !== "") {
      nonEmptyLines.push(lines[i].trim());
      lineIndices.push(i);
    }
  }

  if (nonEmptyLines.length === 0) return null;

  let totpCode = null;
  let totpLineIndex = -1;

  // Check first non-empty line
  if (/^\d{6}$/.test(nonEmptyLines[0])) {
    totpCode = nonEmptyLines[0];
    totpLineIndex = lineIndices[0];
  }
  // Check last non-empty line
  else if (
    nonEmptyLines.length > 1 &&
    /^\d{6}$/.test(nonEmptyLines[nonEmptyLines.length - 1])
  ) {
    totpCode = nonEmptyLines[nonEmptyLines.length - 1];
    totpLineIndex = lineIndices[lineIndices.length - 1];
  }

  if (!totpCode) return null;

  // Remove the TOTP line from the body
  const cleanLines = lines.filter((_, i) => i !== totpLineIndex);
  const cleanBody = cleanLines.join("\n").trim();

  // Derive AES-256 key from TOTP code using PBKDF2
  const encoder = new TextEncoder();
  const salt = encoder.encode(agentAddress + ":" + getDateString());

  const keyMaterial = await crypto.subtle.importKey(
    "raw",
    encoder.encode(totpCode),
    "PBKDF2",
    false,
    ["deriveKey"]
  );

  const aesKey = await crypto.subtle.deriveKey(
    {
      name: "PBKDF2",
      salt: salt,
      iterations: 100000,
      hash: "SHA-256",
    },
    keyMaterial,
    { name: "AES-GCM", length: 256 },
    false,
    ["encrypt"]
  );

  // Encrypt with AES-256-GCM
  const iv = crypto.getRandomValues(new Uint8Array(12));
  const ciphertext = await crypto.subtle.encrypt(
    { name: "AES-GCM", iv: iv },
    aesKey,
    encoder.encode(cleanBody)
  );

  // Combine: iv (12 bytes) + ciphertext (includes 16-byte GCM tag)
  const combined = new Uint8Array(iv.length + ciphertext.byteLength);
  combined.set(iv);
  combined.set(new Uint8Array(ciphertext), iv.length);

  // Return as base64
  return {
    ciphertext: btoa(String.fromCharCode(...combined)),
  };
}

/**
 * Get current date string for PBKDF2 salt (YYYY-MM-DD)
 * Using date ensures the same TOTP code produces different keys on different days
 */
function getDateString() {
  const d = new Date();
  return `${d.getUTCFullYear()}-${String(d.getUTCMonth() + 1).padStart(2, "0")}-${String(d.getUTCDate()).padStart(2, "0")}`;
}
