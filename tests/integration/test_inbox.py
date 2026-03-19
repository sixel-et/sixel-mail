"""Integration tests for GET /v1/inbox and attachment download."""

import base64
import uuid


class TestInboxAuth:
    def test_no_auth_401(self, client):
        resp = client.get("/v1/inbox")
        assert resp.status_code in (401, 403)

    def test_bad_key_401(self, client):
        resp = client.get("/v1/inbox",
                          headers={"Authorization": "Bearer sm_live_fake_key_xyz"})
        assert resp.status_code in (401, 403)


class TestInboxBasic:
    def test_empty_inbox(self, client, auth_a):
        resp = client.get("/v1/inbox", headers=auth_a)
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data["messages"], list)
        assert len(data["messages"]) == 0
        assert "credits_remaining" in data
        assert "agent_status" in data

    def test_message_returned(self, inject_inbound, client, auth_a):
        tag = uuid.uuid4().hex[:8]
        inject_inbound("test-a", "test-b@sixel.email",
                        subject=f"Inbox {tag}", body=f"Read me {tag}")

        resp = client.get("/v1/inbox", headers=auth_a)
        assert resp.status_code == 200
        messages = resp.json()["messages"]
        found = [m for m in messages if tag in (m.get("subject") or "")]
        assert len(found) == 1
        msg = found[0]
        assert tag in msg["body"]
        assert "id" in msg
        assert "received_at" in msg

    def test_messages_marked_read(self, inject_inbound, client, auth_a):
        tag = uuid.uuid4().hex[:8]
        inject_inbound("test-a", "test-b@sixel.email",
                        subject=f"MarkRead {tag}", body=f"Read once {tag}")

        # First poll — message present
        resp1 = client.get("/v1/inbox", headers=auth_a)
        found1 = [m for m in resp1.json()["messages"]
                  if tag in (m.get("subject") or "")]
        assert len(found1) == 1

        # Second poll — message marked read, should not appear
        resp2 = client.get("/v1/inbox", headers=auth_a)
        found2 = [m for m in resp2.json()["messages"]
                  if tag in (m.get("subject") or "")]
        assert len(found2) == 0

    def test_credits_in_response(self, client, auth_a):
        resp = client.get("/v1/inbox", headers=auth_a)
        assert resp.status_code == 200
        assert resp.json()["credits_remaining"] == 10000


class TestInboxAttachments:
    def test_attachment_metadata_in_inbox(self, inject_inbound, client, auth_a, mock_pool):
        tag = uuid.uuid4().hex[:8]
        b64 = base64.b64encode(b"metadata test").decode()
        inject_inbound("test-a", "test-b@sixel.email",
                        subject=f"AttMeta {tag}", body=f"Test {tag}",
                        attachments=[{"filename": "report.pdf",
                                       "mimeType": "application/pdf",
                                       "contentBase64": b64}])

        inbox = client.get("/v1/inbox", headers=auth_a).json()
        msg = next((m for m in inbox["messages"]
                    if tag in (m.get("subject") or "")), None)
        assert msg is not None
        assert len(msg["attachments"]) == 1
        att = msg["attachments"][0]
        assert att["filename"] == "report.pdf"
        assert "mime_type" in att
        assert "size_bytes" in att

    def test_download_attachment(self, inject_inbound, client, auth_a, mock_pool):
        tag = uuid.uuid4().hex[:8]
        content = b"downloadable content"
        b64 = base64.b64encode(content).decode()
        inject_inbound("test-a", "test-b@sixel.email",
                        subject=f"Download {tag}", body=f"Test {tag}",
                        attachments=[{"filename": "doc.pdf",
                                       "mimeType": "application/pdf",
                                       "contentBase64": b64}])

        inbox = client.get("/v1/inbox", headers=auth_a).json()
        msg = next((m for m in inbox["messages"]
                    if tag in (m.get("subject") or "")), None)
        assert msg is not None
        att = msg["attachments"][0]

        dl = client.get(
            f"/v1/inbox/{msg['id']}/attachments/{att['id']}",
            headers=auth_a,
        )
        assert dl.status_code == 200
        assert dl.content == content

    def test_download_wrong_message_404(self, inject_inbound, client, auth_a, mock_pool):
        tag = uuid.uuid4().hex[:8]
        b64 = base64.b64encode(b"test").decode()
        inject_inbound("test-a", "test-b@sixel.email",
                        subject=f"WrongMsg {tag}", body=f"Test {tag}",
                        attachments=[{"filename": "x.txt",
                                       "mimeType": "text/plain",
                                       "contentBase64": b64}])

        inbox = client.get("/v1/inbox", headers=auth_a).json()
        msg = next((m for m in inbox["messages"]
                    if tag in (m.get("subject") or "")), None)
        assert msg is not None
        att = msg["attachments"][0]

        # Try downloading with a fake message ID
        resp = client.get(
            f"/v1/inbox/00000000-0000-0000-0000-000000000000/attachments/{att['id']}",
            headers=auth_a,
        )
        assert resp.status_code == 404


class TestGetMessage:
    def test_get_specific_message(self, inject_inbound, client, auth_a):
        tag = uuid.uuid4().hex[:8]
        inject_inbound("test-a", "test-b@sixel.email",
                        subject=f"Specific {tag}", body=f"Find me {tag}")

        inbox = client.get("/v1/inbox", headers=auth_a).json()
        msg = next((m for m in inbox["messages"]
                    if tag in (m.get("subject") or "")), None)
        assert msg is not None

        resp = client.get(f"/v1/inbox/{msg['id']}", headers=auth_a)
        assert resp.status_code == 200
        data = resp.json()
        assert tag in data["subject"]
        assert tag in data["body"]

    def test_other_agents_message_404(self, inject_inbound, client, auth_a, auth_b):
        tag = uuid.uuid4().hex[:8]
        inject_inbound("test-a", "test-b@sixel.email",
                        subject=f"Private {tag}", body=f"Secret {tag}")

        inbox = client.get("/v1/inbox", headers=auth_a).json()
        msg = next((m for m in inbox["messages"]
                    if tag in (m.get("subject") or "")), None)
        assert msg is not None

        # Agent B should not be able to read A's message
        resp = client.get(f"/v1/inbox/{msg['id']}", headers=auth_b)
        assert resp.status_code == 404
