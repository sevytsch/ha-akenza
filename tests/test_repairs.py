"""Tests for the hub button, device events and repair issues."""

from datetime import UTC, datetime, timedelta

from homeassistant.core import HomeAssistant
from homeassistant.helpers import issue_registry as ir
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_capture_events,
    async_fire_time_changed,
)
from pytest_homeassistant_custom_component.test_util.aiohttp import (
    AiohttpClientMocker,
    AiohttpClientMockResponse,
)

from custom_components.akenza.const import (
    DOMAIN,
    EVENT_DEVICE_ADDED,
    EVENT_DEVICE_REMOVED,
    ISSUE_MISSING_PERMISSIONS,
    ISSUE_STREAM_DISCONNECTED,
    ISSUE_WORKSPACE_UNAVAILABLE,
)

from .conftest import BASE, CAT, WS_HOME, WS_LAB, load_fixture, mock_api, paged, setup_integration


async def test_scan_button_and_device_events(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    mock_config_entry: MockConfigEntry,
    mock_stream: None,
) -> None:
    """Pressing the hub button refreshes now; added/removed devices fire events."""
    await setup_integration(hass, mock_config_entry, aioclient_mock)
    assert hass.states.get("button.test_org_scan_for_new_devices") is not None
    added = async_capture_events(hass, EVENT_DEVICE_ADDED)
    removed = async_capture_events(hass, EVENT_DEVICE_REMOVED)

    assets = load_fixture("assets_list.json")
    remaining = [d for d in assets["content"] if d["id"] != CAT]
    remaining.append(
        {**remaining[0], "id": "02aaaaaaaaaaaaaa", "name": "Newcomer", "dataFlow": None, "tags": []}
    )
    aioclient_mock.clear_requests()
    aioclient_mock.post(f"{BASE}/v3/assets/list", json=paged(remaining))
    aioclient_mock.get(f"{BASE}/v3/devices/02aaaaaaaaaaaaaa/infer-schema", json={})
    aioclient_mock.get(f"{BASE}/v3/devices/02aaaaaaaaaaaaaa/query", json=[])

    await hass.services.async_call(
        "button", "press", {"entity_id": "button.test_org_scan_for_new_devices"}, blocking=True
    )
    await hass.async_block_till_done(wait_background_tasks=True)

    assert hass.states.get("binary_sensor.newcomer_online") is not None
    assert len(added) == 1
    assert added[0].data["akenza_id"] == "02aaaaaaaaaaaaaa"
    assert added[0].data["name"] == "Newcomer"
    assert added[0].data["workspace_id"] == WS_HOME
    assert added[0].data["config_entry_id"] == mock_config_entry.entry_id
    assert len(removed) == 1
    assert removed[0].data["akenza_id"] == CAT


async def test_missing_permissions_issue(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    mock_config_entry: MockConfigEntry,
    mock_stream: None,
) -> None:
    """A 403 on device types raises one repair issue naming the endpoint."""
    await setup_integration(hass, mock_config_entry, aioclient_mock)
    registry = ir.async_get(hass)
    issue = registry.async_get_issue(
        DOMAIN, f"{ISSUE_MISSING_PERMISSIONS}_{mock_config_entry.entry_id}"
    )
    assert issue is not None
    assert issue.translation_placeholders["endpoints"] == "device-types"
    assert issue.translation_placeholders["organization"] == "Test Org"


async def test_workspace_unavailable_issue_for_restricted_key(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    mock_config_entry: MockConfigEntry,
    mock_stream: None,
) -> None:
    """A selected workspace the key cannot access any more raises an issue."""
    # registered first so it takes precedence over the default mock
    aioclient_mock.get(f"{BASE}/v3/workspace-access", json={"all": False, "ids": [WS_HOME]})
    mock_api(aioclient_mock)
    mock_config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done(wait_background_tasks=True)
    issue = ir.async_get(hass).async_get_issue(
        DOMAIN, f"{ISSUE_WORKSPACE_UNAVAILABLE}_{mock_config_entry.entry_id}"
    )
    assert issue is not None
    assert issue.translation_placeholders["workspaces"] == WS_LAB


async def test_deleted_workspace_is_skipped(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    mock_config_entry: MockConfigEntry,
    mock_stream: None,
) -> None:
    """akenza reporting a workspace as not found -> issue, listing continues without it."""
    bodies: list[dict] = []

    async def handler(method, url, data):  # noqa: ANN001
        bodies.append(data)
        if WS_LAB in (data.get("workspaceIds") or []):
            return AiohttpClientMockResponse(
                method, url, status=404, json={"message": f"workspace with id {WS_LAB} not found"}
            )
        return AiohttpClientMockResponse(method, url, json=load_fixture("assets_list.json"))

    aioclient_mock.post(f"{BASE}/v3/assets/list", side_effect=handler)
    mock_api(aioclient_mock)
    mock_config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done(wait_background_tasks=True)
    assert bodies[0]["workspaceIds"] == [WS_HOME, WS_LAB]
    assert bodies[1]["workspaceIds"] == [WS_HOME]
    assert hass.states.get("sensor.kitchen_temperature") is not None
    issue = ir.async_get(hass).async_get_issue(
        DOMAIN, f"{ISSUE_WORKSPACE_UNAVAILABLE}_{mock_config_entry.entry_id}"
    )
    assert issue is not None
    assert issue.translation_placeholders["workspaces"] == WS_LAB


async def test_stream_disconnected_issue(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    mock_config_entry: MockConfigEntry,
    mock_stream: None,
) -> None:
    """A stream outage longer than 10 minutes raises an issue; reconnecting clears it."""
    await setup_integration(hass, mock_config_entry, aioclient_mock)
    coordinator = mock_config_entry.runtime_data
    issue_id = f"{ISSUE_STREAM_DISCONNECTED}_{mock_config_entry.entry_id}"
    registry = ir.async_get(hass)

    coordinator._handle_connection(False)
    async_fire_time_changed(hass, datetime.now(UTC) + timedelta(minutes=5))
    await hass.async_block_till_done()
    assert registry.async_get_issue(DOMAIN, issue_id) is None
    async_fire_time_changed(hass, datetime.now(UTC) + timedelta(minutes=11))
    await hass.async_block_till_done()
    assert registry.async_get_issue(DOMAIN, issue_id) is not None

    coordinator._handle_connection(True)
    await hass.async_block_till_done()
    assert registry.async_get_issue(DOMAIN, issue_id) is None
