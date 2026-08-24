"""Light entities driven by a device type's downlink script (RGB, e.g. Kuando Busylight)."""

from __future__ import annotations

from typing import Any

from homeassistant.components.light import (
    ATTR_BRIGHTNESS,
    ATTR_EFFECT,
    ATTR_RGB_COLOR,
    ColorMode,
    LightEntity,
    LightEntityFeature,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.util import dt as dt_util

from .const import DOMAIN
from .coordinator import AkenzaConfigEntry, AkenzaCoordinator
from .downlink import (
    LIGHT_COLOR_KEYS,
    LIGHT_EFFECTS,
    LIGHT_ON_TIME_KEYS,
    OFF_DURATION_FIELD,
    ON_DURATION_FIELD,
    async_send_payload,
    downlink_fields,
    feedback_value,
    has_rgb_light,
    parse_reported_color,
)
from .entity import AkenzaDeviceEntity

PARALLEL_UPDATES = 0
DEFAULT_RGB = (255, 0, 0)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: AkenzaConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up one RGB light per device whose downlink script takes red/green/blue."""
    coordinator = entry.runtime_data
    known: set[str] = set()

    @callback
    def _sync() -> None:
        new: list[LightEntity] = []
        for device_id, state in coordinator.data.items():
            uid = f"{DOMAIN}_{device_id}_downlink_light"
            if uid in known or not has_rgb_light(state):
                continue
            known.add(uid)
            new.append(AkenzaDownlinkLight(coordinator, device_id, uid))
        if new:
            async_add_entities(new)

    _sync()
    entry.async_on_unload(coordinator.async_add_listener(_sync))


class AkenzaDownlinkLight(AkenzaDeviceEntity, LightEntity, RestoreEntity):
    """RGB light; devices that report their colour back (lastColorRGB) update the state."""

    _attr_translation_key = "downlink_light"
    _attr_color_mode = ColorMode.RGB
    _attr_supported_color_modes = {ColorMode.RGB}

    def __init__(self, coordinator: AkenzaCoordinator, device_id: str, unique_id: str) -> None:
        """Initialise the light."""
        super().__init__(coordinator, device_id)
        self._attr_unique_id = unique_id
        self._attr_is_on = False
        self._attr_rgb_color = DEFAULT_RGB
        self._attr_brightness = 255
        self._sent_at = None
        fields = downlink_fields(coordinator.data[device_id])
        self._has_durations = ON_DURATION_FIELD in fields and OFF_DURATION_FIELD in fields
        if self._has_durations:
            self._attr_supported_features = LightEntityFeature.EFFECT
            self._attr_effect_list = list(LIGHT_EFFECTS)
            self._attr_effect = "solid"

    async def async_added_to_hass(self) -> None:
        """Restore the last assumed state."""
        await super().async_added_to_hass()
        last = await self.async_get_last_state()
        if last is None:
            self._apply_feedback()
            return
        self._attr_is_on = last.state == "on"
        rgb = last.attributes.get(ATTR_RGB_COLOR)
        if isinstance(rgb, list | tuple) and len(rgb) == 3:
            self._attr_rgb_color = (int(rgb[0]), int(rgb[1]), int(rgb[2]))
        brightness = last.attributes.get(ATTR_BRIGHTNESS)
        if isinstance(brightness, int | float):
            self._attr_brightness = int(brightness)
        effect = last.attributes.get(ATTR_EFFECT)
        if self._has_durations and effect in LIGHT_EFFECTS:
            self._attr_effect = effect
        self._apply_feedback()

    def _reported(self) -> tuple[tuple[int, int, int], bool, Any] | None:
        """Colour and on/off the device reported back: (rgb, is_on, sample timestamp)."""
        state = self.state_data
        if state is None:
            return None
        colour = feedback_value(state, LIGHT_COLOR_KEYS)
        if colour is None:
            return None
        rgb = parse_reported_color(colour[0])
        if rgb is None:
            return None
        on = any(rgb)
        on_time = feedback_value(state, LIGHT_ON_TIME_KEYS)
        if on_time is not None and isinstance(on_time[0], int | float):
            on = on and on_time[0] > 0
        return rgb, on, colour[1]

    def _apply_feedback(self) -> None:
        """Adopt the reported state once it is newer than the last command."""
        reported = self._reported()
        if reported is None:
            return
        rgb, on, timestamp = reported
        if self._sent_at is not None and (timestamp is None or timestamp <= self._sent_at):
            return
        self._sent_at = None
        self._attr_is_on = on
        if on:
            self._attr_rgb_color = rgb
            self._attr_brightness = 255

    @property
    def assumed_state(self) -> bool:
        """Assumed until the device has reported its colour back."""
        return self._sent_at is not None or self._reported() is None

    @callback
    def _handle_device_update(self) -> None:
        self._apply_feedback()
        super()._handle_device_update()

    def _payload(self, *, on: bool) -> dict[str, Any]:
        red, green, blue = self._attr_rgb_color or DEFAULT_RGB
        scale = (self._attr_brightness or 255) / 255 if on else 0
        payload: dict[str, Any] = {
            "red": round(red * scale),
            "green": round(green * scale),
            "blue": round(blue * scale),
        }
        if self._has_durations:
            on_duration, off_duration = LIGHT_EFFECTS.get(self._attr_effect or "solid", (255, 0))
            payload[ON_DURATION_FIELD] = on_duration if on else 0
            payload[OFF_DURATION_FIELD] = off_duration if on else 0
        return payload

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Send the colour (and blink pattern) as a downlink."""
        if ATTR_RGB_COLOR in kwargs:
            self._attr_rgb_color = tuple(kwargs[ATTR_RGB_COLOR])  # type: ignore[assignment]
        if ATTR_BRIGHTNESS in kwargs:
            self._attr_brightness = int(kwargs[ATTR_BRIGHTNESS])
        if ATTR_EFFECT in kwargs and kwargs[ATTR_EFFECT] in LIGHT_EFFECTS:
            self._attr_effect = kwargs[ATTR_EFFECT]
        await async_send_payload(self.coordinator, self._device_id, self._payload(on=True))
        self._attr_is_on = True
        self._sent_at = dt_util.utcnow()
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Send all-zero colours."""
        await async_send_payload(self.coordinator, self._device_id, self._payload(on=False))
        self._attr_is_on = False
        self._sent_at = dt_util.utcnow()
        self.async_write_ha_state()
