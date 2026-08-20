"""Integration-level tests: setup, entities, push, poll, unload."""

from datetime import UTC, datetime, timedelta

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry, async_fire_time_changed
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from custom_components.akenza.const import DOMAIN
from custom_components.akenza.models import Sample

from .conftest import BASE, CAT, KITCHEN, SILENT, load_fixture, paged, setup_integration


async def test_setup_creates_devices_and_entities(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker, mock_config_entry: MockConfigEntry, mock_stream: None, caplog
) -> None:
    """Devices, schema-based and inferred entities exist with seeded states."""
    await setup_integration(hass, mock_config_entry, aioclient_mock)
    assert mock_config_entry.state is ConfigEntryState.LOADED
    assert "non existing `via_device`" not in caplog.text

    device_registry = dr.async_get(hass)
    kitchen = device_registry.async_get_device(identifiers={(DOMAIN, KITCHEN)})
    assert kitchen is not None
    assert kitchen.manufacturer == "Elsys"
    assert kitchen.model == "ERS Eco Lite LoRa"
    assert kitchen.serial_number == "A1B2C3D4E5F60001"
    hub = device_registry.async_get_device(identifiers={(DOMAIN, "org_1111111111111111")})
    assert hub is not None and kitchen.via_device_id == hub.id

    state = hass.states.get("sensor.kitchen_temperature")
    assert state is not None
    assert state.state == "27.8"
    assert state.attributes["unit_of_measurement"] == "°C"
    assert state.attributes["device_class"] == "temperature"
    assert state.attributes["topic"] == "default"

    battery = hass.states.get("sensor.kitchen_battery_level")
    assert battery is not None and battery.state == "60.0"
    entity_registry = er.async_get(hass)
    battery_entry = entity_registry.async_get("sensor.kitchen_battery_level")
    assert battery_entry is not None and battery_entry.entity_category == "diagnostic"

    # configuration topic entities are created but disabled
    nfc = entity_registry.async_get_entity_id("binary_sensor", DOMAIN, f"{DOMAIN}_{KITCHEN}_configuration_nfcDisable")
    assert nfc is not None
    assert entity_registry.async_get(nfc).disabled_by is er.RegistryEntryDisabler.INTEGRATION

    # untyped HTTP device: entities from infer-schema + data
    cat = hass.states.get("sensor.cat_tracker_at_home")
    assert cat is not None and cat.state == "0"

    # device without any data still has an online sensor and no value entities
    assert hass.states.get("binary_sensor.silent_device_online") is not None
    silent_entities = [e for e in entity_registry.entities.values() if f"_{SILENT}_" in (e.unique_id or "")]
    assert {e.unique_id.split(f"_{SILENT}_")[-1] for e in silent_entities} == {"meta_online", "meta_last_seen"}

    # boolean from live data -> binary sensor (inferred, unknown device type)
    window = hass.states.get("binary_sensor.bathroom_valve_open_window")
    assert window is not None and window.state == "off"

    online = hass.states.get("binary_sensor.kitchen_online")
    assert online is not None and online.state == "on"
    stream = hass.states.get("binary_sensor.test_org_live_stream")
    assert stream is not None and stream.state == "off"
    count = hass.states.get("sensor.test_org_devices")
    assert count is not None and count.state == "5"


async def test_live_sample_updates_only_that_device(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker, mock_config_entry: MockConfigEntry, mock_stream: None
) -> None:
    """A pushed sample updates the entity; older samples are ignored; new keys create entities."""
    await setup_integration(hass, mock_config_entry, aioclient_mock)
    coordinator = mock_config_entry.runtime_data
    now = datetime(2026, 8, 20, 16, 0, tzinfo=UTC)
    coordinator._handle_sample(Sample(KITCHEN, "default", now, {"temperature": 21.5, "humidity": 40, "light": 5}))
    await hass.async_block_till_done()
    assert hass.states.get("sensor.kitchen_temperature").state == "21.5"
    assert hass.states.get("sensor.kitchen_temperature").attributes["last_sample"] == now.isoformat()

    coordinator._handle_sample(Sample(KITCHEN, "default", now - timedelta(minutes=5), {"temperature": 99}))
    await hass.async_block_till_done()
    assert hass.states.get("sensor.kitchen_temperature").state == "21.5"

    coordinator._handle_sample(Sample(KITCHEN, "default", now + timedelta(minutes=1), {"temperature": 22, "newKey": 7, "flag": True}))
    await hass.async_block_till_done()
    assert hass.states.get("sensor.kitchen_new_key").state == "7"
    assert hass.states.get("binary_sensor.kitchen_flag").state == "on"
    assert hass.states.get("sensor.kitchen_last_seen").state == (now + timedelta(minutes=1)).isoformat()

    # unknown device is ignored
    coordinator._handle_sample(Sample("ffffffffffffffff", "default", now, {"x": 1}))


async def test_poll_removes_and_adds_devices(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker, mock_config_entry: MockConfigEntry, mock_stream: None
) -> None:
    """The metadata poll removes vanished devices and adds new ones."""
    await setup_integration(hass, mock_config_entry, aioclient_mock)
    assets = load_fixture("assets_list.json")
    remaining = [d for d in assets["content"] if d["id"] != CAT]
    remaining.append({**remaining[0], "id": "02aaaaaaaaaaaaaa", "name": "Newcomer", "dataFlow": None})
    aioclient_mock.clear_requests()
    aioclient_mock.post(f"{BASE}/v3/assets/list", json=paged(remaining))
    aioclient_mock.get(f"{BASE}/v3/devices/02aaaaaaaaaaaaaa/infer-schema", json={})
    aioclient_mock.get(f"{BASE}/v3/devices/02aaaaaaaaaaaaaa/query", json=[])

    async_fire_time_changed(hass, datetime.now(UTC) + timedelta(minutes=16))
    await hass.async_block_till_done(wait_background_tasks=True)

    device_registry = dr.async_get(hass)
    assert device_registry.async_get_device(identifiers={(DOMAIN, CAT)}) is None
    assert device_registry.async_get_device(identifiers={(DOMAIN, "02aaaaaaaaaaaaaa")}) is not None
    assert hass.states.get("binary_sensor.newcomer_online") is not None
    assert hass.states.get("sensor.cat_tracker_at_home") is None


async def test_poll_auth_failure_triggers_reauth(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker, mock_config_entry: MockConfigEntry, mock_stream: None
) -> None:
    """A 401 during the poll starts a reauth flow."""
    await setup_integration(hass, mock_config_entry, aioclient_mock)
    aioclient_mock.clear_requests()
    aioclient_mock.post(f"{BASE}/v3/assets/list", status=401, json={"message": "Invalid token"})
    async_fire_time_changed(hass, datetime.now(UTC) + timedelta(minutes=16))
    await hass.async_block_till_done(wait_background_tasks=True)
    flows = hass.config_entries.flow.async_progress()
    assert any(f["context"].get("source") == "reauth" for f in flows)


async def test_unload(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker, mock_config_entry: MockConfigEntry, mock_stream: None
) -> None:
    """Unloading stops everything."""
    await setup_integration(hass, mock_config_entry, aioclient_mock)
    assert await hass.config_entries.async_unload(mock_config_entry.entry_id)
    await hass.async_block_till_done()
    assert mock_config_entry.state is ConfigEntryState.NOT_LOADED
    assert hass.states.get("sensor.kitchen_temperature").state == "unavailable"


async def test_remove_device(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker, mock_config_entry: MockConfigEntry, mock_stream: None, hass_ws_client
) -> None:
    """Known devices cannot be removed via the UI, stale ones can."""
    from custom_components.akenza import async_remove_config_entry_device

    await setup_integration(hass, mock_config_entry, aioclient_mock)
    device_registry = dr.async_get(hass)
    kitchen = device_registry.async_get_device(identifiers={(DOMAIN, KITCHEN)})
    assert await async_remove_config_entry_device(hass, mock_config_entry, kitchen) is False
    stale = device_registry.async_get_or_create(config_entry_id=mock_config_entry.entry_id, identifiers={(DOMAIN, "stale")})
    assert await async_remove_config_entry_device(hass, mock_config_entry, stale) is True


async def test_failed_poll_keeps_entities_available(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker, mock_config_entry: MockConfigEntry, mock_stream: None
) -> None:
    """A failing metadata poll does not make live entities unavailable."""
    await setup_integration(hass, mock_config_entry, aioclient_mock)
    aioclient_mock.clear_requests()
    aioclient_mock.post(f"{BASE}/v3/assets/list", status=503, json={"message": "down"})
    from unittest.mock import AsyncMock, patch

    with patch("custom_components.akenza.api._sleep", AsyncMock()):
        async_fire_time_changed(hass, datetime.now(UTC) + timedelta(minutes=16))
        await hass.async_block_till_done(wait_background_tasks=True)
    assert mock_config_entry.runtime_data.last_update_success is False
    assert hass.states.get("sensor.kitchen_temperature").state == "27.8"
