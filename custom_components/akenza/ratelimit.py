"""Async token bucket used to stay below akenza's API rate limit."""

from __future__ import annotations

import asyncio
import time


async def _sleep(seconds: float) -> None:
    await asyncio.sleep(seconds)


class TokenBucket:
    """Token bucket: `rate` tokens per second, up to `burst` stored tokens."""

    def __init__(self, rate: float, burst: int) -> None:
        """Initialise a full bucket."""
        self._rate = rate
        self._burst = float(burst)
        self._tokens = float(burst)
        self._updated = time.monotonic()
        self._lock = asyncio.Lock()

    def _refill(self) -> None:
        now = time.monotonic()
        self._tokens = min(self._burst, self._tokens + (now - self._updated) * self._rate)
        self._updated = now

    async def acquire(self) -> None:
        """Wait until a token is available and consume it."""
        async with self._lock:
            self._refill()
            self._tokens -= 1
            wait = 0.0 if self._tokens >= 0 else -self._tokens / self._rate
        if wait > 0:
            await _sleep(wait)

    def penalize(self, seconds: float) -> None:
        """Force subsequent callers to wait at least `seconds`."""
        self._refill()
        self._tokens = min(self._tokens, -seconds * self._rate)

    @property
    def tokens(self) -> float:
        """Currently available tokens (may be negative)."""
        self._refill()
        return self._tokens
