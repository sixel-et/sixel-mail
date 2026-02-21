"""Unit tests for app/ratelimit.py — sliding window rate limiter."""

import time
from unittest.mock import patch

from app.ratelimit import RateLimiter


class TestRateLimiter:

    def test_under_limit_passes(self):
        rl = RateLimiter()
        assert rl.check("k", limit=5, window_seconds=60) is True

    def test_at_limit_blocks(self):
        rl = RateLimiter()
        for _ in range(5):
            rl.check("k", limit=5, window_seconds=60)
        assert rl.check("k", limit=5, window_seconds=60) is False

    def test_window_expiry_resets(self):
        rl = RateLimiter()
        for _ in range(5):
            rl.check("k", limit=5, window_seconds=1)

        assert rl.check("k", limit=5, window_seconds=1) is False

        # Advance time past window
        with patch("app.ratelimit.time.time", return_value=time.time() + 2):
            assert rl.check("k", limit=5, window_seconds=1) is True

    def test_independent_keys(self):
        rl = RateLimiter()
        for _ in range(5):
            rl.check("a", limit=5, window_seconds=60)
        # "a" is exhausted, "b" should be fine
        assert rl.check("a", limit=5, window_seconds=60) is False
        assert rl.check("b", limit=5, window_seconds=60) is True

    def test_remaining_count(self):
        rl = RateLimiter()
        assert rl.remaining("k", limit=10, window_seconds=60) == 10
        rl.check("k", limit=10, window_seconds=60)
        assert rl.remaining("k", limit=10, window_seconds=60) == 9

    def test_remaining_at_zero(self):
        rl = RateLimiter()
        for _ in range(10):
            rl.check("k", limit=10, window_seconds=60)
        assert rl.remaining("k", limit=10, window_seconds=60) == 0


class TestKnockRateCheck:
    """Test the knock rate limiter from webhooks.py."""

    def test_under_limit(self):
        from app.routes.webhooks import _check_knock_rate, _knock_timestamps
        _knock_timestamps.clear()
        assert _check_knock_rate("test-agent") is True

    def test_at_limit_blocks(self):
        from app.routes.webhooks import _check_knock_rate, _knock_timestamps, KNOCK_RATE_LIMIT
        _knock_timestamps.clear()
        for _ in range(KNOCK_RATE_LIMIT):
            _check_knock_rate("test-agent")
        assert _check_knock_rate("test-agent") is False

    def test_window_expiry(self):
        from app.routes.webhooks import _check_knock_rate, _knock_timestamps, KNOCK_RATE_LIMIT, KNOCK_RATE_WINDOW
        _knock_timestamps.clear()
        # Fill up
        for _ in range(KNOCK_RATE_LIMIT):
            _check_knock_rate("test-agent")
        assert _check_knock_rate("test-agent") is False

        # Move all timestamps to the past
        _knock_timestamps["test-agent"] = [
            time.time() - KNOCK_RATE_WINDOW - 1
            for _ in _knock_timestamps["test-agent"]
        ]
        assert _check_knock_rate("test-agent") is True
