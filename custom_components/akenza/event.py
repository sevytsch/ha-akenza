"""Event platform: button presses and similar one-shot data keys."""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any

from homeassistant.components.event import EventDeviceClass, EventEntity
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import DIAGNOSTIC_TOPIC_PREFIXES, DISABLED_TOPICS, DOMAIN, EVENT_TYPE_PRESSED
from .coordinator import AkenzaConfigEntry, AkenzaCoordinator
from .entity import AkenzaDeviceEntity
from .mapping import split_measurement_type
from .models import DataPointDescriptor, ValueType
from .sensor import _display_name

PARALLEL_UPDATES = 0

_BUTTON_KEY = re.compile(r"^(button|btn|key)\d*$|^buttonevent$|^(short|long|double)press(ed)?$|^press(type|ed)?$", re.I)


def is_button_event(descriptor: DataPointDescriptor) -> bool:
    """Whether a data key describes a button press."""
    if descriptor.topic in DISABLED_TOPICS or descriptor.topic.startswith(DIAGNOSTIC_TOPIC_PREFIXES):
        return False
    _, mtype, _ = split_measurement_type(descriptor.measurement_type)
    if mtype in ("buttonEvent", "buttonStatus"):
        return True
    return bool(_BUTTON_KEY.match(descriptor.key.rsplit(".", 1)[-1]))


async def async_setup_entry(
    hass: HomeAssistant,
    entry: AkenzaConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up event entities for button-like data keys."""
    coordinator = entry.runtime_data
    known: set[str] = set()

    @callback
    def _sync() -> None:
        new: list[EventEntity] = []
        for device_id, state in coordinator.data.items():
            for descriptor in state.descriptors.values():
                if not is_button_event(descriptor) or not coordinator.entity_wanted(state, descriptor):
                    continue
                uid = f"{DOMAIN}_{device_id}_{descriptor.key_id}_event"
                if uid in known:
                    continue
                known.add(uid)
                new.append(AkenzaButtonEvent(coordinator, device_id, descriptor, uid))
        if new:
            async_add_entities(new)

    _sync()
    entry.async_on_unload(coordinator.async_add_listener(_sync))


class AkenzaButtonEvent(AkenzaDeviceEntity, EventEntity):
    """Fires `pressed` whenever a new sample reports the button as pressed."""

    _attr_device_class = EventDeviceClass.BUTTON
    _attr_event_types = [EVENT_TYPE_PRESSED]

    def __init__(
        self,
        coordinator: AkenzaCoordinator,
        device_id: str,
        descriptor: DataPointDescriptor,
        unique_id: str,
    ) -> None:
        """Initialise."""
        super().__init__(coordinator, device_id)
        self._descriptor = descriptor
        self._attr_unique_id = unique_id
        self._attr_name = _display_name(descriptor, coordinator.data[device_id])
        self._handled: datetime | None = None

    async def async_added_to_hass(self) -> None:
        """Ignore samples that arrived before the entity existed."""
        await super().async_added_to_hass()
        state = self.state_data
        if state:
            self._handled = state.topic_timestamps.get(self._descriptor.topic)

    @callback
    def _handle_device_update(self) -> None:
        state = self.state_data
        if state is None:
            return
        ts = state.topic_timestamps.get(self._descriptor.topic)
        if ts is None or (self._handled is not None and ts <= self._handled):
            return
        self._handled = ts
        if self._descriptor.key not in state.last_sample_keys.get(self._descriptor.topic, frozenset()):
            return
        value = state.values.get(self._descriptor.key_id)
        if not _is_pressed(value, self._descriptor):
            return
        attrs: dict[str, Any] = {"topic": self._descriptor.topic, "data_key": self._descriptor.key}
        if not isinstance(value, bool):
            attrs["value"] = value
        self._trigger_event(EVENT_TYPE_PRESSED, attrs)
        self.async_write_ha_state()


def _is_pressed(value: Any, descriptor: DataPointDescriptor) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, int | float):
        return value > 0
    if isinstance(value, str):
        return value.strip().lower() not in ("", "0", "false", "none", "released", "idle")
    return descriptor.value_type is ValueType.STRING and value is not None
