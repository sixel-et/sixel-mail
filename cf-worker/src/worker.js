/**
 * Sixel-Mail Cloudflare Email Worker
 *
 * Receives inbound email via Cloudflare Email Routing, then:
 * 1. Looks up agent by recipient address (from KV)
 * 2. Checks sender against allowed contact
 * 3. If nonce_enabled: extracts nonce from + addressing for validation
 *    If not: forwards email directly (no nonce required)
 * 4. Extracts text body and attachments from MIME
 * 5. Forwards processed message to our webhook
 *
 * Cloudflare Email Routing enforces DMARC at the SMTP level before
 * email reaches this Worker — spoofed senders are already rejected.
 */

const MAX_ATTACHMENT_TOTAL = 10 * 1024 * 1024; // 10MB decoded

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

      // Parse the email to extract subject, body, and attachments
      const rawEmail = await streamToString(message.raw);
      const { subject, body, attachments } = parseEmail(rawEmail);
      console.log(`Parsed email: subject="${subject}", body_length=${body.length}, attachments=${attachments.length}`);

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

      // Include attachments if any
      if (attachments.length > 0) {
        payload.attachments = attachments;
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
 * Simple email parser — extracts Subject header, text/plain body, and attachments
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

  // For multipart emails, extract text/plain body and attachments
  const contentTypeMatch = headerPart.match(
    /^Content-Type:\s*multipart\/\w+;\s*boundary="?([^"\s;]+)"?/im
  );

  let body;
  let attachments = [];
  if (contentTypeMatch) {
    const boundary = contentTypeMatch[1];
    body = extractTextPlain(bodyPart, boundary);
    attachments = extractAttachments(bodyPart, boundary);
  } else {
    body = bodyPart;
  }

  return { subject, body: body || "(no body)", attachments };
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
 * Extract attachments from multipart MIME body.
 * Returns array of { filename, mimeType, contentBase64 }
 */
function extractAttachments(body, boundary) {
  const attachments = [];
  const parts = body.split("--" + boundary);
  let totalSize = 0;

  for (const part of parts) {
    if (part.trim() === "--" || part.trim() === "") continue;

    const partHeaderEnd = part.indexOf("\r\n\r\n");
    const partSplit =
      partHeaderEnd !== -1 ? partHeaderEnd : part.indexOf("\n\n");
    if (partSplit === -1) continue;

    const partHeaders = part.substring(0, partSplit);
    const partBody = part.substring(
      partSplit + (partHeaderEnd !== -1 ? 4 : 2)
    ).trim();

    // Skip text/plain and text/html parts (those are the email body, not attachments)
    if (partHeaders.match(/Content-Type:\s*text\/(plain|html)/i) &&
        !partHeaders.match(/Content-Disposition:\s*attachment/i)) {
      continue;
    }

    // Look for attachment-like parts: Content-Disposition: attachment, or
    // non-text Content-Type with a filename
    const dispositionMatch = partHeaders.match(
      /Content-Disposition:\s*(?:attachment|inline)[^]*?filename="?([^";\r\n]+)"?/i
    );
    const contentTypeHeaderMatch = partHeaders.match(
      /Content-Type:\s*([^\s;]+)/i
    );

    // Also check for filename in Content-Type header (some clients put it there)
    const ctFilenameMatch = partHeaders.match(
      /Content-Type:[^]*?name="?([^";\r\n]+)"?/i
    );

    const filename = dispositionMatch
      ? dispositionMatch[1].trim()
      : ctFilenameMatch
        ? ctFilenameMatch[1].trim()
        : null;

    // Must have a filename to be treated as an attachment
    if (!filename) continue;

    const mimeType = contentTypeHeaderMatch
      ? contentTypeHeaderMatch[1].trim()
      : "application/octet-stream";

    // Check Content-Transfer-Encoding
    const encodingMatch = partHeaders.match(
      /Content-Transfer-Encoding:\s*([^\r\n]+)/i
    );
    const encoding = encodingMatch
      ? encodingMatch[1].toLowerCase().trim()
      : "7bit";

    let contentBase64;
    if (encoding === "base64") {
      // Already base64 — just clean up whitespace
      contentBase64 = partBody.replace(/\s/g, "");
    } else {
      // For other encodings (7bit, 8bit, quoted-printable), encode to base64
      // Use btoa for simple cases — this handles ASCII and latin1
      try {
        contentBase64 = btoa(partBody);
      } catch (e) {
        // btoa fails on non-latin1 chars; skip this attachment
        console.log(`Skipping attachment ${filename}: encoding error`);
        continue;
      }
    }

    // Estimate decoded size (base64 is ~4/3 of original)
    const estimatedSize = Math.ceil(contentBase64.length * 3 / 4);
    totalSize += estimatedSize;

    if (totalSize > MAX_ATTACHMENT_TOTAL) {
      console.log(`Attachment total exceeds ${MAX_ATTACHMENT_TOTAL / 1024 / 1024}MB limit, stopping extraction`);
      break;
    }

    attachments.push({ filename, mimeType, contentBase64 });
    console.log(`Extracted attachment: ${filename} (${mimeType}, ~${estimatedSize} bytes)`);
  }

  return attachments;
}
