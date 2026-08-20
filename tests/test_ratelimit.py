"""Tests for the token bucket."""

from unittest.mock import patch

from custom_components.akenza.ratelimit import TokenBucket


async def test_burst_then_wait() -> None:
    """Burst passes immediately; the next call waits."""
    bucket = TokenBucket(rate=10, burst=3)
    sleeps: list[float] = []

    async def fake_sleep(delay: float) -> None:
        sleeps.append(delay)

    with patch("custom_components.akenza.ratelimit._sleep", fake_sleep):
        for _ in range(3):
            await bucket.acquire()
        assert sleeps == []
        await bucket.acquire()
    assert len(sleeps) == 1
    assert 0.05 < sleeps[0] <= 0.11


async def test_penalize() -> None:
    """penalize forces a wait."""
    bucket = TokenBucket(rate=10, burst=5)
    bucket.penalize(2.0)
    assert bucket.tokens <= -19.9
