"""Binary sensor platform for boolean akenza data points and connectivity."""

from __future__ import annotations

from typing import Any

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.const import STATE_ON, EntityCategory
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity

from .const import DEFAULT_TOPIC, DOMAIN
from .coordinator import AkenzaConfigEntry, AkenzaCoordinator
from .entity import AkenzaDeviceEntity, AkenzaHubEntity
from .mapping import binary_spec
from .models import DataPointDescriptor, ValueType
from .sensor import _display_name

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: AkenzaConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up binary sensors; new devices/data points are added dynamically."""
    coordinator = entry.runtime_data
    known: set[str] = set()

    @callback
    def _sync() -> None:
        new: list[BinarySensorEntity] = []
        for device_id, state in coordinator.data.items():
            for descriptor in state.descriptors.values():
                if descriptor.value_type is not ValueType.BOOLEAN:
                    continue
                if coordinator.default_topic_only and descriptor.topic != DEFAULT_TOPIC:
                    continue
                uid = f"{DOMAIN}_{device_id}_{descriptor.key_id}"
                if uid in known:
                    continue
                known.add(uid)
                new.append(AkenzaDataPointBinarySensor(coordinator, device_id, descriptor, uid))
            uid = f"{DOMAIN}_{device_id}_meta_online"
            if uid not in known:
                known.add(uid)
                new.append(AkenzaOnlineBinarySensor(coordinator, device_id, uid))
        hub_uid = f"{DOMAIN}_org_{coordinator.organization_id}_stream_connected"
        if hub_uid not in known:
            known.add(hub_uid)
            new.append(AkenzaStreamBinarySensor(coordinator, hub_uid))
        if new:
            async_add_entities(new)

    _sync()
    entry.async_on_unload(coordinator.async_add_listener(_sync))


class AkenzaDataPointBinarySensor(AkenzaDeviceEntity, BinarySensorEntity, RestoreEntity):
    """A boolean data key of a device topic."""

    def __init__(
        self,
        coordinator: AkenzaCoordinator,
        device_id: str,
        descriptor: DataPointDescriptor,
        unique_id: str,
    ) -> None:
        """Initialise from the descriptor."""
        super().__init__(coordinator, device_id)
        self._descriptor = descriptor
        self._attr_unique_id = unique_id
        spec = binary_spec(descriptor, enable_hidden_kpis=coordinator.enable_hidden_kpis)
        self._attr_name = _display_name(descriptor, coordinator.data[device_id])
        self._attr_device_class = spec.device_class
        self._attr_entity_category = spec.entity_category
        self._attr_entity_registry_enabled_default = spec.enabled_default
        if spec.icon:
            self._attr_icon = spec.icon
        self._restored: bool | None = None

    async def async_added_to_hass(self) -> None:
        """Restore the last state until live data arrives."""
        await super().async_added_to_hass()
        if (
            self._raw_value() is None
            and (last := await self.async_get_last_state())
            and last.state in (STATE_ON, "off")
        ):
            self._restored = last.state == STATE_ON

    def _raw_value(self) -> Any:
        state = self.state_data
        return state.values.get(self._descriptor.key_id) if state else None

    @property
    def is_on(self) -> bool | None:
        """Boolean value."""
        raw = self._raw_value()
        if raw is None:
            state = self.state_data
            if state is not None and not state.seeded:
                return self._restored
            return None
        if isinstance(raw, bool):
            return raw
        if isinstance(raw, int | float):
            return raw != 0
        if isinstance(raw, str):
            return raw.strip().lower() in ("true", "on", "1", "yes")
        return None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Expose topic and key details."""
        attrs: dict[str, Any] = {"topic": self._descriptor.topic, "data_key": self._descriptor.key}
        if self._descriptor.measurement_type:
            attrs["measurement_type"] = self._descriptor.measurement_type
        state = self.state_data
        if state and (ts := state.topic_timestamps.get(self._descriptor.topic)):
            attrs["last_sample"] = ts.isoformat()
        return attrs


class AkenzaOnlineBinarySensor(AkenzaDeviceEntity, BinarySensorEntity):
    """Online state as reported by akenza (based on the device's online timeout)."""

    _attr_translation_key = "online"
    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator: AkenzaCoordinator, device_id: str, unique_id: str) -> None:
        """Initialise."""
        super().__init__(coordinator, device_id)
        self._attr_unique_id = unique_id

    @property
    def is_on(self) -> bool | None:
        """True when akenza reports the device online; None when unknown."""
        state = self.state_data
        if state is None:
            return None
        if state.device.online is not None:
            return state.device.online
        online_state = (state.device.online_state or "").upper()
        if online_state == "ONLINE":
            return True
        if online_state == "OFFLINE":
            return False
        return None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Expose the raw akenza online state."""
        state = self.state_data
        return {"online_state": state.device.online_state} if state else {}


class AkenzaStreamBinarySensor(AkenzaHubEntity, BinarySensorEntity):
    """Whether the live WebSocket stream is connected."""

    _attr_translation_key = "stream_connected"
    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator: AkenzaCoordinator, unique_id: str) -> None:
        """Initialise."""
        super().__init__(coordinator)
        self._attr_unique_id = unique_id

    @property
    def is_on(self) -> bool:
        """Stream connection state."""
        return self.coordinator.stream_connected
