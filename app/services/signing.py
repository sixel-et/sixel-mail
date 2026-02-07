import hashlib
import hmac
import time
import urllib.parse

from app.config import settings

EXPIRY_SECONDS = 86400 * 30  # 30 days


def sign_alert_url(agent_id: str, action: str) -> str:
    expires = int(time.time()) + EXPIRY_SECONDS
    payload = f"{agent_id}:{action}:{expires}"
    signature = hmac.new(
        settings.signing_secret.encode(), payload.encode(), hashlib.sha256
    ).hexdigest()[:16]
    params = urllib.parse.urlencode(
        {"agent": agent_id, "action": action, "expires": expires, "sig": signature}
    )
    return f"{settings.api_base_url}/alert?{params}"


def verify_signature(agent_id: str, action: str, expires: str, sig: str) -> bool:
    # Check expiry
    try:
        exp_int = int(expires)
    except ValueError:
        return False
    if time.time() > exp_int:
        return False

    # Verify HMAC
    payload = f"{agent_id}:{action}:{expires}"
    expected = hmac.new(
        settings.signing_secret.encode(), payload.encode(), hashlib.sha256
    ).hexdigest()[:16]
    return hmac.compare_digest(sig, expected)
