"""WebSocket client for the akenza data-streams API."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import random
from collections.abc import Callable, Iterable
from typing import Any

import aiohttp

from .const import (
    WS_BACKOFF_MAX,
    WS_GREETING_TIMEOUT,
    WS_HEARTBEAT,
    WS_RECEIVE_TIMEOUT,
    WS_SUBSCRIBE_CHUNK,
)
from .models import Sample

_LOGGER = logging.getLogger(__name__)


class AkenzaStream:
    """Maintain a WebSocket subscription for a set of assets with auto-reconnect."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        url: str,
        api_key: str,
        *,
        on_sample: Callable[[Sample], None],
        on_connection: Callable[[bool], None],
        on_auth_failed: Callable[[], None],
    ) -> None:
        """Initialise the stream (does not connect)."""
        self._session = session
        self._url = url
        self._api_key = api_key
        self._on_sample = on_sample
        self._on_connection = on_connection
        self._on_auth_failed = on_auth_failed
        self._asset_ids: set[str] = set()
        self._subscribed: set[str] = set()
        self._ws: aiohttp.ClientWebSocketResponse | None = None
        self._task: asyncio.Task[None] | None = None
        self._stopping = False
        self._message_id = 0
        self._connected = False
        self._logged_unavailable = False
        self._ever_connected = False

    @property
    def connected(self) -> bool:
        """Whether the stream is currently connected and subscribed."""
        return self._connected

    @property
    def subscribed_count(self) -> int:
        """Number of assets currently subscribed."""
        return len(self._subscribed)

    def start(self, create_task: Callable[[Any], asyncio.Task[None]]) -> None:
        """Start the connection loop using the provided task factory."""
        if self._task is not None:
            return
        self._stopping = False
        self._task = create_task(self._run())

    async def async_stop(self) -> None:
        """Stop the stream and close the connection."""
        self._stopping = True
        if self._ws is not None and not self._ws.closed:
            await self._ws.close()
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await self._task
            self._task = None

    def set_asset_ids(
        self, asset_ids: Iterable[str], create_task: Callable[[Any], asyncio.Task[None]]
    ) -> None:
        """Update the set of subscribed assets; diff is applied live if connected."""
        new_ids = set(asset_ids)
        added = new_ids - self._asset_ids
        removed = self._asset_ids - new_ids
        self._asset_ids = new_ids
        if self._ws is None or self._ws.closed or not self._connected:
            return
        if added or removed:
            create_task(self._apply_diff(added, removed))

    async def _apply_diff(self, added: set[str], removed: set[str]) -> None:
        ws = self._ws
        if ws is None or ws.closed:
            return
        try:
            if added:
                await self._send_subscriptions(ws, "subscribe", added)
            if removed:
                await self._send_subscriptions(ws, "unsubscribe", removed)
                self._subscribed -= removed
        except (aiohttp.ClientError, ConnectionResetError, RuntimeError) as err:
            _LOGGER.debug("Failed to update subscriptions: %s", err)

    def _next_id(self) -> int:
        self._message_id += 1
        return self._message_id

    async def _send_subscriptions(
        self, ws: aiohttp.ClientWebSocketResponse, kind: str, asset_ids: Iterable[str]
    ) -> None:
        ids = sorted(asset_ids)
        for start in range(0, len(ids), WS_SUBSCRIBE_CHUNK):
            chunk = ids[start : start + WS_SUBSCRIBE_CHUNK]
            # NOTE: the server rejects string message ids; use integers.
            await ws.send_json(
                {
                    "type": kind,
                    "id": self._next_id(),
                    "subscriptions": [{"assetId": asset_id, "topic": "*"} for asset_id in chunk],
                }
            )

    async def _run(self) -> None:
        attempt = 0
        while not self._stopping:
            try:
                await self._connect_once()
                attempt = 0
            except aiohttp.WSServerHandshakeError as err:
                if err.status in (401, 403):
                    _LOGGER.error("akenza WebSocket authentication failed (HTTP %s)", err.status)
                    self._set_connected(False)
                    self._on_auth_failed()
                    return
                _LOGGER.debug("WebSocket handshake failed: %s", err)
            except asyncio.CancelledError:
                # task cancelled by Home Assistant shutdown / entry unload
                self._stopping = True
                raise
            except (aiohttp.ClientError, TimeoutError, OSError, ValueError) as err:
                _LOGGER.debug("WebSocket connection error: %s", err)
            finally:
                self._ws = None
                self._subscribed = set()
                self._set_connected(False)
            if self._stopping:
                return
            delay = min(WS_BACKOFF_MAX, 2**attempt) * random.uniform(0.8, 1.2)
            attempt += 1
            await self._backoff_sleep(delay)

    async def _backoff_sleep(self, delay: float) -> None:
        await asyncio.sleep(delay)

    async def _connect_once(self) -> None:
        async with self._session.ws_connect(
            self._url,
            params={"xApiKey": self._api_key},
            heartbeat=WS_HEARTBEAT,
            receive_timeout=WS_RECEIVE_TIMEOUT,
        ) as ws:
            self._ws = ws
            await self._await_greeting(ws)
            if self._asset_ids:
                await self._send_subscriptions(ws, "subscribe", self._asset_ids)
            self._subscribed = set(self._asset_ids)
            self._set_connected(True)
            async for msg in ws:
                if msg.type is aiohttp.WSMsgType.TEXT:
                    try:
                        self._handle(msg.json())
                    except ValueError:
                        _LOGGER.debug("Ignoring non-JSON WebSocket message")
                elif msg.type in (
                    aiohttp.WSMsgType.CLOSE,
                    aiohttp.WSMsgType.CLOSING,
                    aiohttp.WSMsgType.CLOSED,
                    aiohttp.WSMsgType.ERROR,
                ):
                    break

    async def _await_greeting(self, ws: aiohttp.ClientWebSocketResponse) -> None:
        msg = await asyncio.wait_for(ws.receive(), WS_GREETING_TIMEOUT)
        if msg.type is not aiohttp.WSMsgType.TEXT:
            raise aiohttp.ClientError(f"unexpected frame {msg.type} instead of greeting")
        data = msg.json()
        if not isinstance(data, dict) or data.get("type") != "connected":
            raise aiohttp.ClientError(f"unexpected greeting: {data}")

    def _set_connected(self, connected: bool) -> None:
        if connected == self._connected:
            return
        self._connected = connected
        if connected:
            if self._logged_unavailable:
                _LOGGER.info("akenza WebSocket connection restored")
            self._logged_unavailable = False
            self._ever_connected = True
        elif self._ever_connected and not self._stopping and not self._logged_unavailable:
            _LOGGER.warning("akenza WebSocket connection lost, reconnecting")
            self._logged_unavailable = True
        self._on_connection(connected)

    def _handle(self, data: Any) -> None:
        if not isinstance(data, dict):
            return
        kind = data.get("type")
        if kind == "sample_insert":
            sample = data.get("sample")
            if isinstance(sample, dict) and (parsed := Sample.from_api(sample)):
                self._on_sample(parsed)
        elif kind == "subscribed":
            invalid = [
                s.get("assetId")
                for s in data.get("subscriptions") or []
                if isinstance(s, dict) and s.get("valid") is False
            ]
            if invalid:
                _LOGGER.warning("akenza rejected subscriptions for assets: %s", invalid)
        elif kind == "error":
            _LOGGER.warning("akenza WebSocket error: %s", data.get("message"))
        elif kind in ("pong", "connected", "unsubscribed"):
            return
        else:
            _LOGGER.debug("Unhandled WebSocket message type %s", kind)
