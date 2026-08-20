"""Tests for tracker, event, downlink service, custom fields and the data-keys-only option."""

from datetime import UTC, datetime, timedelta

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import device_registry as dr
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from custom_components.akenza import build_downlink_body
from custom_components.akenza.const import CONF_DATA_KEYS_ONLY, DOMAIN
from custom_components.akenza.models import Sample

from .conftest import BASE, KITCHEN, TRACKER, setup_integration


async def test_tracker_and_area(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker, mock_config_entry: MockConfigEntry, mock_stream: None
) -> None:
    """A topic with latitude/longitude becomes a GPS tracker; Room custom field suggests the area."""
    await setup_integration(hass, mock_config_entry, aioclient_mock)
    tracker = hass.states.get("device_tracker.garage_tracker_position_position")
    assert tracker is not None
    assert tracker.attributes["latitude"] == 47.41
    assert tracker.attributes["longitude"] == 8.53
    assert tracker.attributes["gps_accuracy"] == 12
    assert tracker.attributes["source_type"] == "gps"
    assert hass.states.get("device_tracker.kitchen_position") is None

    device = dr.async_get(hass).async_get_device(identifiers={(DOMAIN, TRACKER)})
    assert device is not None and device.area_id == "garage"
    ident = hass.states.get("sensor.garage_tracker_akenza_id")
    assert ident.attributes["custom_fields"] == {"Room": "Garage", "Floor": 2.0}


async def test_button_event(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker, mock_config_entry: MockConfigEntry, mock_stream: None
) -> None:
    """Button keys get an event entity that fires on new pressed samples only."""
    await setup_integration(hass, mock_config_entry, aioclient_mock)
    event = hass.states.get("event.garage_tracker_button1")
    assert event is not None and event.state == "unknown"
    coordinator = mock_config_entry.runtime_data
    now = datetime(2026, 8, 20, 16, 0, tzinfo=UTC)
    coordinator._handle_sample(Sample(TRACKER, "default", now, {"button1": True}))
    await hass.async_block_till_done()
    fired = hass.states.get("event.garage_tracker_button1")
    assert fired.state != "unknown" and fired.attributes["event_type"] == "pressed"
    # a released sample must not fire again
    coordinator._handle_sample(Sample(TRACKER, "default", now + timedelta(seconds=1), {"button1": False}))
    await hass.async_block_till_done()
    assert hass.states.get("event.garage_tracker_button1").state == fired.state
    # the regular binary sensor still exists alongside
    assert hass.states.get("binary_sensor.garage_tracker_button1").state == "off"


def test_build_downlink_body() -> None:
    """Request bodies per connectivity."""
    assert build_downlink_body("LORA", payload={"a": 1}, payload_hex=None, port=2, confirmed=True, topic=None) == {
        "loraDownlink": {"port": 2, "confirmed": True, "payload": {"a": 1}}
    }
    assert build_downlink_body("LORA", payload=None, payload_hex="0e14", port=1, confirmed=False, topic=None) == {
        "raw": True,
        "loraDownlink": {"port": 1, "confirmed": False, "payloadHex": "0e14"},
    }
    assert build_downlink_body("MQTT", payload={"on": True}, payload_hex=None, port=1, confirmed=False, topic="dl") == {
        "mqttDownlink": {"topic": "dl", "contentType": "JSON", "payload": {"on": True}}
    }
    with pytest.raises(ServiceValidationError):
        build_downlink_body("LORA", payload=None, payload_hex=None, port=1, confirmed=False, topic=None)
    with pytest.raises(ServiceValidationError):
        build_downlink_body("MQTT", payload={"a": 1}, payload_hex=None, port=1, confirmed=False, topic=None)
    with pytest.raises(ServiceValidationError):
        build_downlink_body("HTTP", payload={"a": 1}, payload_hex=None, port=1, confirmed=False, topic=None)


async def test_send_downlink_service(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker, mock_config_entry: MockConfigEntry, mock_stream: None
) -> None:
    """The service posts to the downlink endpoint and maps errors."""
    await setup_integration(hass, mock_config_entry, aioclient_mock)
    aioclient_mock.post(f"{BASE}/v3/devices/{KITCHEN}/downlink", json={"id": "dl1"})
    device = dr.async_get(hass).async_get_device(identifiers={(DOMAIN, KITCHEN)})
    await hass.services.async_call(
        DOMAIN,
        "send_downlink",
        {"device_id": device.id, "payload_hex": "0e14", "port": 3},
        blocking=True,
    )
    call = aioclient_mock.mock_calls[-1]
    assert call[0] == "POST" and str(call[1]).endswith(f"/v3/devices/{KITCHEN}/downlink")
    assert call[2] == {"raw": True, "loraDownlink": {"port": 3, "confirmed": False, "payloadHex": "0e14"}}

    aioclient_mock.clear_requests()
    aioclient_mock.post(f"{BASE}/v3/devices/{KITCHEN}/downlink", status=403, json={"message": "no"})
    with pytest.raises(HomeAssistantError):
        await hass.services.async_call(
            DOMAIN, "send_downlink", {"device_id": device.id, "payload": {"x": 1}}, blocking=True
        )
    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            DOMAIN, "send_downlink", {"device_id": "does-not-exist", "payload": {"x": 1}}, blocking=True
        )


async def test_data_keys_only(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker, mock_config_entry: MockConfigEntry, mock_stream: None
) -> None:
    """With the option on, schema-only keys get no entity until they deliver data."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        title=mock_config_entry.title,
        unique_id=mock_config_entry.unique_id,
        data=dict(mock_config_entry.data),
        options={**mock_config_entry.options, CONF_DATA_KEYS_ONLY: True},
    )
    await setup_integration(hass, entry, aioclient_mock)
    assert hass.states.get("sensor.kitchen_temperature") is not None
    # ERS Eco schema declares `configuration` keys that never delivered data
    assert hass.states.get("binary_sensor.kitchen_nfc_disabled") is None
    coordinator = entry.runtime_data
    coordinator._handle_sample(Sample(KITCHEN, "default", datetime(2026, 8, 20, 16, 0, tzinfo=UTC), {"newKey": 1}))
    await hass.async_block_till_done()
    assert hass.states.get("sensor.kitchen_new_key") is not None
