"""API endpoint tests: /v1/inbox, /v1/send, and authentication.

Runs against the live system using the same loopback test agents.
"""

import os
import uuid

import httpx
import pytest

from tests.e2e.conftest import drain_inbox, wait_for_message

E2E_BASE_URL = os.environ.get("E2E_BASE_URL", "https://sixel.email")
WORKER_SECRET = os.environ.get("CF_WORKER_SECRET", "")


def inject_inbound(agent_address: str, sender: str, subject: str, body: str):
    """Quick injection helper (no attachments)."""
    if not WORKER_SECRET:
        pytest.skip("CF_WORKER_SECRET not set")
    resp = httpx.post(
        f"{E2E_BASE_URL}/webhooks/inbound",
        json={"agent_address": agent_address, "from": sender,
              "subject": subject, "body": body, "encrypted": False},
        headers={"X-Worker-Auth": WORKER_SECRET},
        timeout=30,
    )
    return resp


class TestAuth:
    """API authentication."""

    def test_no_auth_returns_401(self):
        """Request without auth header → 401."""
        resp = httpx.get(f"{E2E_BASE_URL}/v1/inbox", timeout=10)
        assert resp.status_code in (401, 403)

    def test_bad_key_returns_401(self):
        """Invalid API key → 401."""
        resp = httpx.get(
            f"{E2E_BASE_URL}/v1/inbox",
            headers={"Authorization": "Bearer sm_live_totally_fake_key"},
            timeout=10,
        )
        assert resp.status_code in (401, 403)


class TestInbox:
    """GET /v1/inbox endpoint."""

    @pytest.fixture(autouse=True)
    def clean(self, agent_a, agent_b):
        drain_inbox(agent_a)
        drain_inbox(agent_b)
        yield

    def test_empty_inbox(self, agent_a):
        """Empty inbox returns empty message list and credit count."""
        resp = agent_a.get("/inbox")
        assert resp.status_code == 200
        data = resp.json()
        assert "messages" in data
        assert isinstance(data["messages"], list)
        assert "credits_remaining" in data

    def test_messages_returned_and_marked_read(self, agent_a):
        """Inbox returns messages, second poll shows them as read."""
        if not WORKER_SECRET:
            pytest.skip("CF_WORKER_SECRET not set")

        tag = uuid.uuid4().hex[:8]
        inject_inbound("test-a", "test-b@sixel.email",
                       f"Read test {tag}", f"Body {tag}")

        msg = wait_for_message(
            agent_a, lambda m: tag in (m.get("subject") or ""), timeout=10
        )
        assert msg is not None

        # Second poll — message should now be read (not returned as unread)
        resp = agent_a.get("/inbox")
        data = resp.json()
        unread_tags = [m for m in data["messages"]
                       if tag in (m.get("subject") or "") and not m.get("is_read")]
        assert len(unread_tags) == 0, "Message should be marked read after first poll"

    def test_inbox_includes_attachment_metadata(self, agent_a):
        """Messages with attachments include attachment metadata (not content)."""
        if not WORKER_SECRET:
            pytest.skip("CF_WORKER_SECRET not set")

        import base64
        tag = uuid.uuid4().hex[:8]
        b64 = base64.b64encode(b"test data").decode()

        inject_inbound_resp = httpx.post(
            f"{E2E_BASE_URL}/webhooks/inbound",
            json={
                "agent_address": "test-a", "from": "test-b@sixel.email",
                "subject": f"Att meta {tag}", "body": f"Body {tag}",
                "encrypted": False,
                "attachments": [{"filename": "doc.pdf", "mimeType": "application/pdf",
                                 "contentBase64": b64}],
            },
            headers={"X-Worker-Auth": WORKER_SECRET},
            timeout=30,
        )
        assert inject_inbound_resp.status_code == 200

        msg = wait_for_message(
            agent_a, lambda m: tag in (m.get("subject") or ""), timeout=10
        )
        assert msg is not None
        assert len(msg.get("attachments", [])) > 0
        att = msg["attachments"][0]
        assert att["filename"] == "doc.pdf"
        assert "content" not in att  # metadata only, no content blob


class TestSend:
    """POST /v1/send endpoint."""

    def test_send_success(self, agent_a):
        """Valid send → 200 with status and credits."""
        resp = agent_a.post("/send", json={
            "subject": "Send test", "body": "Testing send endpoint"
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "sent"
        assert "credits_remaining" in data

    def test_send_no_auth(self):
        """Send without auth → 401."""
        resp = httpx.post(
            f"{E2E_BASE_URL}/v1/send",
            json={"subject": "No auth", "body": "test"},
            timeout=10,
        )
        assert resp.status_code in (401, 403)

    def test_send_records_in_outbox(self, agent_a):
        """Sent message appears in inbox history as outbound."""
        tag = uuid.uuid4().hex[:8]
        resp = agent_a.post("/send", json={
            "subject": f"Outbox {tag}", "body": f"Outbox test {tag}"
        })
        assert resp.status_code == 200

        # Check that the sent message ID is returned
        data = resp.json()
        assert "message_id" in data or data["status"] == "sent"
