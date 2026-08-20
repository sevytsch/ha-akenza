"""Tests for the WebSocket stream client."""

from __future__ import annotations

import asyncio
import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import aiohttp
import pytest

from custom_components.akenza.models import Sample
from custom_components.akenza.stream import AkenzaStream


class FakeMsg:
    def __init__(self, type_: aiohttp.WSMsgType, data: Any = None) -> None:
        self.type = type_
        self.data = json.dumps(data) if data is not None else None

    def json(self) -> Any:
        return json.loads(self.data)


class FakeWS:
    """Scriptable WebSocket."""

    def __init__(self, script: list[FakeMsg], *, hold: bool = False) -> None:
        self.script = list(script)
        self.sent: list[dict[str, Any]] = []
        self.closed = False
        self.hold = hold
        self._closed_event = asyncio.Event()

    async def receive(self) -> FakeMsg:
        return self.script.pop(0)

    async def send_json(self, data: dict[str, Any]) -> None:
        self.sent.append(data)

    async def close(self) -> None:
        self.closed = True
        self._closed_event.set()

    def __aiter__(self):
        return self

    async def __anext__(self) -> FakeMsg:
        if not self.script:
            if self.hold and not self.closed:
                await self._closed_event.wait()
            raise StopAsyncIteration
        return self.script.pop(0)


class FakeSession:
    def __init__(self, connections: list[FakeWS | Exception]) -> None:
        self.connections = list(connections)
        self.calls: list[dict[str, Any]] = []

    def ws_connect(self, url: str, **kwargs: Any):
        self.calls.append({"url": url, **kwargs})
        item = self.connections.pop(0)

        class _Ctx:
            async def __aenter__(self_inner):
                if isinstance(item, Exception):
                    raise item
                return item

            async def __aexit__(self_inner, *exc):
                return False

        return _Ctx()


def greeting() -> FakeMsg:
    return FakeMsg(aiohttp.WSMsgType.TEXT, {"type": "connected"})


def make_task(coro):
    return asyncio.get_running_loop().create_task(coro)


async def test_subscribe_and_samples() -> None:
    """Greeting, integer-id subscribe, samples delivered, error frames tolerated."""
    ws = FakeWS(
        [
            greeting(),
            FakeMsg(aiohttp.WSMsgType.TEXT, {"type": "subscribed", "subscriptions": [{"assetId": "a", "valid": True}]}),
            FakeMsg(aiohttp.WSMsgType.TEXT, {"type": "sample_insert", "sample": {"deviceId": "a", "topic": "default", "timestamp": "2026-08-20T15:15:34.919Z", "data": {"t": 1}}}),
            FakeMsg(aiohttp.WSMsgType.TEXT, {"type": "error", "message": "boom"}),
            FakeMsg(aiohttp.WSMsgType.TEXT, {"type": "sample_insert", "sample": {"deviceId": "a", "topic": "x", "data": "not-a-dict"}}),
            FakeMsg(aiohttp.WSMsgType.CLOSE),
        ]
    )
    session = FakeSession([ws])
    samples: list[Sample] = []
    connections: list[bool] = []
    stream = AkenzaStream(session, "wss://x/v3/data-streams", "KEY", on_sample=samples.append, on_connection=connections.append, on_auth_failed=lambda: None)
    ids = [f"{i:016x}" for i in range(150)]
    stream.set_asset_ids(ids, make_task)
    with patch("custom_components.akenza.stream.AkenzaStream._backoff_sleep", AsyncMock(side_effect=asyncio.CancelledError)):
        stream.start(make_task)
        with pytest.raises(asyncio.CancelledError):
            await stream._task
    assert session.calls[0]["params"] == {"xApiKey": "KEY"}
    assert [m["type"] for m in ws.sent] == ["subscribe", "subscribe"]
    assert isinstance(ws.sent[0]["id"], int)
    assert len(ws.sent[0]["subscriptions"]) == 100 and len(ws.sent[1]["subscriptions"]) == 50
    assert ws.sent[0]["subscriptions"][0] == {"assetId": ids[0], "topic": "*"}
    assert len(samples) == 1 and samples[0].data == {"t": 1}
    assert connections == [True, False]


async def test_reconnect_with_backoff() -> None:
    """After a drop the stream reconnects and resubscribes."""
    ws1 = FakeWS([greeting(), FakeMsg(aiohttp.WSMsgType.CLOSED)])
    ws2 = FakeWS([greeting(), FakeMsg(aiohttp.WSMsgType.CLOSED)])
    session = FakeSession([ws1, aiohttp.ClientConnectionError("down"), ws2])
    sleeps: list[float] = []
    stop = asyncio.Event()

    async def fake_sleep(_self, delay: float) -> None:
        sleeps.append(delay)
        if len(sleeps) == 3:
            stop.set()
            await asyncio.Event().wait()

    stream = AkenzaStream(session, "wss://x", "KEY", on_sample=lambda s: None, on_connection=lambda c: None, on_auth_failed=lambda: None)
    stream.set_asset_ids(["a"], make_task)
    with patch("custom_components.akenza.stream.AkenzaStream._backoff_sleep", fake_sleep):
        stream.start(make_task)
        await asyncio.wait_for(stop.wait(), 5)
        await stream.async_stop()
    assert len(session.calls) == 3
    assert ws2.sent[0]["type"] == "subscribe"
    assert sleeps[0] <= 1.3 and sleeps[1] <= 2.5 and sleeps[1] > sleeps[0] * 0.5


async def test_auth_failure_stops_loop() -> None:
    """A 401 handshake calls on_auth_failed and ends the loop."""
    err = aiohttp.WSServerHandshakeError(MagicMock(), (), status=401, message="nope")
    session = FakeSession([err])
    auth_failed = MagicMock()
    stream = AkenzaStream(session, "wss://x", "KEY", on_sample=lambda s: None, on_connection=lambda c: None, on_auth_failed=auth_failed)
    stream.start(make_task)
    await stream._task
    auth_failed.assert_called_once()
    assert stream.connected is False


async def test_live_diff_subscribe() -> None:
    """Changing asset ids while connected sends subscribe/unsubscribe deltas."""
    ws = FakeWS([greeting()], hold=True)
    session = FakeSession([ws])
    stream = AkenzaStream(session, "wss://x", "KEY", on_sample=lambda s: None, on_connection=lambda c: None, on_auth_failed=lambda: None)
    stream.set_asset_ids(["a", "b"], make_task)
    stream.start(make_task)
    for _ in range(10):
        await asyncio.sleep(0)
        if stream.connected:
            break
    assert stream.connected
    stream.set_asset_ids(["b", "c"], make_task)
    await asyncio.sleep(0)
    await asyncio.sleep(0)
    kinds = [(m["type"], [s["assetId"] for s in m["subscriptions"]]) for m in ws.sent]
    assert kinds == [("subscribe", ["a", "b"]), ("subscribe", ["c"]), ("unsubscribe", ["a"])]
    await stream.async_stop()
