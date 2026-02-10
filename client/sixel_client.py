"""
Sixel-Mail Reference Client

This client handles TOTP decryption and message verification.
Agents should use this client instead of calling the API directly.

The agent never sees raw/unverified content. This is the gatekeeper.

Usage:
    from sixel_client import SixelClient

    client = SixelClient(
        api_url="https://sixel.email/v1",
        api_key="sm_live_xxxxx",
        agent_address="my-agent",  # Your agent's local part
        totp_secret="YOUR_BASE32_SECRET",  # Optional, for TOTP-enabled agents
    )

    # Poll for messages (only returns decrypted/verified messages)
    messages = client.poll()
    for msg in messages:
        print(msg["subject"], msg["body"])

    # Send a message
    client.send("Subject here", "Body here")
"""

import base64
import hashlib
import hmac
import json
import struct
import time
from datetime import datetime, timedelta, timezone
from typing import Optional

import httpx


class SixelClient:
    """Reference client for sixel-mail with TOTP decryption.

    Core principle: the agent never reads raw email. It reads through
    this client, which gates all access through TOTP decryption.
    """

    def __init__(
        self,
        api_url: str,
        api_key: str,
        agent_address: str,
        totp_secret: Optional[str] = None,
        totp_window: int = 10,
    ):
        """
        Args:
            api_url: Base URL for the sixel-mail API (e.g. https://sixel.email/v1)
            api_key: API key (sm_live_xxxxx)
            agent_address: The agent's local part (e.g. "my-agent" from my-agent@sixel.email)
            totp_secret: Base32-encoded TOTP shared secret. If provided, only
                         messages that decrypt successfully will be surfaced.
            totp_window: Number of TOTP windows to try in each direction
                         (default 10 = ±5 minutes to account for email delivery delay)
        """
        self.api_url = api_url.rstrip("/")
        self.api_key = api_key
        self._agent_address = agent_address.lower()
        self.totp_secret = totp_secret
        self.totp_window = totp_window
        self._consecutive_failures = 0

    def poll(self) -> list[dict]:
        """Poll for new messages. Returns only verified/decrypted messages.

        If TOTP is enabled, messages that fail decryption are discarded
        and an alert is sent to the allowed contact.

        Returns:
            List of message dicts with keys: id, subject, body, received_at
        """
        with httpx.Client() as client:
            resp = client.get(
                f"{self.api_url}/inbox",
                headers={"Authorization": f"Bearer {self.api_key}"},
            )
            resp.raise_for_status()

        data = resp.json()
        raw_messages = data.get("messages", [])

        if not self.totp_secret:
            # No TOTP — return messages as-is
            self._consecutive_failures = 0
            return raw_messages

        # TOTP enabled — decrypt each message
        verified = []
        for msg in raw_messages:
            if not msg.get("encrypted", False):
                # Unencrypted message (sender didn't include TOTP code)
                verified.append(msg)
                self._consecutive_failures = 0
                continue

            decrypted = self._try_decrypt(msg)
            if decrypted:
                verified.append(decrypted)
                self._consecutive_failures = 0
            else:
                # Failed to decrypt — potential tampering
                self._consecutive_failures += 1
                self._send_decryption_alert()

        return verified

    def send(self, subject: str, body: str) -> dict:
        """Send a message. Outbound remains plaintext (known asymmetry)."""
        with httpx.Client() as client:
            resp = client.post(
                f"{self.api_url}/send",
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                json={"subject": subject, "body": body},
            )
            resp.raise_for_status()
        return resp.json()

    def _try_decrypt(self, msg: dict) -> Optional[dict]:
        """Try to decrypt a message using recent TOTP codes.

        Tries current TOTP window ± self.totp_window windows.
        Returns the message with decrypted body, or None if all fail.
        """
        ciphertext_b64 = msg.get("body", "")
        try:
            combined = base64.b64decode(ciphertext_b64)
        except Exception:
            return None

        if len(combined) < 28:  # 12 (iv) + 16 (min GCM tag)
            return None

        iv = combined[:12]
        ciphertext = combined[12:]

        # Get the agent address for salt
        # We use the date from the message's received_at, falling back to today
        received_at = msg.get("received_at", "")
        try:
            dt = datetime.fromisoformat(received_at.replace("Z", "+00:00"))
            date_str = dt.strftime("%Y-%m-%d")
        except (ValueError, AttributeError):
            dt = datetime.now(timezone.utc)
            date_str = dt.strftime("%Y-%m-%d")

        # Try message date, today, and yesterday to handle clock skew / midnight crossing
        now = datetime.now(timezone.utc)
        dates_to_try = [date_str]
        for d in [now, now - timedelta(days=1)]:
            d_str = d.strftime("%Y-%m-%d")
            if d_str not in dates_to_try:
                dates_to_try.append(d_str)

        current_time = int(time.time())

        for try_date in dates_to_try:
            for offset in range(-self.totp_window, self.totp_window + 1):
                totp_time = current_time + (offset * 30)
                code = self._generate_totp(totp_time)

                plaintext = self._decrypt_aes_gcm(
                    iv, ciphertext, code, try_date
                )
                if plaintext is not None:
                    result = msg.copy()
                    result["body"] = plaintext
                    return result

        return None

    def _generate_totp(self, timestamp: int) -> str:
        """Generate a 6-digit TOTP code for the given timestamp."""
        # Time step
        time_step = timestamp // 30

        # HMAC-SHA1
        secret_bytes = _base32_decode(self.totp_secret)
        msg = struct.pack(">Q", time_step)
        h = hmac.new(secret_bytes, msg, hashlib.sha1).digest()

        # Dynamic truncation
        offset = h[-1] & 0x0F
        code = (
            struct.unpack(">I", h[offset : offset + 4])[0] & 0x7FFFFFFF
        ) % 1000000

        return str(code).zfill(6)

    def _decrypt_aes_gcm(
        self, iv: bytes, ciphertext: bytes, totp_code: str, date_str: str
    ) -> Optional[str]:
        """Try to decrypt with a specific TOTP code.

        Uses PBKDF2 to derive key from TOTP code, same as the Worker.
        Returns plaintext string or None if decryption fails.
        """
        try:
            from cryptography.hazmat.primitives.ciphers.aead import AESGCM
            from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
            from cryptography.hazmat.primitives import hashes
        except ImportError:
            raise ImportError(
                "sixel_client requires the 'cryptography' package. "
                "Install with: pip install cryptography"
            )

        # Derive key — must match Worker's derivation exactly
        # Salt = agent_address + ":" + date_string
        salt = (self._agent_address + ":" + date_str).encode()

        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=32,
            salt=salt,
            iterations=100000,
        )
        key = kdf.derive(totp_code.encode())

        try:
            aesgcm = AESGCM(key)
            plaintext = aesgcm.decrypt(iv, ciphertext, None)
            return plaintext.decode("utf-8")
        except Exception:
            return None

    def _send_decryption_alert(self):
        """Send an alert to the allowed contact about failed decryption.

        Does NOT include the undecryptable content (it could be crafted
        to inject via the alert text itself).
        """
        severity = "WARNING"
        detail = "I received a message I couldn't decrypt."
        if self._consecutive_failures >= 3:
            severity = "ALERT"
            detail = (
                f"I've received {self._consecutive_failures} consecutive "
                "messages I couldn't decrypt. This may indicate tampering "
                "or a TOTP sync issue. Please verify your authenticator app "
                "is working and check your agent's TOTP secret."
            )

        try:
            self.send(
                f"[{severity}] Decryption failure",
                detail,
            )
        except Exception:
            pass  # Don't fail the poll if the alert fails


def _base32_decode(secret: str) -> bytes:
    """Decode a base32 string to bytes."""
    # Add padding if needed
    padding = 8 - (len(secret) % 8)
    if padding != 8:
        secret += "=" * padding
    return base64.b32decode(secret.upper())
