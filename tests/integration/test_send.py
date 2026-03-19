"""Integration tests for POST /v1/send endpoint."""

import base64
import uuid


class TestSendAuth:
    def test_no_auth_401(self, client):
        resp = client.post("/v1/send", json={
            "subject": "No auth", "body": "test"
        })
        assert resp.status_code in (401, 403)

    def test_bad_key_401(self, client):
        resp = client.post("/v1/send", json={
            "subject": "Bad key", "body": "test"
        }, headers={"Authorization": "Bearer sm_live_totally_fake_key_12345"})
        assert resp.status_code in (401, 403)


class TestSendBasic:
    def test_send_success(self, client, auth_a, mock_send_email):
        resp = client.post("/v1/send", json={
            "subject": "Test send", "body": "Hello from integration test"
        }, headers=auth_a)
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] in ("sent", "delivered")
        assert "credits_remaining" in data

    def test_send_deducts_credit(self, client, auth_a, mock_pool, mock_send_email):
        before = mock_pool.agents["test-a"]["credit_balance"]
        client.post("/v1/send", json={
            "subject": "Credit send", "body": "Checking credit deduction"
        }, headers=auth_a)
        after = mock_pool.agents["test-a"]["credit_balance"]
        assert after < before

    def test_send_no_credits_402(self, client, auth_a, mock_pool, mock_send_email):
        mock_pool.agents["test-a"]["credit_balance"] = 0
        resp = client.post("/v1/send", json={
            "subject": "No credits", "body": "Should fail"
        }, headers=auth_a)
        assert resp.status_code == 402

    def test_send_empty_body_rejected(self, client, auth_a):
        resp = client.post("/v1/send", json={
            "subject": "Empty", "body": "   "
        }, headers=auth_a)
        assert resp.status_code == 422


class TestSendInternalRouting:
    """Agent-to-agent internal delivery (test-a -> test-b)."""

    def test_internal_delivery(self, client, auth_a, mock_pool, mock_send_email):
        tag = uuid.uuid4().hex[:8]
        resp = client.post("/v1/send", json={
            "subject": f"Internal {tag}",
            "body": f"Agent-to-agent {tag}",
        }, headers=auth_a)
        assert resp.status_code == 200
        assert resp.json()["status"] == "delivered"

        # Message should be stored for recipient
        b_msgs = [m for m in mock_pool.messages
                  if m["agent_id"] == mock_pool.agents["test-b"]["id"]
                  and tag in m.get("subject", "")]
        assert len(b_msgs) >= 1

    def test_internal_deducts_both_credits(self, client, auth_a, mock_pool, mock_send_email):
        before_a = mock_pool.agents["test-a"]["credit_balance"]
        before_b = mock_pool.agents["test-b"]["credit_balance"]

        client.post("/v1/send", json={
            "subject": "Credit both", "body": "Both agents charged"
        }, headers=auth_a)

        after_a = mock_pool.agents["test-a"]["credit_balance"]
        after_b = mock_pool.agents["test-b"]["credit_balance"]
        assert after_a < before_a
        assert after_b < before_b

    def test_recipient_inactive_rejected(self, client, auth_a, mock_pool, mock_send_email):
        mock_pool.agents["test-b"]["channel_active"] = False
        resp = client.post("/v1/send", json={
            "subject": "Inactive", "body": "Should fail"
        }, headers=auth_a)
        assert resp.status_code == 400


class TestSendAttachments:
    def test_send_with_attachment(self, client, auth_a, mock_send_email):
        content = base64.b64encode(b"test attachment data").decode()
        resp = client.post("/v1/send", json={
            "subject": "With attachment",
            "body": "See attached",
            "attachments": [{"filename": "data.bin", "content": content}],
        }, headers=auth_a)
        assert resp.status_code == 200
        assert resp.json()["status"] in ("sent", "delivered")

    def test_send_invalid_base64_rejected(self, client, auth_a):
        resp = client.post("/v1/send", json={
            "subject": "Bad attachment",
            "body": "Invalid base64",
            "attachments": [{"filename": "bad.bin", "content": "not!valid!base64!!!"}],
        }, headers=auth_a)
        assert resp.status_code == 400
