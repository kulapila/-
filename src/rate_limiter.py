"""Token-bucket rate limiter for DeepSeek API (RPM window)."""

from __future__ import annotations

import asyncio
import time
from collections import deque


class RateLimiter:
    """Async token-bucket rate limiter with sliding-window RPM tracking."""

    def __init__(self, max_rpm: int = 60) -> None:
        self.max_rpm = max_rpm
        self._window: deque[float] = deque()
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        """Wait until a request token is available."""
        async with self._lock:
            now = time.monotonic()
            # Remove timestamps older than 60 seconds
            cutoff = now - 60
            while self._window and self._window[0] < cutoff:
                self._window.popleft()
            # If at capacity, wait for the oldest slot to expire
            if len(self._window) >= self.max_rpm:
                wait_time = self._window[0] - cutoff + 0.1
                if wait_time > 0:
                    await asyncio.sleep(wait_time)
                    # Reclean after sleep
                    now = time.monotonic()
                    cutoff = now - 60
                    while self._window and self._window[0] < cutoff:
                        self._window.popleft()
            self._window.append(time.monotonic())

    @property
    def current_rpm(self) -> int:
        """Number of requests in the current minute window."""
        cutoff = time.monotonic() - 60
        return sum(1 for t in self._window if t >= cutoff)

    @property
    def usage_info(self) -> dict:
        return {"rpm_used": self.current_rpm, "rpm_max": self.max_rpm}
