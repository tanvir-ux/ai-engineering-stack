"""A small in-memory sliding-window rate limiter.

Good enough for one API replica. With several replicas, move the counters to Redis or enforce the
limit at the ingress (see `deploy/k8s`), because each replica would otherwise count separately.
"""

from __future__ import annotations

import time
from collections import defaultdict, deque


class RateLimiter:
    def __init__(self, limit: int, window_seconds: float = 60.0) -> None:
        self.limit, self.window = limit, window_seconds
        self._hits: dict[str, deque[float]] = defaultdict(deque)

    def check(self, key: str, now: float | None = None) -> float:
        """Record a hit. Returns 0.0 if allowed, otherwise seconds until a slot frees up."""
        t = time.monotonic() if now is None else now
        q = self._hits[key]
        while q and t - q[0] >= self.window:
            q.popleft()
        if len(q) >= self.limit:
            return max(0.001, self.window - (t - q[0]))
        q.append(t)
        return 0.0
