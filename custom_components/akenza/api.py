"""REST client for the akenza public API v3."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Iterable
from typing import Any

import aiohttp

from .const import API_TIMEOUT, PAGE_SIZE, RATE_LIMIT_BURST, RATE_LIMIT_RATE, WS_PATH
from .models import (
    AkenzaDevice,
    AkenzaDeviceType,
    Organization,
    Sample,
    Tag,
    Workspace,
    WorkspaceAccess,
)
from .ratelimit import TokenBucket

_LOGGER = logging.getLogger(__name__)

_RETRY_STATUSES = {429, 500, 502, 503, 504}
_MAX_ATTEMPTS = 3


class AkenzaError(Exception):
    """Base error."""


class AkenzaConnectionError(AkenzaError):
    """Network / timeout / unexpected server error."""


class AkenzaAuthError(AkenzaError):
    """Invalid API key (HTTP 401)."""


class AkenzaForbiddenError(AkenzaError):
    """The API key lacks permission for this endpoint (HTTP 403)."""


class AkenzaNotFoundError(AkenzaError):
    """Entity not found (HTTP 404)."""


class AkenzaApiClient:
    """Thin async client with rate limiting and error mapping."""

    def __init__(self, session: aiohttp.ClientSession, api_key: str, base_url: str) -> None:
        """Initialise the client."""
        self._session = session
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._limiter = TokenBucket(RATE_LIMIT_RATE, RATE_LIMIT_BURST)

    @property
    def base_url(self) -> str:
        """REST base URL."""
        return self._base_url

    @property
    def websocket_url(self) -> str:
        """WebSocket data-streams URL derived from the base URL."""
        scheme_swapped = self._base_url.replace("https://", "wss://", 1).replace(
            "http://", "ws://", 1
        )
        return scheme_swapped + WS_PATH

    @property
    def api_key(self) -> str:
        """API key (used for the WebSocket query parameter)."""
        return self._api_key

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json: Any = None,
    ) -> Any:
        url = f"{self._base_url}{path}"
        headers = {"x-api-key": self._api_key, "Accept": "application/json"}
        last_exc: Exception | None = None
        for attempt in range(1, _MAX_ATTEMPTS + 1):
            await self._limiter.acquire()
            try:
                async with self._session.request(
                    method,
                    url,
                    params=params,
                    json=json,
                    headers=headers,
                    timeout=aiohttp.ClientTimeout(total=API_TIMEOUT),
                ) as resp:
                    remaining = resp.headers.get("x-ratelimit-remaining")
                    if remaining == "0":
                        self._limiter.penalize(1.0)
                    if resp.status == 401:
                        raise AkenzaAuthError(await _error_text(resp))
                    if resp.status == 403:
                        raise AkenzaForbiddenError(await _error_text(resp))
                    if resp.status == 404:
                        raise AkenzaNotFoundError(await _error_text(resp))
                    if resp.status in _RETRY_STATUSES:
                        text = await _error_text(resp)
                        last_exc = AkenzaConnectionError(f"HTTP {resp.status}: {text}")
                        if resp.status == 429:
                            retry_after = resp.headers.get("Retry-After")
                            delay = (
                                float(retry_after) if retry_after and retry_after.isdigit() else 1.0
                            )
                            self._limiter.penalize(delay)
                        if attempt < _MAX_ATTEMPTS:
                            await _sleep(min(2**attempt, 10))
                            continue
                        raise last_exc
                    if resp.status >= 400:
                        raise AkenzaConnectionError(
                            f"HTTP {resp.status}: {await _error_text(resp)}"
                        )
                    if resp.status == 204:
                        return None
                    return await resp.json(content_type=None)
            except (aiohttp.ClientError, TimeoutError) as err:
                last_exc = AkenzaConnectionError(str(err))
                if attempt < _MAX_ATTEMPTS:
                    await _sleep(min(2**attempt, 10))
                    continue
                raise last_exc from err
        raise last_exc or AkenzaConnectionError("request failed")

    async def _paged(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json: Any = None,
        max_pages: int = 200,
    ) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        page = 0
        while page < max_pages:
            query = {"page": page, "size": PAGE_SIZE, **(params or {})}
            data = await self._request(method, path, params=query, json=json)
            if isinstance(data, list):
                items.extend(i for i in data if isinstance(i, dict))
                break
            if not isinstance(data, dict):
                break
            content = data.get("content") or []
            items.extend(i for i in content if isinstance(i, dict))
            if data.get("last", True) or not content:
                break
            page += 1
        return items

    # --- discovery -------------------------------------------------------

    async def async_get_organization(self) -> Organization:
        """Return the organization the API key belongs to."""
        data = await self._request(
            "GET", "/v3/organizations", params={"size": 1, "minimal": "true"}
        )
        content = (data or {}).get("content") or []
        if not content:
            raise AkenzaForbiddenError("API key has no organization access")
        org = content[0]
        return Organization(id=str(org["id"]), name=str(org.get("name") or org["id"]))

    async def async_get_workspace_access(self, organization_id: str) -> WorkspaceAccess:
        """Return which workspaces the key may read assets from."""
        data = await self._request(
            "GET",
            "/v3/workspace-access",
            params={"organizationId": organization_id, "scope": "ASSET", "verb": "READ"},
        )
        data = data or {}
        return WorkspaceAccess(
            all=bool(data.get("all")),
            ids=frozenset(str(i) for i in (data.get("ids") or [])),
        )

    async def async_list_workspaces(self, organization_id: str) -> list[Workspace]:
        """List workspaces of an organization."""
        items = await self._paged(
            "GET", "/v3/workspaces", params={"organizationId": organization_id}
        )
        return [
            Workspace(id=str(w["id"]), name=str(w.get("name") or w["id"]))
            for w in items
            if "id" in w
        ]

    async def async_list_tags(self, workspace_id: str) -> list[Tag]:
        """List tags of a workspace."""
        items = await self._paged("GET", "/v3/tags", params={"workspaceId": workspace_id})
        return [
            Tag(id=str(t["id"]), name=str(t.get("name") or t["id"]), workspace_id=workspace_id)
            for t in items
            if "id" in t
        ]

    async def async_list_devices(
        self, organization_id: str, workspace_ids: Iterable[str] | None = None
    ) -> list[AkenzaDevice]:
        """List all devices of the organization, optionally limited to workspaces."""
        body: dict[str, Any] = {"organizationId": organization_id}
        ids = [w for w in (workspace_ids or []) if w]
        if ids:
            body["workspaceIds"] = ids
        items = await self._paged("POST", "/v3/assets/list", params={"sort": "name,asc"}, json=body)
        devices: list[AkenzaDevice] = []
        for item in items:
            if item.get("type", "DEVICE") != "DEVICE" or "id" not in item:
                continue
            try:
                devices.append(AkenzaDevice.from_api(item))
            except (KeyError, TypeError, ValueError) as err:
                _LOGGER.debug("Skipping malformed device %s: %s", item.get("id"), err)
        return devices

    # --- per device ------------------------------------------------------

    async def async_get_device_type(self, device_type_id: str) -> AkenzaDeviceType:
        """Fetch a device type including its schemas."""
        data = await self._request("GET", f"/v3/device-types/{device_type_id}")
        return AkenzaDeviceType.from_api(data)

    async def async_infer_schema(self, device_id: str) -> dict[str, dict[str, Any]]:
        """Return the inferred per-topic schema of a device ({} if no data)."""
        data = await self._request("GET", f"/v3/devices/{device_id}/infer-schema")
        if not isinstance(data, dict):
            return {}
        return {str(k): v for k, v in data.items() if isinstance(v, dict)}

    async def async_send_downlink(self, device_id: str, body: dict[str, Any]) -> Any:
        """Queue a downlink for a device (LoRaWAN or MQTT body as documented by akenza)."""
        return await self._request("POST", f"/v3/devices/{device_id}/downlink", json=body)

    async def async_get_topics(self, device_id: str) -> list[str]:
        """Return the topics that hold stored data for a device."""
        data = await self._request("GET", f"/v3/devices/{device_id}/query/topics")
        return [str(t) for t in data] if isinstance(data, list) else []

    async def async_query_topic_latest(self, device_id: str, topic: str) -> Sample | None:
        """Return the newest sample of one topic (None if the topic has no data)."""
        try:
            data = await self._request(
                "GET",
                f"/v3/devices/{device_id}/query",
                params={"topic": topic, "limit": 1, "skip": 0},
            )
        except AkenzaNotFoundError:
            return None
        if isinstance(data, list) and data and isinstance(data[0], dict):
            return Sample.from_api(data[0], device_id)
        return None

    async def async_query_latest(self, device_id: str, limit: int) -> list[Sample]:
        """Return the newest samples across all topics (newest first)."""
        try:
            data = await self._request(
                "GET",
                f"/v3/devices/{device_id}/query",
                params={"topic": "*", "limit": limit, "skip": 0},
            )
        except AkenzaNotFoundError:
            return []
        samples: list[Sample] = []
        for item in data if isinstance(data, list) else []:
            if isinstance(item, dict) and (sample := Sample.from_api(item, device_id)):
                samples.append(sample)
        return samples


async def _sleep(seconds: float) -> None:
    await asyncio.sleep(seconds)


async def _error_text(resp: aiohttp.ClientResponse) -> str:
    try:
        data = await resp.json(content_type=None)
    except aiohttp.ContentTypeError, ValueError:
        return (await resp.text())[:200]
    if isinstance(data, dict):
        return str(data.get("message") or data.get("error") or data)[:200]
    return str(data)[:200]
