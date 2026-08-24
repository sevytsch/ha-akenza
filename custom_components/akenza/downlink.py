"""Downlink helpers: request bodies and the entity patterns derived from downlink scripts."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from homeassistant.components.number import NumberDeviceClass
from homeassistant.const import UnitOfTemperature
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError

from .api import AkenzaAuthError, AkenzaError, AkenzaForbiddenError
from .const import DOMAIN

if TYPE_CHECKING:
    from .coordinator import AkenzaCoordinator
    from .models import DeviceState

# a script that consumes red/green/blue is an RGB light (e.g. Plenom Kuando Busylight)
RGB_FIELDS = frozenset({"red", "green", "blue"})
ON_DURATION_FIELD = "onDuration"
OFF_DURATION_FIELD = "offDuration"
# (onDuration, offDuration) in 0.1 s steps; 255/0 = steady
LIGHT_EFFECTS: dict[str, tuple[int, int]] = {
    "solid": (255, 0),
    "blink_slow": (10, 10),
    "blink_fast": (3, 3),
}
# uplink data keys some RGB lights (Kuando Busylight) report their state back with
LIGHT_COLOR_KEYS = ("lastColorRGB", "lastColorRgb", "lastColor")
LIGHT_ON_TIME_KEYS = ("timeOn",)


def parse_reported_color(value: Any) -> tuple[int, int, int] | None:
    """Parse a reported colour like ``"255,0,0"`` into an RGB tuple."""
    if not isinstance(value, str):
        return None
    parts = value.replace(";", ",").split(",")
    if len(parts) != 3:
        return None
    try:
        rgb = tuple(int(float(p.strip())) for p in parts)
    except ValueError:
        return None
    if all(0 <= c <= 255 for c in rgb):
        return rgb  # type: ignore[return-value]
    return None


@dataclass(frozen=True, slots=True)
class DownlinkNumber:
    """A single-field numeric downlink command exposed as a number entity."""

    field: str
    translation_key: str
    native_min: float
    native_max: float
    native_step: float
    unit: str | None
    device_class: NumberDeviceClass | None
    # uplink data keys that report the current value back
    feedback_keys: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class DownlinkSwitch:
    """A single-field boolean downlink command exposed as a switch entity."""

    field: str
    translation_key: str
    feedback_keys: tuple[str, ...]


# Known single-field commands (the script must reference the field for the entity to appear)
NUMBERS: tuple[DownlinkNumber, ...] = (
    DownlinkNumber(
        field="setTargetTemperature",  # MClimate Vicki
        translation_key="target_temperature",
        native_min=5,
        native_max=30,
        native_step=1,
        unit=UnitOfTemperature.CELSIUS,
        device_class=NumberDeviceClass.TEMPERATURE,
        feedback_keys=("targetTemperature",),
    ),
)
SWITCHES: tuple[DownlinkSwitch, ...] = (
    DownlinkSwitch(
        field="setChildLock",  # MClimate Vicki
        translation_key="child_lock",
        feedback_keys=("childLock",),
    ),
)


def downlink_fields(state: DeviceState) -> frozenset[str]:
    """Downlink payload fields a device understands (LoRa devices with an encoder only)."""
    if state.device_type is None or (state.device.connectivity or "").upper() != "LORA":
        return frozenset()
    return state.device_type.downlink_fields


def has_rgb_light(state: DeviceState) -> bool:
    """Whether the device's downlink script drives an RGB light."""
    return downlink_fields(state) >= RGB_FIELDS


def feedback_value(state: DeviceState, keys: tuple[str, ...]) -> tuple[Any, Any] | None:
    """Latest reported value for one of the keys: (value, sample timestamp)."""
    for descriptor in state.descriptors.values():
        if descriptor.key in keys and descriptor.key_id in state.values:
            return state.values[descriptor.key_id], state.topic_timestamps.get(descriptor.topic)
    return None


def build_downlink_body(
    connectivity: str | None,
    *,
    payload: dict[str, Any] | None,
    payload_hex: str | None,
    port: int,
    confirmed: bool,
    topic: str | None,
) -> dict[str, Any]:
    """Build the akenza downlink request body for a device's connectivity."""
    if payload is None and payload_hex is None:
        raise ServiceValidationError(translation_domain=DOMAIN, translation_key="payload_required")
    kind = (connectivity or "").upper()
    if kind == "LORA":
        downlink: dict[str, Any] = {"port": port, "confirmed": confirmed}
        if payload_hex is not None:
            downlink["payloadHex"] = payload_hex
            return {"raw": True, "loraDownlink": downlink}
        downlink["payload"] = payload
        return {"loraDownlink": downlink}
    if kind == "MQTT":
        if not topic:
            raise ServiceValidationError(
                translation_domain=DOMAIN, translation_key="topic_required"
            )
        mqtt: dict[str, Any] = {"topic": topic, "contentType": "JSON"}
        if payload_hex is not None:
            mqtt["payload"] = {"payloadHex": payload_hex}
            return {"raw": True, "mqttDownlink": mqtt}
        mqtt["payload"] = payload
        return {"mqttDownlink": mqtt}
    raise ServiceValidationError(
        translation_domain=DOMAIN,
        translation_key="downlink_unsupported",
        translation_placeholders={"connectivity": connectivity or "unknown"},
    )


async def async_send_payload(
    coordinator: AkenzaCoordinator, device_id: str, payload: dict[str, Any]
) -> None:
    """Queue a JSON downlink (encoded by the device type's script) for a device."""
    state = coordinator.data[device_id]
    body = build_downlink_body(
        state.device.connectivity,
        payload=payload,
        payload_hex=None,
        port=1,
        confirmed=True,
        topic=None,
    )
    try:
        await coordinator.client.async_send_downlink(device_id, body)
    except (AkenzaAuthError, AkenzaForbiddenError) as err:
        raise HomeAssistantError(
            translation_domain=DOMAIN, translation_key="downlink_forbidden"
        ) from err
    except AkenzaError as err:
        raise HomeAssistantError(
            translation_domain=DOMAIN,
            translation_key="downlink_failed",
            translation_placeholders={"error": str(err)},
        ) from err
