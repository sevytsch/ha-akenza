"""Shared fixtures."""

from __future__ import annotations

import json
from collections.abc import Generator
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest
from homeassistant.const import CONF_API_KEY
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from custom_components.akenza.const import (
    CONF_BASE_URL,
    CONF_ORGANIZATION_ID,
    CONF_ORGANIZATION_NAME,
    CONF_WORKSPACE_IDS,
    DOMAIN,
)

FIXTURES = Path(__file__).parent / "fixtures"
BASE = "https://api.akenza.io"
ORG_ID = "1111111111111111"
WS_HOME = "2222222222222222"
WS_LAB = "3333333333333333"
KITCHEN = "020784546ed5d03b"
GARDEN = "02bf028baeb96713"
CAT = "025d93694916aadb"
SILENT = "02ba658a48d50849"
VALVE = "0293268877b09633"
ERS_ECO_TYPE = "331b994e3d4d295b"


def load_fixture(name: str) -> Any:
    """Load a JSON fixture."""
    return json.loads((FIXTURES / name).read_text())


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations: None) -> None:
    """Enable custom integrations."""


@pytest.fixture
def mock_stream() -> Generator[None]:
    """Prevent the real WebSocket from connecting."""
    with patch("custom_components.akenza.stream.AkenzaStream.start"):
        yield


def paged(content: list[dict[str, Any]]) -> dict[str, Any]:
    """Wrap content in a single-page response."""
    return {
        "content": content,
        "totalElements": len(content),
        "totalPages": 1,
        "last": True,
        "first": True,
        "number": 0,
        "size": 100,
        "numberOfElements": len(content),
        "empty": not content,
    }


KITCHEN_SAMPLES = [
    {
        "timestamp": "2026-08-20T14:58:38.275Z",
        "deviceId": KITCHEN,
        "topic": "default",
        "data": {"light": 93, "temperature": 27.8, "humidity": 50},
    },
    {
        "timestamp": "2026-08-20T14:48:36.445Z",
        "deviceId": KITCHEN,
        "topic": "default",
        "data": {"light": 220, "temperature": 27.7, "humidity": 50},
    },
]

CAT_INFER = {
    "cat": {
        "title": "Cat",
        "type": "object",
        "properties": {
            "atHome": {"title": "At Home", "type": "number", "inferred": True},
            "batteryLevel": {"title": "Battery Level", "type": "number", "inferred": True},
        },
    }
}
CAT_SAMPLES = [
    {
        "timestamp": "2026-08-20T15:15:00.207Z",
        "deviceId": CAT,
        "topic": "cat",
        "data": {"atHome": 0, "batteryLevel": 37},
    }
]
VALVE_SAMPLES = [
    {
        "timestamp": "2026-08-20T15:16:38.534Z",
        "deviceId": VALVE,
        "topic": "default",
        "data": {"targetTemperature": 18, "sensorTemperature": 26.24, "openWindow": False},
    }
]


def mock_api(aioclient_mock: AiohttpClientMocker, *, assets: dict[str, Any] | None = None) -> None:
    """Register the default REST responses."""
    aioclient_mock.get(
        f"{BASE}/v3/organizations",
        json=paged([{"id": ORG_ID, "name": "Test Org", "version": 1}]),
    )
    aioclient_mock.get(f"{BASE}/v3/workspace-access", json={"all": True, "ids": []})
    aioclient_mock.get(
        f"{BASE}/v3/workspaces",
        json=paged([{"id": WS_HOME, "name": "Home"}, {"id": WS_LAB, "name": "Lab"}]),
    )
    aioclient_mock.get(
        f"{BASE}/v3/tags",
        json=paged([{"id": "7100000000000001", "name": "Indoor", "workspaceId": WS_HOME}]),
    )
    aioclient_mock.post(f"{BASE}/v3/assets/list", json=assets or load_fixture("assets_list.json"))
    aioclient_mock.get(
        f"{BASE}/v3/device-types/{ERS_ECO_TYPE}", json=load_fixture("device_type_ers_eco.json")
    )
    aioclient_mock.get(f"{BASE}/v3/device-types/337096c7a576c35e", status=404, json={"message": "nf"})
    aioclient_mock.get(f"{BASE}/v3/device-types/3372f14fe98432c0", status=403, json={"message": "no"})
    aioclient_mock.get(f"{BASE}/v3/devices/{KITCHEN}/infer-schema", json={})
    aioclient_mock.get(
        f"{BASE}/v3/devices/{KITCHEN}/query",
        params={"topic": "*", "limit": "25", "skip": "0"},
        json=KITCHEN_SAMPLES,
    )
    aioclient_mock.get(f"{BASE}/v3/devices/{KITCHEN}/query/topics", json=["default", "lifecycle"])
    aioclient_mock.get(
        f"{BASE}/v3/devices/{KITCHEN}/query",
        params={"topic": "lifecycle", "limit": "1", "skip": "0"},
        json=[
            {
                "timestamp": "2026-08-20T14:58:38.275Z",
                "deviceId": KITCHEN,
                "topic": "lifecycle",
                "data": {"batteryVoltage": 3.291, "batteryLevel": 60.0},
            }
        ],
    )
    aioclient_mock.get(f"{BASE}/v3/devices/{CAT}/infer-schema", json=CAT_INFER)
    aioclient_mock.get(f"{BASE}/v3/devices/{CAT}/query", json=CAT_SAMPLES)
    aioclient_mock.get(f"{BASE}/v3/devices/{CAT}/query/topics", json=["cat"])
    aioclient_mock.get(f"{BASE}/v3/devices/{GARDEN}/infer-schema", json={})
    aioclient_mock.get(f"{BASE}/v3/devices/{GARDEN}/query", json=[])
    aioclient_mock.get(f"{BASE}/v3/devices/{SILENT}/infer-schema", json={})
    aioclient_mock.get(
        f"{BASE}/v3/devices/{SILENT}/query", status=404, json={"message": "no samples"}
    )
    aioclient_mock.get(f"{BASE}/v3/devices/{VALVE}/infer-schema", json={})
    aioclient_mock.get(f"{BASE}/v3/devices/{VALVE}/query", json=VALVE_SAMPLES)
    aioclient_mock.get(f"{BASE}/v3/devices/{VALVE}/query/topics", json=["default"])
    aioclient_mock.get(f"{BASE}/v3/devices/{GARDEN}/query/topics", json=[])
    aioclient_mock.get(f"{BASE}/v3/devices/{SILENT}/query/topics", json=[])


@pytest.fixture
def mock_config_entry() -> MockConfigEntry:
    """A configured entry for the test organization."""
    return MockConfigEntry(
        domain=DOMAIN,
        title="Test Org",
        unique_id=ORG_ID,
        data={
            CONF_API_KEY: "secret-key",
            CONF_BASE_URL: BASE,
            CONF_ORGANIZATION_ID: ORG_ID,
            CONF_ORGANIZATION_NAME: "Test Org",
        },
        options={CONF_WORKSPACE_IDS: [WS_HOME, WS_LAB]},
    )


async def setup_integration(
    hass: HomeAssistant, entry: MockConfigEntry, aioclient_mock: AiohttpClientMocker
) -> None:
    """Set up the integration and wait for background seeding."""
    mock_api(aioclient_mock)
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done(wait_background_tasks=True)
