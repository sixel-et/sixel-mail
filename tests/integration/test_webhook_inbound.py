"""Integration tests for POST /webhooks/inbound.

Tests all branching paths in the webhook handler using TestClient
with a mock database pool.
"""

import base64
import hashlib
import uuid

import pytest


class TestWebhookAuth:
    """X-Worker-Auth header validation."""

    def test_missing_auth_header(self, client):
        resp = client.post("/webhooks/inbound", json={
            "agent_address": "test-a", "from": "test-b@sixel.email",
            "subject": "No auth", "body": "test",
        })
        assert resp.status_code == 403

    def test_wrong_auth_header(self, client):
        resp = client.post("/webhooks/inbound", json={
            "agent_address": "test-a", "from": "test-b@sixel.email",
            "subject": "Bad auth", "body": "test",
        }, headers={"X-Worker-Auth": "wrong-secret"})
        assert resp.status_code == 403

    def test_empty_auth_header(self, client):
        resp = client.post("/webhooks/inbound", json={
            "agent_address": "test-a", "from": "test-b@sixel.email",
            "subject": "Empty auth", "body": "test",
        }, headers={"X-Worker-Auth": ""})
        assert resp.status_code == 403


class TestMissingFields:
    """Request validation."""

    def test_missing_agent_address(self, client, worker_auth):
        resp = client.post("/webhooks/inbound", json={
            "from": "test-b@sixel.email", "subject": "No agent", "body": "test",
        }, headers=worker_auth)
        assert resp.status_code == 400

    def test_missing_from(self, client, worker_auth):
        resp = client.post("/webhooks/inbound", json={
            "agent_address": "test-a", "subject": "No from", "body": "test",
        }, headers=worker_auth)
        assert resp.status_code == 400

    def test_empty_agent_address(self, client, worker_auth):
        resp = client.post("/webhooks/inbound", json={
            "agent_address": "", "from": "test-b@sixel.email",
            "subject": "Empty agent", "body": "test",
        }, headers=worker_auth)
        assert resp.status_code == 400


class TestAgentLookup:
    """Agent lookup and validation."""

    def test_unknown_agent_dropped(self, inject_inbound):
        resp = inject_inbound("nonexistent-agent-xyz", "anyone@test.com")
        assert resp.status_code == 200
        assert resp.json()["status"] == "dropped"
        assert resp.json()["reason"] == "unknown_agent"

    def test_wrong_sender_dropped(self, inject_inbound):
        resp = inject_inbound("test-a", "stranger@evil.com")
        assert resp.status_code == 200
        assert resp.json()["status"] == "dropped"
        assert resp.json()["reason"] == "sender_not_allowed"

    def test_channel_inactive_dropped(self, inject_inbound, mock_pool):
        mock_pool.agents["test-a"]["channel_active"] = False
        resp = inject_inbound("test-a", "test-b@sixel.email")
        assert resp.status_code == 200
        assert resp.json()["status"] == "dropped"
        assert resp.json()["reason"] == "channel_inactive"

    def test_not_admin_approved_dropped(self, inject_inbound, mock_pool):
        mock_pool.agents["test-a"]["admin_approved"] = False
        resp = inject_inbound("test-a", "test-b@sixel.email")
        assert resp.status_code == 200
        assert resp.json()["status"] == "dropped"
        assert resp.json()["reason"] == "not_approved"


class TestNonceDisabled:
    """test-a has nonce_enabled=False — emails accepted directly."""

    def test_valid_message_accepted(self, inject_inbound):
        resp = inject_inbound(
            "test-a", "test-b@sixel.email",
            subject="Direct msg", body="Hello world",
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "received"

    def test_message_stored_in_db(self, inject_inbound, mock_pool):
        tag = uuid.uuid4().hex[:8]
        inject_inbound(
            "test-a", "test-b@sixel.email",
            subject=f"Stored {tag}", body=f"Check DB {tag}",
        )
        found = [m for m in mock_pool.messages if tag in m.get("subject", "")]
        assert len(found) == 1
        assert tag in found[0]["body"]

    def test_credit_deducted(self, inject_inbound, mock_pool):
        before = mock_pool.agents["test-a"]["credit_balance"]
        inject_inbound("test-a", "test-b@sixel.email",
                        subject="Credit test", body="deduct check")
        after = mock_pool.agents["test-a"]["credit_balance"]
        assert after == before - 1

    def test_no_credits_dropped(self, inject_inbound, mock_pool):
        mock_pool.agents["test-a"]["credit_balance"] = 0
        resp = inject_inbound("test-a", "test-b@sixel.email",
                               subject="No credits", body="should fail")
        assert resp.status_code == 200
        assert resp.json()["status"] == "dropped"
        assert resp.json()["reason"] == "insufficient_credits"

    def test_no_knock_sent(self, inject_inbound, mock_send_email):
        """Nonce-disabled agent should NOT trigger knock reply."""
        inject_inbound("test-a", "test-b@sixel.email",
                        subject="No knock", body="direct delivery")
        assert len(mock_send_email) == 0


class TestNonceEnabled:
    """test-b has nonce_enabled=True — requires nonce or triggers knock."""

    def test_no_nonce_triggers_knock(self, inject_inbound, mock_send_email):
        resp = inject_inbound("test-b", "test-a@sixel.email",
                               subject="Knock me", body="Need nonce")
        assert resp.status_code == 200
        assert resp.json()["status"] == "knock_replied"
        assert len(mock_send_email) == 1
        sent = mock_send_email[0]
        assert "test-a@sixel.email" in sent["to_address"]
        assert "Knock received" in sent["body"]

    def test_knock_includes_original_message(self, inject_inbound, mock_send_email):
        body_text = "Please forward this important info"
        inject_inbound("test-b", "test-a@sixel.email",
                        subject="Forward me", body=body_text)
        assert len(mock_send_email) == 1
        assert body_text in mock_send_email[0]["body"]

    def test_knock_reply_to_contains_nonce(self, inject_inbound, mock_send_email):
        inject_inbound("test-b", "test-a@sixel.email",
                        subject="Check reply-to", body="test")
        assert len(mock_send_email) == 1
        reply_to = mock_send_email[0]["reply_to"]
        assert reply_to.startswith("test-b+")
        assert reply_to.endswith("@sixel.email")

    def test_knock_no_credit_deducted(self, inject_inbound, mock_pool):
        before = mock_pool.agents["test-b"]["credit_balance"]
        inject_inbound("test-b", "test-a@sixel.email",
                        subject="No charge", body="knock is free")
        after = mock_pool.agents["test-b"]["credit_balance"]
        assert after == before

    def test_invalid_nonce_dropped(self, inject_inbound):
        resp = inject_inbound("test-b", "test-a@sixel.email",
                               subject="Bad nonce", body="test",
                               nonce="totally-invalid-nonce-value")
        assert resp.status_code == 200
        result = resp.json()
        assert result["status"] == "dropped"
        assert result["reason"] == "invalid_nonce"

    def test_valid_nonce_accepted(self, inject_inbound, mock_pool):
        """Valid nonce should deliver the message."""
        from tests.integration.conftest import TEST_AGENT_IDS
        from datetime import datetime, timedelta, timezone

        agent_id = TEST_AGENT_IDS["test-b"]
        nonce_str = "valid-test-nonce-" + uuid.uuid4().hex[:8]
        mock_pool.nonces[nonce_str] = {
            "agent_id": agent_id,
            "burned": False,
            "expires_at": datetime.now(timezone.utc) + timedelta(minutes=30),
        }

        resp = inject_inbound("test-b", "test-a@sixel.email",
                               subject="Nonce msg", body="Authenticated",
                               nonce=nonce_str)
        assert resp.status_code == 200
        assert resp.json()["status"] == "received"
        # Nonce should be burned
        assert mock_pool.nonces[nonce_str]["burned"] is True

    def test_valid_nonce_deducts_credit(self, inject_inbound, mock_pool):
        from tests.integration.conftest import TEST_AGENT_IDS
        from datetime import datetime, timedelta, timezone

        agent_id = TEST_AGENT_IDS["test-b"]
        nonce_str = "credit-nonce-" + uuid.uuid4().hex[:8]
        mock_pool.nonces[nonce_str] = {
            "agent_id": agent_id,
            "burned": False,
            "expires_at": datetime.now(timezone.utc) + timedelta(minutes=30),
        }

        before = mock_pool.agents["test-b"]["credit_balance"]
        inject_inbound("test-b", "test-a@sixel.email",
                        subject="Nonce credit", body="test",
                        nonce=nonce_str)
        after = mock_pool.agents["test-b"]["credit_balance"]
        assert after == before - 1

    def test_nonce_for_wrong_agent_dropped(self, inject_inbound, mock_pool):
        """Nonce belongs to test-a but message sent to test-b."""
        from tests.integration.conftest import TEST_AGENT_IDS
        from datetime import datetime, timedelta, timezone

        # Create nonce for test-a
        nonce_str = "wrong-agent-nonce-" + uuid.uuid4().hex[:8]
        mock_pool.nonces[nonce_str] = {
            "agent_id": TEST_AGENT_IDS["test-a"],  # belongs to test-a
            "burned": False,
            "expires_at": datetime.now(timezone.utc) + timedelta(minutes=30),
        }

        # Send to test-b with test-a's nonce
        resp = inject_inbound("test-b", "test-a@sixel.email",
                               subject="Wrong agent nonce", body="test",
                               nonce=nonce_str)
        assert resp.status_code == 200
        assert resp.json()["status"] == "dropped"
        assert resp.json()["reason"] == "nonce_agent_mismatch"


class TestAllstop:
    """Allstop kill switch via nonce starting with 'allstop-'."""

    def test_allstop_without_key_hash(self, inject_inbound):
        """Agent without allstop key hash — treated as invalid nonce."""
        resp = inject_inbound("test-a", "test-b@sixel.email",
                               subject="Allstop", body="kill",
                               nonce="allstop-some-key")
        assert resp.status_code == 200
        assert resp.json()["status"] == "dropped"

    def test_allstop_invalid_key(self, inject_inbound, mock_pool):
        """Wrong allstop key — dropped."""
        real_hash = hashlib.sha256(b"real-kill-key").hexdigest()
        mock_pool.agents["test-a"]["allstop_key_hash"] = real_hash

        resp = inject_inbound("test-a", "test-b@sixel.email",
                               subject="Allstop", body="kill",
                               nonce="allstop-wrong-key")
        assert resp.status_code == 200
        assert resp.json()["status"] == "dropped"
        assert resp.json()["reason"] == "invalid_nonce"

    def test_allstop_valid_key(self, inject_inbound, mock_pool):
        """Correct allstop key — deactivates channel."""
        kill_key = "real-kill-key"
        key_hash = hashlib.sha256(kill_key.encode()).hexdigest()
        mock_pool.agents["test-a"]["allstop_key_hash"] = key_hash

        resp = inject_inbound("test-a", "test-b@sixel.email",
                               subject="Allstop", body="kill",
                               nonce=f"allstop-{kill_key}")
        assert resp.status_code == 200
        assert resp.json()["status"] == "channel_deactivated"
        assert mock_pool.agents["test-a"]["channel_active"] is False


class TestAttachments:
    """Inbound attachment handling."""

    def test_attachment_stored(self, inject_inbound, mock_pool):
        tag = uuid.uuid4().hex[:8]
        content = f"File content {tag}".encode()
        b64 = base64.b64encode(content).decode()

        resp = inject_inbound(
            "test-a", "test-b@sixel.email",
            subject=f"Att {tag}", body=f"See attached {tag}",
            attachments=[{
                "filename": "test.txt",
                "mimeType": "text/plain",
                "contentBase64": b64,
            }],
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "received"
        assert len(mock_pool.attachments) == 1
        assert mock_pool.attachments[0]["filename"] == "test.txt"

    def test_multiple_attachments(self, inject_inbound, mock_pool):
        attachments = [
            {"filename": "a.txt", "mimeType": "text/plain",
             "contentBase64": base64.b64encode(b"aaa").decode()},
            {"filename": "b.txt", "mimeType": "text/plain",
             "contentBase64": base64.b64encode(b"bbb").decode()},
        ]
        inject_inbound("test-a", "test-b@sixel.email",
                        subject="Multi att", body="test",
                        attachments=attachments)
        assert len(mock_pool.attachments) == 2
        filenames = {a["filename"] for a in mock_pool.attachments}
        assert filenames == {"a.txt", "b.txt"}


class TestBinarySafety:
    """Binary content in message bodies."""

    def test_base64_in_body(self, inject_inbound):
        fake_image = base64.b64encode(b"\x89PNG" + b"\x00" * 1024).decode()
        body = f"Pasted image:\n{fake_image}"
        resp = inject_inbound("test-a", "test-b@sixel.email",
                               subject="Binary body", body=body)
        assert resp.status_code == 200
        assert resp.json()["status"] == "received"

    def test_large_body(self, inject_inbound):
        body = "x" * 50_000
        resp = inject_inbound("test-a", "test-b@sixel.email",
                               subject="Large body", body=body)
        assert resp.status_code == 200
        assert resp.json()["status"] == "received"

    def test_unicode_body(self, inject_inbound, mock_pool):
        tag = uuid.uuid4().hex[:8]
        body = f"Tag: {tag}\nEmoji: \U0001f600\nChinese: \u4f60\u597d"
        inject_inbound("test-a", "test-b@sixel.email",
                        subject=f"Unicode {tag}", body=body)
        found = [m for m in mock_pool.messages if tag in m.get("subject", "")]
        assert len(found) == 1
        assert "\u4f60\u597d" in found[0]["body"]
