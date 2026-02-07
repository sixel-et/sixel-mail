import time
from collections import defaultdict


class RateLimiter:
    """Simple in-memory rate limiter using sliding window counters."""

    def __init__(self):
        # {key: [(timestamp, count)]}
        self._windows: dict[str, list[tuple[float, int]]] = defaultdict(list)

    def _cleanup(self, key: str, window_seconds: float):
        cutoff = time.time() - window_seconds
        self._windows[key] = [
            (ts, c) for ts, c in self._windows[key] if ts > cutoff
        ]

    def check(self, key: str, limit: int, window_seconds: float) -> bool:
        """Returns True if the request is allowed, False if rate limited."""
        now = time.time()
        self._cleanup(key, window_seconds)

        total = sum(c for _, c in self._windows[key])
        if total >= limit:
            return False

        self._windows[key].append((now, 1))
        return True

    def remaining(self, key: str, limit: int, window_seconds: float) -> int:
        self._cleanup(key, window_seconds)
        total = sum(c for _, c in self._windows[key])
        return max(0, limit - total)


# Global instance
limiter = RateLimiter()

# Limits from spec
SEND_LIMIT = 100  # messages per day per agent
SEND_WINDOW = 86400  # 24 hours

POLL_LIMIT = 120  # polls per minute per agent
POLL_WINDOW = 60  # 1 minute
