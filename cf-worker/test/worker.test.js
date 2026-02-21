import { describe, it, expect } from "vitest";
import { parseEmail, extractTextPlain, extractAttachments, extractEmail } from "../src/worker.js";

// --- extractEmail ---

describe("extractEmail", () => {
  it("extracts from angle brackets", () => {
    expect(extractEmail("Alice <alice@test.com>")).toBe("alice@test.com");
  });

  it("returns plain address as-is", () => {
    expect(extractEmail("bob@test.com")).toBe("bob@test.com");
  });

  it("handles display name with special chars", () => {
    expect(extractEmail('"O\'Brien, John" <john@test.com>')).toBe("john@test.com");
  });
});

// --- parseEmail ---

describe("parseEmail", () => {
  it("parses simple plain-text email", () => {
    const raw = [
      "From: sender@test.com",
      "To: agent@sixel.email",
      "Subject: Hello World",
      "",
      "This is the body.",
    ].join("\r\n");

    const { subject, body, attachments } = parseEmail(raw);
    expect(subject).toBe("Hello World");
    expect(body).toBe("This is the body.");
    expect(attachments).toHaveLength(0);
  });

  it("parses subject with LF line endings", () => {
    const raw = [
      "From: sender@test.com",
      "Subject: LF Test",
      "",
      "Body here.",
    ].join("\n");

    const { subject, body } = parseEmail(raw);
    expect(subject).toBe("LF Test");
    expect(body).toBe("Body here.");
  });

  it("returns (no body) when body missing", () => {
    const raw = "Subject: Empty\r\n\r\n";
    const { body } = parseEmail(raw);
    expect(body).toBe("(no body)");
  });
});

// --- extractTextPlain (multipart) ---

describe("extractTextPlain", () => {
  it("extracts text/plain from multipart/alternative", () => {
    const boundary = "boundary123";
    const body = [
      `--${boundary}`,
      "Content-Type: text/plain; charset=utf-8",
      "",
      "Plain text content here.",
      `--${boundary}`,
      "Content-Type: text/html; charset=utf-8",
      "",
      "<p>HTML content here.</p>",
      `--${boundary}--`,
    ].join("\r\n");

    expect(extractTextPlain(body, boundary)).toBe("Plain text content here.");
  });

  it("extracts text/plain from nested multipart", () => {
    // multipart/related containing multipart/alternative
    const outerBoundary = "outer";
    const innerBoundary = "inner";
    const body = [
      `--${outerBoundary}`,
      `Content-Type: multipart/alternative; boundary="${innerBoundary}"`,
      "",
      `--${innerBoundary}`,
      "Content-Type: text/plain",
      "",
      "Nested plain text.",
      `--${innerBoundary}`,
      "Content-Type: text/html",
      "",
      "<p>Nested HTML.</p>",
      `--${innerBoundary}--`,
      `--${outerBoundary}--`,
    ].join("\r\n");

    expect(extractTextPlain(body, outerBoundary)).toBe("Nested plain text.");
  });

  it("returns empty string when no text/plain found", () => {
    const boundary = "b";
    const body = [
      `--${boundary}`,
      "Content-Type: text/html",
      "",
      "<p>Only HTML.</p>",
      `--${boundary}--`,
    ].join("\r\n");

    expect(extractTextPlain(body, boundary)).toBe("");
  });

  it("handles LF-only line endings", () => {
    const boundary = "lf";
    const body = [
      `--${boundary}`,
      "Content-Type: text/plain",
      "",
      "LF body.",
      `--${boundary}--`,
    ].join("\n");

    expect(extractTextPlain(body, boundary)).toBe("LF body.");
  });
});

// --- extractAttachments ---

describe("extractAttachments", () => {
  it("extracts base64-encoded attachment", () => {
    const boundary = "att";
    const contentBase64 = btoa("Hello attachment");
    const body = [
      `--${boundary}`,
      "Content-Type: text/plain",
      "",
      "Body text.",
      `--${boundary}`,
      'Content-Type: application/pdf; name="doc.pdf"',
      'Content-Disposition: attachment; filename="doc.pdf"',
      "Content-Transfer-Encoding: base64",
      "",
      contentBase64,
      `--${boundary}--`,
    ].join("\r\n");

    const atts = extractAttachments(body, boundary);
    expect(atts).toHaveLength(1);
    expect(atts[0].filename).toBe("doc.pdf");
    expect(atts[0].mimeType).toBe("application/pdf");
    expect(atts[0].contentBase64).toBe(contentBase64);
  });

  it("extracts multiple attachments", () => {
    const boundary = "multi";
    const body = [
      `--${boundary}`,
      "Content-Type: text/plain",
      "",
      "Body.",
      `--${boundary}`,
      'Content-Type: image/png; name="a.png"',
      'Content-Disposition: attachment; filename="a.png"',
      "Content-Transfer-Encoding: base64",
      "",
      btoa("png1"),
      `--${boundary}`,
      'Content-Type: image/jpeg; name="b.jpg"',
      'Content-Disposition: attachment; filename="b.jpg"',
      "Content-Transfer-Encoding: base64",
      "",
      btoa("jpg2"),
      `--${boundary}--`,
    ].join("\r\n");

    const atts = extractAttachments(body, boundary);
    expect(atts).toHaveLength(2);
    expect(atts[0].filename).toBe("a.png");
    expect(atts[1].filename).toBe("b.jpg");
  });

  it("skips text/plain parts without disposition", () => {
    const boundary = "skip";
    const body = [
      `--${boundary}`,
      "Content-Type: text/plain",
      "",
      "Not an attachment.",
      `--${boundary}--`,
    ].join("\r\n");

    expect(extractAttachments(body, boundary)).toHaveLength(0);
  });

  it("extracts from nested multipart", () => {
    const outer = "outer";
    const inner = "inner";
    const body = [
      `--${outer}`,
      `Content-Type: multipart/related; boundary="${inner}"`,
      "",
      `--${inner}`,
      "Content-Type: text/plain",
      "",
      "Body.",
      `--${inner}`,
      'Content-Type: image/gif; name="img.gif"',
      'Content-Disposition: inline; filename="img.gif"',
      "Content-Transfer-Encoding: base64",
      "",
      btoa("gif"),
      `--${inner}--`,
      `--${outer}--`,
    ].join("\r\n");

    const atts = extractAttachments(body, outer);
    expect(atts).toHaveLength(1);
    expect(atts[0].filename).toBe("img.gif");
  });

  it("uses Content-Type name when no Content-Disposition", () => {
    const boundary = "ctname";
    const body = [
      `--${boundary}`,
      "Content-Type: text/plain",
      "",
      "Body.",
      `--${boundary}`,
      'Content-Type: application/octet-stream; name="data.bin"',
      "Content-Transfer-Encoding: base64",
      "",
      btoa("binary"),
      `--${boundary}--`,
    ].join("\r\n");

    const atts = extractAttachments(body, boundary);
    expect(atts).toHaveLength(1);
    expect(atts[0].filename).toBe("data.bin");
  });
});

// --- Full email parsing with multipart ---

describe("parseEmail multipart", () => {
  it("parses Gmail-style multipart/alternative", () => {
    const raw = [
      "From: alice@gmail.com",
      "To: agent@sixel.email",
      "Subject: Gmail Test",
      'Content-Type: multipart/alternative; boundary="gmail_boundary"',
      "",
      "--gmail_boundary",
      "Content-Type: text/plain; charset=utf-8",
      "",
      "Hello from Gmail!",
      "--gmail_boundary",
      "Content-Type: text/html; charset=utf-8",
      "",
      "<div>Hello from Gmail!</div>",
      "--gmail_boundary--",
    ].join("\r\n");

    const { subject, body, attachments } = parseEmail(raw);
    expect(subject).toBe("Gmail Test");
    expect(body).toBe("Hello from Gmail!");
    expect(attachments).toHaveLength(0);
  });

  it("parses email with text body and attachment", () => {
    const attachmentContent = btoa("PDF content here");
    const raw = [
      "From: sender@test.com",
      "To: agent@sixel.email",
      "Subject: With Attachment",
      'Content-Type: multipart/mixed; boundary="mixed_boundary"',
      "",
      "--mixed_boundary",
      "Content-Type: text/plain",
      "",
      "See the attached file.",
      "--mixed_boundary",
      'Content-Type: application/pdf; name="report.pdf"',
      'Content-Disposition: attachment; filename="report.pdf"',
      "Content-Transfer-Encoding: base64",
      "",
      attachmentContent,
      "--mixed_boundary--",
    ].join("\r\n");

    const { subject, body, attachments } = parseEmail(raw);
    expect(subject).toBe("With Attachment");
    expect(body).toBe("See the attached file.");
    expect(attachments).toHaveLength(1);
    expect(attachments[0].filename).toBe("report.pdf");
    expect(attachments[0].contentBase64).toBe(attachmentContent);
  });

  it("handles binary body without crash", () => {
    // Simulate pasted image — body is just binary-ish data
    const binaryish = "\x89PNG\x00\x00test";
    const raw = [
      "Subject: Binary",
      "Content-Type: text/plain",
      "",
      binaryish,
    ].join("\r\n");

    // Should not throw
    const { body } = parseEmail(raw);
    expect(body).toContain("PNG");
  });
});
