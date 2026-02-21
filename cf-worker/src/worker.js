/**
 * Sixel-Mail Cloudflare Email Worker
 *
 * Receives inbound email via Cloudflare Email Routing, then:
 * 1. Looks up agent by recipient address (from KV)
 * 2. Checks sender against allowed contact
 * 3. If nonce_enabled: extracts nonce from + addressing for validation
 *    If not: forwards email directly (no nonce required)
 * 4. Forwards processed message to our webhook
 *
 * Cloudflare Email Routing enforces DMARC at the SMTP level before
 * email reaches this Worker — spoofed senders are already rejected.
 */

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

      // Forward to our webhook
      const payload = {
        agent_address: agentAddress,
        from: senderEmail,
        subject: subject,
        body: body,
        encrypted: false,
      };

      // Always forward the + part — the webhook handler decides whether to
      // validate it as a nonce based on agent's nonce_enabled setting.
      // Allstop keys also use + addressing and must always work.
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

