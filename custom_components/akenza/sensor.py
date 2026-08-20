"""Sensor platform for akenza data points and device diagnostics."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from homeassistant.components.sensor import (
    RestoreSensor,
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import (
    PERCENTAGE,
    SIGNAL_STRENGTH_DECIBELS,
    SIGNAL_STRENGTH_DECIBELS_MILLIWATT,
    EntityCategory,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.typing import StateType
from homeassistant.util import dt as dt_util

from .const import DEFAULT_TOPIC, DOMAIN
from .coordinator import AkenzaConfigEntry, AkenzaCoordinator
from .entity import AkenzaDeviceEntity, AkenzaHubEntity
from .mapping import sensor_spec
from .models import DataPointDescriptor, DeviceState, ValueType

PARALLEL_UPDATES = 0


@dataclass(frozen=True, kw_only=True)
class AkenzaMetaSensorDescription(SensorEntityDescription):
    """Describes a diagnostic sensor derived from device metadata."""

    value_fn: Callable[[DeviceState], StateType | datetime]
    exists_fn: Callable[[DeviceState], bool] = lambda _: True


def _uplink(state: DeviceState) -> Any:
    return state.device.uplink_metrics


META_SENSORS: tuple[AkenzaMetaSensorDescription, ...] = (
    AkenzaMetaSensorDescription(
        key="last_seen",
        translation_key="last_seen",
        device_class=SensorDeviceClass.TIMESTAMP,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda s: s.last_seen,
    ),
    AkenzaMetaSensorDescription(
        key="rssi",
        translation_key="rssi",
        device_class=SensorDeviceClass.SIGNAL_STRENGTH,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=SIGNAL_STRENGTH_DECIBELS_MILLIWATT,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda s: _uplink(s).rssi,
        exists_fn=lambda s: _uplink(s) is not None and _uplink(s).rssi is not None,
    ),
    AkenzaMetaSensorDescription(
        key="snr",
        translation_key="snr",
        device_class=SensorDeviceClass.SIGNAL_STRENGTH,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=SIGNAL_STRENGTH_DECIBELS,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda s: _uplink(s).snr,
        exists_fn=lambda s: _uplink(s) is not None and _uplink(s).snr is not None,
    ),
    AkenzaMetaSensorDescription(
        key="spreading_factor",
        translation_key="spreading_factor",
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda s: _uplink(s).sf,
        exists_fn=lambda s: _uplink(s) is not None and _uplink(s).sf is not None,
    ),
    AkenzaMetaSensorDescription(
        key="gateways",
        translation_key="gateways",
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda s: _uplink(s).number_of_gateways,
        exists_fn=lambda s: _uplink(s) is not None and _uplink(s).number_of_gateways is not None,
    ),
    AkenzaMetaSensorDescription(
        key="uplink_battery",
        translation_key="uplink_battery",
        device_class=SensorDeviceClass.BATTERY,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=PERCENTAGE,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda s: _uplink(s).battery_level,
        exists_fn=lambda s: _uplink(s) is not None and _uplink(s).battery_level is not None,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: AkenzaConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up sensors; new devices/data points are added dynamically."""
    coordinator = entry.runtime_data
    known: set[str] = set()

    @callback
    def _sync() -> None:
        new: list[SensorEntity] = []
        for device_id, state in coordinator.data.items():
            if device_id not in known:
                known.add(device_id)
                # placeholder so meta-sensor ids below are per device
            for descriptor in state.descriptors.values():
                if descriptor.value_type is ValueType.BOOLEAN:
                    continue
                if coordinator.default_topic_only and descriptor.topic != DEFAULT_TOPIC:
                    continue
                uid = f"{DOMAIN}_{device_id}_{descriptor.key_id}"
                if uid in known:
                    continue
                known.add(uid)
                new.append(AkenzaDataPointSensor(coordinator, device_id, descriptor, uid))
            for description in META_SENSORS:
                uid = f"{DOMAIN}_{device_id}_meta_{description.key}"
                if uid in known or not description.exists_fn(state):
                    continue
                known.add(uid)
                new.append(AkenzaMetaSensor(coordinator, device_id, description, uid))
        hub_uid = f"{DOMAIN}_org_{coordinator.organization_id}_device_count"
        if hub_uid not in known:
            known.add(hub_uid)
            new.append(AkenzaDeviceCountSensor(coordinator, hub_uid))
        if new:
            async_add_entities(new)

    _sync()
    entry.async_on_unload(coordinator.async_add_listener(_sync))


def _display_name(descriptor: DataPointDescriptor, state: DeviceState) -> str:
    title = descriptor.title or _prettify(descriptor.key)
    if descriptor.topic != DEFAULT_TOPIC and any(
        d.key == descriptor.key and d.topic != descriptor.topic for d in state.descriptors.values()
    ):
        return f"{title} ({descriptor.topic})"
    return title


def _prettify(key: str) -> str:
    out = []
    for index, char in enumerate(key.replace("_", " ").replace(".", " ")):
        if char.isupper() and index and key[index - 1].islower():
            out.append(" ")
        out.append(char)
    text = "".join(out)
    return text[:1].upper() + text[1:]


class AkenzaDataPointSensor(AkenzaDeviceEntity, RestoreSensor):
    """A numeric or string data key of a device topic."""

    def __init__(
        self,
        coordinator: AkenzaCoordinator,
        device_id: str,
        descriptor: DataPointDescriptor,
        unique_id: str,
    ) -> None:
        """Initialise from the descriptor and the mapping tables."""
        super().__init__(coordinator, device_id)
        self._descriptor = descriptor
        self._attr_unique_id = unique_id
        spec = sensor_spec(descriptor, enable_hidden_kpis=coordinator.enable_hidden_kpis)
        self._attr_name = _display_name(descriptor, coordinator.data[device_id])
        self._attr_device_class = spec.device_class
        self._attr_state_class = spec.state_class
        self._attr_native_unit_of_measurement = spec.unit
        self._attr_entity_category = spec.entity_category
        self._attr_entity_registry_enabled_default = spec.enabled_default
        self._attr_suggested_display_precision = spec.precision
        if spec.options:
            self._attr_options = list(spec.options)
        self._restored: StateType | datetime | None = None

    async def async_added_to_hass(self) -> None:
        """Restore the last value until live data arrives."""
        await super().async_added_to_hass()
        if self._raw_value() is None and (last := await self.async_get_last_sensor_data()):
            self._restored = last.native_value

    def _raw_value(self) -> Any:
        state = self.state_data
        if state is None:
            return None
        return state.values.get(self._descriptor.key_id)

    @property
    def native_value(self) -> StateType | datetime:
        """Current value, coerced to the descriptor type."""
        raw = self._raw_value()
        if raw is None:
            state = self.state_data
            if state is not None and not state.seeded and self._restored is not None:
                return self._restored
            return None
        if self.device_class is SensorDeviceClass.TIMESTAMP:
            return dt_util.parse_datetime(str(raw)) if not isinstance(raw, datetime) else raw
        if self.device_class is SensorDeviceClass.ENUM:
            text = str(raw)
            return text if self._attr_options and text in self._attr_options else None
        if self._descriptor.value_type is ValueType.STRING:
            return str(raw)
        if isinstance(raw, bool):
            return int(raw)
        if isinstance(raw, int | float):
            return raw
        try:
            return float(raw)
        except TypeError, ValueError:
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


class AkenzaMetaSensor(AkenzaDeviceEntity, SensorEntity):
    """Diagnostic sensor derived from device metadata (uplink metrics)."""

    entity_description: AkenzaMetaSensorDescription

    def __init__(
        self,
        coordinator: AkenzaCoordinator,
        device_id: str,
        description: AkenzaMetaSensorDescription,
        unique_id: str,
    ) -> None:
        """Initialise."""
        super().__init__(coordinator, device_id)
        self.entity_description = description
        self._attr_unique_id = unique_id

    @property
    def native_value(self) -> StateType | datetime:
        """Value from the description's value function."""
        state = self.state_data
        if state is None:
            return None
        try:
            return self.entity_description.value_fn(state)
        except AttributeError:
            return None


class AkenzaDeviceCountSensor(AkenzaHubEntity, SensorEntity):
    """Number of devices tracked for this organization."""

    _attr_translation_key = "device_count"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator: AkenzaCoordinator, unique_id: str) -> None:
        """Initialise."""
        super().__init__(coordinator)
        self._attr_unique_id = unique_id

    @property
    def native_value(self) -> int:
        """Device count."""
        return len(self.coordinator.data or {})

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Seeding progress."""
        return {
            "seeded_devices": self.coordinator.seeded_devices,
            "seeding_done": self.coordinator.seeding_done,
            "subscribed_assets": self.coordinator.stream.subscribed_count,
        }
