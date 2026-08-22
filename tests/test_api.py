"""Tests for the REST client."""

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from custom_components.akenza.api import AkenzaApiClient, AkenzaAuthError, AkenzaConnectionError

from .conftest import BASE, ORG_ID, load_fixture, paged


async def test_pagination_and_models(hass: HomeAssistant, aioclient_mock: AiohttpClientMocker) -> None:
    """Two pages are merged and loraProperties are never exposed."""
    page0 = load_fixture("assets_list.json")
    page0.update(last=False, totalPages=2)
    page1 = paged([{"id": "02ffffffffffffff", "name": "Extra", "type": "DEVICE", "workspaceId": "w", "organizationId": ORG_ID, "loraProperties": {"applicationKey": "secret"}}])
    aioclient_mock.post(f"{BASE}/v3/assets/list", side_effect=None, json=page0)
    client = AkenzaApiClient(async_get_clientsession(hass), "k", BASE)
    # first call returns page0, second page1
    aioclient_mock.clear_requests()
    responses = iter([page0, page1])

    async def handler(method, url, data):  # noqa: ANN001
        from pytest_homeassistant_custom_component.test_util.aiohttp import (
            AiohttpClientMockResponse,
        )

        return AiohttpClientMockResponse(method, url, json=next(responses))

    aioclient_mock.post(f"{BASE}/v3/assets/list", side_effect=handler)
    devices = await client.async_list_devices(ORG_ID, ["w"])
    assert len(devices) == 7
    assert devices[-1].name == "Extra"
    assert not hasattr(devices[-1], "loraProperties")
    assert aioclient_mock.mock_calls[0][2] == {"workspaceIds": ["w"]}
    assert aioclient_mock.mock_calls[0][3]["x-api-key"] == "k"


async def test_auth_error(hass: HomeAssistant, aioclient_mock: AiohttpClientMocker) -> None:
    """401 raises AkenzaAuthError."""
    aioclient_mock.get(f"{BASE}/v3/organizations", status=401, json={"message": "Invalid token provided"})
    client = AkenzaApiClient(async_get_clientsession(hass), "bad", BASE)
    with pytest.raises(AkenzaAuthError):
        await client.async_get_organization()


async def test_retry_on_429(hass: HomeAssistant, aioclient_mock: AiohttpClientMocker) -> None:
    """429 is retried; persistent failure raises a connection error."""
    aioclient_mock.get(f"{BASE}/v3/organizations", status=429, json={"message": "slow down"})
    client = AkenzaApiClient(async_get_clientsession(hass), "k", BASE)
    from unittest.mock import AsyncMock, patch

    with patch("custom_components.akenza.api._sleep", AsyncMock()), pytest.raises(AkenzaConnectionError):
        await client.async_get_organization()
    assert aioclient_mock.call_count == 3


async def test_websocket_url() -> None:
    """The WebSocket URL is derived from the base URL."""
    client = AkenzaApiClient(None, "k", "https://api.example.akenza.io/")  # type: ignore[arg-type]
    assert client.websocket_url == "wss://api.example.akenza.io/v3/data-streams"


async def test_list_devices_without_workspaces_uses_organization(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """Without a workspace selection the organization-wide listing is used."""
    aioclient_mock.post(f"{BASE}/v3/assets/list", json=load_fixture("assets_list.json"))
    client = AkenzaApiClient(async_get_clientsession(hass), "k", BASE)
    await client.async_list_devices(ORG_ID, [])
    assert aioclient_mock.mock_calls[0][2] == {"organizationId": ORG_ID}
