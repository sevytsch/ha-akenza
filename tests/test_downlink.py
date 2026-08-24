"""Tests for entities derived from downlink scripts (light / number / switch)."""

from datetime import UTC, datetime

import pytest
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from custom_components.akenza.models import Sample, extract_downlink_fields

from .conftest import BASE, WS_HOME, load_fixture, mock_api, paged

BUSYLIGHT = "02bb000000000001"
VICKI = "02cc000000000002"
BUSYLIGHT_TYPE = "33c7a431d6ff276f"
VICKI_TYPE = "33aa11bb22cc33dd"


def _device(device_id: str, name: str, type_id: str, type_name: str) -> dict:
    return {
        "id": device_id,
        "name": name,
        "type": "DEVICE",
        "workspaceId": WS_HOME,
        "organizationId": "1111111111111111",
        "connectivity": "LORA",
        "online": True,
        "onlineState": "ONLINE",
        "tags": [],
        "customFields": [],
        "dataFlow": {"deviceType": {"id": type_id, "name": type_name, "pictureUrl": None}},
        "uplinkMetrics": None,
    }


async def _setup(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker, entry: MockConfigEntry
) -> None:
    aioclient_mock.get(
        f"{BASE}/v3/device-types/{BUSYLIGHT_TYPE}", json=load_fixture("device_type_busylight.json")
    )
    aioclient_mock.get(
        f"{BASE}/v3/device-types/{VICKI_TYPE}", json=load_fixture("device_type_vicki.json")
    )
    assets = load_fixture("assets_list.json")
    content = [d for d in assets["content"] if d["name"] == "Kitchen"]
    content.append(_device(BUSYLIGHT, "Meeting light", BUSYLIGHT_TYPE, "Kuando Busylight"))
    content.append(_device(VICKI, "Bedroom valve", VICKI_TYPE, "Vicki"))
    for device_id in (BUSYLIGHT, VICKI):
        aioclient_mock.get(f"{BASE}/v3/devices/{device_id}/infer-schema", json={})
        aioclient_mock.get(f"{BASE}/v3/devices/{device_id}/query/topics", json=["default"])
        aioclient_mock.post(f"{BASE}/v3/devices/{device_id}/downlink", json={})
    aioclient_mock.get(f"{BASE}/v3/devices/{BUSYLIGHT}/query", json=[])
    aioclient_mock.get(
        f"{BASE}/v3/devices/{VICKI}/query",
        json=[
            {
                "timestamp": "2026-08-20T15:00:00.000Z",
                "deviceId": VICKI,
                "topic": "default",
                "data": {"targetTemperature": 21, "sensorTemperature": 22.5, "childLock": False},
            }
        ],
    )
    mock_api(aioclient_mock, assets=paged(content))
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done(wait_background_tasks=True)


def _downlink_bodies(aioclient_mock: AiohttpClientMocker, device_id: str) -> list[dict]:
    return [
        call[2]
        for call in aioclient_mock.mock_calls
        if call[0] == "POST" and str(call[1]).endswith(f"/v3/devices/{device_id}/downlink")
    ]


@pytest.mark.parametrize(
    ("code", "expected"),
    [
        (
            load_fixture("device_type_busylight.json")["downlinkScript"]["code"],
            {"red", "green", "blue", "onDuration", "offDuration"},
        ),
        (
            load_fixture("device_type_vicki.json")["downlinkScript"]["code"],
            {"setKeepAlive", "setChildLock", "setTargetTemperature"},
        ),
        (
            'if ("ledStatus" in payload) { x(payload.ledStatus); } if ("timeToSend" in payload) {}',
            {"ledStatus", "timeToSend"},
        ),
        (
            "function consume(event) { var payload = event.payload; emit('downlink', { payloadHex: payload, port: 1 }); }",
            set(),
        ),
        ("", set()),
        (None, set()),
    ],
)
def test_extract_downlink_fields(code, expected) -> None:
    """Payload fields are read from the encoder script."""
    assert set(extract_downlink_fields(code)) == expected


async def test_rgb_light_from_downlink_script(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    mock_config_entry: MockConfigEntry,
    mock_stream: None,
) -> None:
    """A script taking red/green/blue becomes an RGB light that sends downlinks."""
    await _setup(hass, aioclient_mock, mock_config_entry)
    assert hass.states.get("light.meeting_light_light").state == "off"
    assert hass.states.get("light.bedroom_valve_light") is None
    assert hass.states.get("light.kitchen_light") is None

    await hass.services.async_call(
        "light",
        "turn_on",
        {"entity_id": "light.meeting_light_light", "rgb_color": [0, 255, 0]},
        blocking=True,
    )
    state = hass.states.get("light.meeting_light_light")
    assert state.state == "on"
    assert state.attributes["rgb_color"] == (0, 255, 0)
    assert state.attributes["assumed_state"] is True
    assert _downlink_bodies(aioclient_mock, BUSYLIGHT)[-1] == {
        "loraDownlink": {
            "port": 1,
            "confirmed": True,
            "payload": {"red": 0, "green": 255, "blue": 0, "onDuration": 255, "offDuration": 0},
        }
    }

    # brightness scales the colour, an effect sets the blink pattern
    await hass.services.async_call(
        "light",
        "turn_on",
        {
            "entity_id": "light.meeting_light_light",
            "rgb_color": [255, 0, 0],
            "brightness": 128,
            "effect": "blink_slow",
        },
        blocking=True,
    )
    assert _downlink_bodies(aioclient_mock, BUSYLIGHT)[-1]["loraDownlink"]["payload"] == {
        "red": 128,
        "green": 0,
        "blue": 0,
        "onDuration": 10,
        "offDuration": 10,
    }
    assert hass.states.get("light.meeting_light_light").attributes["effect"] == "blink_slow"

    await hass.services.async_call(
        "light", "turn_off", {"entity_id": "light.meeting_light_light"}, blocking=True
    )
    assert hass.states.get("light.meeting_light_light").state == "off"
    assert _downlink_bodies(aioclient_mock, BUSYLIGHT)[-1]["loraDownlink"]["payload"] == {
        "red": 0,
        "green": 0,
        "blue": 0,
        "onDuration": 0,
        "offDuration": 0,
    }


async def test_number_and_switch_from_downlink_script(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    mock_config_entry: MockConfigEntry,
    mock_stream: None,
) -> None:
    """Known single-field commands become number / switch entities with device feedback."""
    await _setup(hass, aioclient_mock, mock_config_entry)
    number = hass.states.get("number.bedroom_valve_target_temperature")
    assert number.state == "21.0"
    assert number.attributes["unit_of_measurement"] == "°C"
    assert number.attributes["min"] == 5 and number.attributes["max"] == 30
    assert "assumed_state" not in number.attributes
    assert hass.states.get("switch.bedroom_valve_child_lock").state == "off"
    # the busylight script knows none of these commands
    assert hass.states.get("number.meeting_light_target_temperature") is None
    assert hass.states.get("switch.meeting_light_child_lock") is None

    await hass.services.async_call(
        "number",
        "set_value",
        {"entity_id": "number.bedroom_valve_target_temperature", "value": 23},
        blocking=True,
    )
    assert _downlink_bodies(aioclient_mock, VICKI)[-1] == {
        "loraDownlink": {"port": 1, "confirmed": True, "payload": {"setTargetTemperature": 23}}
    }
    number = hass.states.get("number.bedroom_valve_target_temperature")
    assert number.state == "23.0"
    assert number.attributes["assumed_state"] is True

    # an older report does not override the pending value, a newer one does
    coordinator = mock_config_entry.runtime_data
    coordinator._handle_sample(
        Sample(
            VICKI, "default", datetime(2026, 8, 20, 15, 30, tzinfo=UTC), {"targetTemperature": 21}
        )
    )
    await hass.async_block_till_done()
    assert hass.states.get("number.bedroom_valve_target_temperature").state == "23.0"
    coordinator._handle_sample(
        Sample(VICKI, "default", datetime.now(UTC), {"targetTemperature": 23, "childLock": True})
    )
    await hass.async_block_till_done()
    number = hass.states.get("number.bedroom_valve_target_temperature")
    assert number.state == "23.0"
    assert "assumed_state" not in number.attributes
    assert hass.states.get("switch.bedroom_valve_child_lock").state == "on"

    await hass.services.async_call(
        "switch", "turn_off", {"entity_id": "switch.bedroom_valve_child_lock"}, blocking=True
    )
    assert _downlink_bodies(aioclient_mock, VICKI)[-1]["loraDownlink"]["payload"] == {
        "setChildLock": False
    }
    assert hass.states.get("switch.bedroom_valve_child_lock").state == "off"


async def test_light_feedback_from_reported_color(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    mock_config_entry: MockConfigEntry,
    mock_stream: None,
) -> None:
    """The Busylight reports lastColorRGB/timeOn; the light adopts newer reports."""
    await _setup(hass, aioclient_mock, mock_config_entry)
    coordinator = mock_config_entry.runtime_data
    coordinator._handle_sample(
        Sample(
            BUSYLIGHT,
            "default",
            datetime(2026, 8, 24, 6, 37, tzinfo=UTC),
            {"lastColorRGB": "255,0,0", "timeOn": 255.0, "timeOff": 0.0},
        )
    )
    await hass.async_block_till_done()
    state = hass.states.get("light.meeting_light_light")
    assert state.state == "on"
    assert state.attributes["rgb_color"] == (255, 0, 0)
    assert "assumed_state" not in state.attributes

    # a command marks the state assumed until a newer report arrives
    await hass.services.async_call(
        "light",
        "turn_on",
        {"entity_id": "light.meeting_light_light", "rgb_color": [0, 0, 255]},
        blocking=True,
    )
    state = hass.states.get("light.meeting_light_light")
    assert state.attributes["rgb_color"] == (0, 0, 255)
    assert state.attributes["assumed_state"] is True
    coordinator._handle_sample(
        Sample(
            BUSYLIGHT,
            "default",
            datetime.now(UTC),
            {"lastColorRGB": "0,0,255", "timeOn": 255.0, "timeOff": 0.0},
        )
    )
    await hass.async_block_till_done()
    state = hass.states.get("light.meeting_light_light")
    assert state.attributes["rgb_color"] == (0, 0, 255)
    assert "assumed_state" not in state.attributes

    # the device reporting all zeros means off
    coordinator._handle_sample(
        Sample(
            BUSYLIGHT,
            "default",
            datetime.now(UTC),
            {"lastColorRGB": "0,0,0", "timeOn": 0.0, "timeOff": 0.0},
        )
    )
    await hass.async_block_till_done()
    assert hass.states.get("light.meeting_light_light").state == "off"
