"""Unit tests for app/services/signing.py — URL signing and verification."""

import time
from unittest.mock import patch

from app.services.signing import sign_alert_url, verify_signature, EXPIRY_SECONDS


class TestSignAndVerify:

    def test_sign_verify_roundtrip(self):
        url = sign_alert_url("agent-123", "deactivate")
        # Extract params from URL
        from urllib.parse import urlparse, parse_qs
        parsed = urlparse(url)
        params = parse_qs(parsed.query)
        assert verify_signature(
            params["agent"][0], params["action"][0],
            params["expires"][0], params["sig"][0]
        ) is True

    def test_expired_fails(self):
        url = sign_alert_url("agent-123", "deactivate")
        from urllib.parse import urlparse, parse_qs
        parsed = urlparse(url)
        params = parse_qs(parsed.query)

        # Advance time past expiry
        future = time.time() + EXPIRY_SECONDS + 1
        with patch("app.services.signing.time.time", return_value=future):
            assert verify_signature(
                params["agent"][0], params["action"][0],
                params["expires"][0], params["sig"][0]
            ) is False

    def test_tampered_agent_fails(self):
        url = sign_alert_url("agent-123", "deactivate")
        from urllib.parse import urlparse, parse_qs
        parsed = urlparse(url)
        params = parse_qs(parsed.query)
        assert verify_signature(
            "agent-TAMPERED", params["action"][0],
            params["expires"][0], params["sig"][0]
        ) is False

    def test_tampered_action_fails(self):
        url = sign_alert_url("agent-123", "deactivate")
        from urllib.parse import urlparse, parse_qs
        parsed = urlparse(url)
        params = parse_qs(parsed.query)
        assert verify_signature(
            params["agent"][0], "TAMPERED",
            params["expires"][0], params["sig"][0]
        ) is False

    def test_invalid_expires_fails(self):
        assert verify_signature("a", "b", "not-a-number", "sig") is False


class TestBuildReplyTo:
    """Test nonce reply-to address construction."""

    def test_format(self):
        from app.services.nonce import build_reply_to
        result = build_reply_to("myagent", "abc123")
        assert result == "myagent+abc123@sixel.email"

    def test_preserves_nonce_case(self):
        from app.services.nonce import build_reply_to
        nonce = "AbCdEf_GhI-JkL"
        result = build_reply_to("agent", nonce)
        assert nonce in result
