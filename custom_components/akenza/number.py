"""Number entities for single-field downlink commands (e.g. Vicki target temperature)."""

from __future__ import annotations

from datetime import datetime

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.util import dt as dt_util

from .const import DOMAIN
from .coordinator import AkenzaConfigEntry, AkenzaCoordinator
from .downlink import NUMBERS, DownlinkNumber, async_send_payload, downlink_fields, feedback_value
from .entity import AkenzaDeviceEntity

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: AkenzaConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up number entities for devices whose downlink script knows the command."""
    coordinator = entry.runtime_data
    known: set[str] = set()

    @callback
    def _sync() -> None:
        new: list[NumberEntity] = []
        for device_id, state in coordinator.data.items():
            fields = downlink_fields(state)
            for description in NUMBERS:
                uid = f"{DOMAIN}_{device_id}_downlink_{description.field}"
                if uid in known or description.field not in fields:
                    continue
                known.add(uid)
                new.append(AkenzaDownlinkNumber(coordinator, device_id, description, uid))
        if new:
            async_add_entities(new)

    _sync()
    entry.async_on_unload(coordinator.async_add_listener(_sync))


class AkenzaDownlinkNumber(AkenzaDeviceEntity, NumberEntity, RestoreEntity):
    """Set a value via downlink; shows the device's reported value once it confirms."""

    _attr_mode = NumberMode.BOX

    def __init__(
        self,
        coordinator: AkenzaCoordinator,
        device_id: str,
        description: DownlinkNumber,
        unique_id: str,
    ) -> None:
        """Initialise the number."""
        super().__init__(coordinator, device_id)
        self._description = description
        self._attr_unique_id = unique_id
        self._attr_translation_key = description.translation_key
        self._attr_native_min_value = description.native_min
        self._attr_native_max_value = description.native_max
        self._attr_native_step = description.native_step
        self._attr_native_unit_of_measurement = description.unit
        self._attr_device_class = description.device_class
        self._pending: tuple[float, datetime] | None = None
        self._restored: float | None = None

    async def async_added_to_hass(self) -> None:
        """Restore the last value."""
        await super().async_added_to_hass()
        last = await self.async_get_last_state()
        if last is not None and last.state not in ("unknown", "unavailable"):
            try:
                self._restored = float(last.state)
            except ValueError:
                self._restored = None

    @property
    def native_value(self) -> float | None:
        """Pending value until the device reports a newer one, else the reported value."""
        state = self.state_data
        reported = feedback_value(state, self._description.feedback_keys) if state else None
        if self._pending is not None:
            value, sent_at = self._pending
            if reported is None or reported[1] is None or reported[1] <= sent_at:
                return value
            self._pending = None
        if reported is not None and isinstance(reported[0], int | float):
            return float(reported[0])
        return self._restored

    @property
    def assumed_state(self) -> bool:
        """Assumed until the device has reported the value back."""
        return self._pending is not None or not (
            self.state_data and feedback_value(self.state_data, self._description.feedback_keys)
        )

    async def async_set_native_value(self, value: float) -> None:
        """Send the value as a downlink."""
        payload_value: float | int = int(value) if float(value).is_integer() else value
        await async_send_payload(
            self.coordinator, self._device_id, {self._description.field: payload_value}
        )
        self._pending = (float(value), dt_util.utcnow())
        self._restored = float(value)
        self.async_write_ha_state()
