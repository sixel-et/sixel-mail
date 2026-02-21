"""E2E test fixtures for loopback testing against the live system."""

import json
import os
import time
from pathlib import Path

import httpx
import pytest

E2E_BASE_URL = os.environ.get("E2E_BASE_URL", "https://sixel.email")
POLL_INTERVAL = 5  # seconds between inbox checks
POLL_TIMEOUT = 60  # max seconds to wait for email delivery


@pytest.fixture(scope="session")
def test_keys():
    """Load test agent API keys from .test-keys.json."""
    key_file = Path(__file__).parent.parent / ".test-keys.json"
    if not key_file.exists():
        pytest.skip("No test keys found. Run setup_test_agents.py first.")
    return json.loads(key_file.read_text())


@pytest.fixture(scope="session")
def agent_a(test_keys):
    """httpx client authenticated as test-a (nonce disabled)."""
    client = httpx.Client(
        base_url=f"{E2E_BASE_URL}/v1",
        headers={"Authorization": f"Bearer {test_keys['test-a']}"},
        timeout=30,
    )
    yield client
    client.close()


@pytest.fixture(scope="session")
def agent_b(test_keys):
    """httpx client authenticated as test-b (nonce enabled)."""
    client = httpx.Client(
        base_url=f"{E2E_BASE_URL}/v1",
        headers={"Authorization": f"Bearer {test_keys['test-b']}"},
        timeout=30,
    )
    yield client
    client.close()


def drain_inbox(client: httpx.Client):
    """Read all messages from an agent's inbox to clear it."""
    resp = client.get("/inbox")
    if resp.status_code == 200:
        return resp.json().get("messages", [])
    return []


def wait_for_message(client: httpx.Client, match_fn, timeout=POLL_TIMEOUT):
    """Poll inbox until a message matching match_fn arrives, or timeout.

    Returns the matching message or None.
    """
    deadline = time.time() + timeout
    while time.time() < deadline:
        resp = client.get("/inbox")
        if resp.status_code == 200:
            for msg in resp.json().get("messages", []):
                if match_fn(msg):
                    return msg
        time.sleep(POLL_INTERVAL)
    return None
