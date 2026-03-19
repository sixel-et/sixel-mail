"""Integration test fixtures.

Uses FastAPI TestClient with a mock database pool.
Tests the full request/response cycle through the webhook and API handlers
without requiring network access to Supabase.
"""

import copy
import hashlib
import json
import secrets
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from starlette.testclient import TestClient

TEST_WORKER_SECRET = "test-integration-secret-12345"

# Pre-computed from the test keys in .test-keys.json
TEST_KEYS = {
    "test-a": "sm_live_KODiDPifb_ohCn-xX13hP2MdUXFYAmhcFx-R1FOMoZE",
    "test-b": "sm_live__bz8BRsfKDsfQbknZVDZeR1hM3FTHL7knm8TK40zNiI",
}
TEST_KEY_HASHES = {k: hashlib.sha256(v.encode()).hexdigest() for k, v in TEST_KEYS.items()}
TEST_AGENT_IDS = {
    "test-a": "a1a1a1a1-0000-0000-0000-000000000001",
    "test-b": "b2b2b2b2-0000-0000-0000-000000000002",
}


class MockRecord(dict):
    """Dict that supports both key and attribute access like asyncpg.Record."""
    def __getattr__(self, key):
        try:
            return self[key]
        except KeyError:
            raise AttributeError(key)


def _make_agent(address, **overrides):
    """Create a mock agent record."""
    defaults = {
        "test-a": {
            "id": TEST_AGENT_IDS["test-a"],
            "address": "test-a",
            "allowed_contact": "test-b@sixel.email",
            "credit_balance": 10000,
            "channel_active": True,
            "nonce_enabled": False,
            "admin_approved": True,
            "allstop_key_hash": None,
            "heartbeat_enabled": False,
            "agent_down_notified": False,
            "cc_email": None,
        },
        "test-b": {
            "id": TEST_AGENT_IDS["test-b"],
            "address": "test-b",
            "allowed_contact": "test-a@sixel.email",
            "credit_balance": 10000,
            "channel_active": True,
            "nonce_enabled": True,
            "admin_approved": True,
            "allstop_key_hash": None,
            "heartbeat_enabled": False,
            "agent_down_notified": False,
            "cc_email": None,
        },
    }
    data = defaults.get(address, {})
    data.update(overrides)
    return MockRecord(data)


class MockPool:
    """In-memory mock for asyncpg.Pool that simulates test agents."""

    def __init__(self):
        self.agents = {
            "test-a": _make_agent("test-a"),
            "test-b": _make_agent("test-b"),
        }
        self.agents_by_id = {a["id"]: a for a in self.agents.values()}
        self.messages = []  # list of MockRecord
        self.attachments = []  # list of MockRecord
        self.nonces = {}  # nonce_str -> {"agent_id": ..., "burned": False, "expires_at": ...}
        self.credit_transactions = []

    def reset(self):
        """Reset to initial state."""
        self.agents = {
            "test-a": _make_agent("test-a"),
            "test-b": _make_agent("test-b"),
        }
        self.agents_by_id = {a["id"]: a for a in self.agents.values()}
        self.messages.clear()
        self.attachments.clear()
        self.nonces.clear()
        self.credit_transactions.clear()

    async def fetchrow(self, query, *args):
        q = query.strip().upper()

        # API key lookup
        if "FROM API_KEYS" in q:
            prefix, key_hash = args[0], args[1]
            for name, agent_key in TEST_KEYS.items():
                if agent_key[:16] == prefix and TEST_KEY_HASHES[name] == key_hash:
                    return MockRecord({"agent_id": TEST_AGENT_IDS[name]})
            return None

        # Agent lookup by address
        if "FROM AGENTS WHERE ADDRESS" in q:
            return copy.copy(self.agents.get(args[0]))

        # Agent lookup by id
        if "FROM AGENTS WHERE ID" in q:
            agent_id = str(args[0])
            return copy.copy(self.agents_by_id.get(agent_id))

        # Insert message RETURNING id
        if "INSERT INTO MESSAGES" in q:
            msg_id = str(uuid.uuid4())
            msg = MockRecord({
                "id": msg_id,
                "agent_id": args[0],
                "direction": "inbound",
                "subject": args[1] if len(args) > 1 else "",
                "body": args[2] if len(args) > 2 else "",
                "is_read": False,
                "encrypted": args[3] if len(args) > 3 else False,
                "created_at": datetime.now(timezone.utc),
            })
            self.messages.append(msg)
            return MockRecord({"id": msg_id})

        # Deduct credit (from deduct_credit service)
        if "UPDATE AGENTS" in q and "CREDIT_BALANCE - 1" in q:
            agent_id = str(args[0])
            agent = self.agents_by_id.get(agent_id)
            if agent and agent["credit_balance"] >= 1:
                agent["credit_balance"] -= 1
                return MockRecord({"credit_balance": agent["credit_balance"]})
            return None

        # Add credits
        if "UPDATE AGENTS" in q and "CREDIT_BALANCE +" in q:
            agent_id = str(args[0])
            amount = args[1]
            agent = self.agents_by_id.get(agent_id)
            if agent:
                agent["credit_balance"] += amount
                return MockRecord({"credit_balance": agent["credit_balance"]})
            return None

        # Validate nonce (burn it)
        if "UPDATE NONCES" in q and "BURNED = TRUE" in q and "BURNED = FALSE" in q and "EXPIRES_AT > NOW()" in q:
            nonce_str = args[0]
            nonce = self.nonces.get(nonce_str)
            if nonce and not nonce["burned"] and nonce["expires_at"] > datetime.now(timezone.utc):
                nonce["burned"] = True
                return MockRecord({"agent_id": nonce["agent_id"]})
            return None

        # Check expired nonce
        if "UPDATE NONCES" in q and "BURNED = TRUE" in q and "EXPIRES_AT <= NOW()" in q:
            nonce_str = args[0]
            nonce = self.nonces.get(nonce_str)
            if nonce and not nonce["burned"] and nonce["expires_at"] <= datetime.now(timezone.utc):
                nonce["burned"] = True
                return MockRecord({"agent_id": nonce["agent_id"]})
            return None

        # Agent down recovery
        if "UPDATE AGENTS" in q and "AGENT_DOWN_NOTIFIED = FALSE" in q:
            return None

        # Get single message by id
        if "FROM MESSAGES" in q and "WHERE ID" in q:
            msg_id = str(args[0])
            agent_id = str(args[1]) if len(args) > 1 else None
            for m in self.messages:
                if m["id"] == msg_id and (agent_id is None or m["agent_id"] == agent_id):
                    return m
            return None

        # Single attachment lookup by id
        if "FROM ATTACHMENTS" in q and "WHERE ID" in q:
            att_id = str(args[0])
            msg_id = str(args[1]) if len(args) > 1 else None
            for a in self.attachments:
                if a["id"] == att_id and (msg_id is None or a["message_id"] == msg_id):
                    return a
            return None

        # Stripe dedup
        if "FROM CREDIT_TRANSACTIONS" in q:
            return None

        return None

    async def fetchval(self, query, *args):
        row = await self.fetchrow(query, *args)
        if row:
            # Return first value
            return list(row.values())[0]
        return None

    async def fetch(self, query, *args):
        q = query.strip().upper()

        # Fetch unread inbound messages
        if "FROM MESSAGES" in q and "IS_READ = FALSE" in q:
            agent_id = str(args[0])
            return [m for m in self.messages
                    if m["agent_id"] == agent_id
                    and m.get("direction") == "inbound"
                    and not m.get("is_read", True)]

        # Fetch attachments for messages
        if "FROM ATTACHMENTS" in q:
            msg_ids = [str(mid) for mid in args[0]]
            return [a for a in self.attachments if str(a["message_id"]) in msg_ids]

        return []

    async def execute(self, query, *args):
        q = query.strip().upper()

        # Mark messages as read
        if "UPDATE MESSAGES SET IS_READ = TRUE" in q:
            ids = [str(i) for i in args[0]]
            for m in self.messages:
                if m["id"] in ids:
                    m["is_read"] = True
            return f"UPDATE {len(ids)}"

        # Insert attachment
        if "INSERT INTO ATTACHMENTS" in q:
            att = MockRecord({
                "id": str(uuid.uuid4()),
                "message_id": str(args[0]),
                "filename": args[1],
                "mime_type": args[2],
                "size_bytes": args[3],
                "content_base64": args[4],
                "created_at": datetime.now(timezone.utc),
            })
            self.attachments.append(att)
            return "INSERT 0 1"

        # Insert credit transaction
        if "INSERT INTO CREDIT_TRANSACTIONS" in q:
            self.credit_transactions.append(args)
            return "INSERT 0 1"

        # Insert nonce
        if "INSERT INTO NONCES" in q:
            agent_id = str(args[0])
            nonce_str = args[1]
            expires_at = args[2]
            self.nonces[nonce_str] = {
                "agent_id": agent_id,
                "burned": False,
                "expires_at": expires_at,
            }
            return "INSERT 0 1"

        # Update channel_active (allstop)
        if "UPDATE AGENTS SET CHANNEL_ACTIVE" in q:
            agent_id = str(args[0])
            agent = self.agents_by_id.get(agent_id)
            if agent:
                agent["channel_active"] = False
            return "UPDATE 1"

        # Delete api_keys (rotate)
        if "DELETE FROM API_KEYS" in q:
            return "DELETE 0"

        # Insert api_key
        if "INSERT INTO API_KEYS" in q:
            return "INSERT 0 1"

        # Update last_seen_at
        if "UPDATE AGENTS SET LAST_SEEN_AT" in q:
            return "UPDATE 1"

        return "OK"


# Module-level mock pool instance (shared across tests in module)
_mock_pool = MockPool()


@pytest.fixture(scope="module")
def mock_pool():
    return _mock_pool


@pytest.fixture(scope="module")
def client(mock_pool):
    """TestClient with mock DB and no-op lifespan."""
    import sys

    from app.config import settings
    original_secret = settings.cf_worker_secret
    object.__setattr__(settings, "cf_worker_secret", TEST_WORKER_SECRET)

    # Import the FastAPI instance (use alias to avoid shadowing with package)
    from app.main import app as fastapi_app

    @asynccontextmanager
    async def test_lifespan(a):
        yield

    original_lifespan = fastapi_app.router.lifespan_context
    fastapi_app.router.lifespan_context = test_lifespan

    # Mock get_pool in all modules that import it
    app_pkg = sys.modules["app"]
    db_mod = sys.modules.get("app.db") or __import__("app.db", fromlist=["db"])
    webhooks_mod = sys.modules.get("app.routes.webhooks") or __import__("app.routes.webhooks", fromlist=["webhooks"])
    api_mod = sys.modules.get("app.routes.api") or __import__("app.routes.api", fromlist=["api"])
    auth_mod = sys.modules.get("app.auth") or __import__("app.auth", fromlist=["auth"])

    original_get_pool = db_mod.get_pool

    async def mock_get_pool():
        return mock_pool

    db_mod.get_pool = mock_get_pool
    webhooks_mod.get_pool = mock_get_pool
    api_mod.get_pool = mock_get_pool
    auth_mod.get_pool = mock_get_pool

    with TestClient(fastapi_app, raise_server_exceptions=False) as c:
        yield c

    # Restore
    fastapi_app.router.lifespan_context = original_lifespan
    db_mod.get_pool = original_get_pool
    webhooks_mod.get_pool = original_get_pool
    api_mod.get_pool = original_get_pool
    auth_mod.get_pool = original_get_pool
    object.__setattr__(settings, "cf_worker_secret", original_secret)


@pytest.fixture(scope="module")
def test_keys():
    return TEST_KEYS.copy()


@pytest.fixture
def auth_a():
    return {"Authorization": f"Bearer {TEST_KEYS['test-a']}"}


@pytest.fixture
def auth_b():
    return {"Authorization": f"Bearer {TEST_KEYS['test-b']}"}


@pytest.fixture
def worker_auth():
    return {"X-Worker-Auth": TEST_WORKER_SECRET}


@pytest.fixture(autouse=True)
def reset_pool(mock_pool):
    """Reset mock pool state before each test."""
    mock_pool.reset()
    yield


@pytest.fixture(autouse=True)
def mock_send_email(monkeypatch):
    """Mock send_email to prevent actual sends. Returns captured calls."""
    sent = []

    async def fake_send(**kwargs):
        sent.append(kwargs)

    monkeypatch.setattr("app.routes.webhooks.send_email", fake_send)
    monkeypatch.setattr("app.routes.api.send_email", fake_send)
    return sent


@pytest.fixture
def inject_inbound(client, worker_auth):
    """Helper to POST to /webhooks/inbound."""
    def _inject(agent_address, sender, subject="Test", body="Test body",
                nonce=None, attachments=None):
        payload = {
            "agent_address": agent_address,
            "from": sender,
            "subject": subject,
            "body": body,
            "encrypted": False,
        }
        if nonce is not None:
            payload["nonce"] = nonce
        if attachments is not None:
            payload["attachments"] = attachments
        return client.post("/webhooks/inbound", json=payload, headers=worker_auth)
    return _inject
