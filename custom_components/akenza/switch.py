"""Switch entities for single-field boolean downlink commands (e.g. Vicki child lock)."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.util import dt as dt_util

from .const import DOMAIN
from .coordinator import AkenzaConfigEntry, AkenzaCoordinator
from .downlink import SWITCHES, DownlinkSwitch, async_send_payload, downlink_fields, feedback_value
from .entity import AkenzaDeviceEntity

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: AkenzaConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up switch entities for devices whose downlink script knows the command."""
    coordinator = entry.runtime_data
    known: set[str] = set()

    @callback
    def _sync() -> None:
        new: list[SwitchEntity] = []
        for device_id, state in coordinator.data.items():
            fields = downlink_fields(state)
            for description in SWITCHES:
                uid = f"{DOMAIN}_{device_id}_downlink_{description.field}"
                if uid in known or description.field not in fields:
                    continue
                known.add(uid)
                new.append(AkenzaDownlinkSwitch(coordinator, device_id, description, uid))
        if new:
            async_add_entities(new)

    _sync()
    entry.async_on_unload(coordinator.async_add_listener(_sync))


class AkenzaDownlinkSwitch(AkenzaDeviceEntity, SwitchEntity, RestoreEntity):
    """Toggle a setting via downlink; follows the device's reported value once it confirms."""

    def __init__(
        self,
        coordinator: AkenzaCoordinator,
        device_id: str,
        description: DownlinkSwitch,
        unique_id: str,
    ) -> None:
        """Initialise the switch."""
        super().__init__(coordinator, device_id)
        self._description = description
        self._attr_unique_id = unique_id
        self._attr_translation_key = description.translation_key
        self._pending: tuple[bool, datetime] | None = None
        self._restored: bool | None = None

    async def async_added_to_hass(self) -> None:
        """Restore the last state."""
        await super().async_added_to_hass()
        last = await self.async_get_last_state()
        if last is not None and last.state in ("on", "off"):
            self._restored = last.state == "on"

    @property
    def is_on(self) -> bool | None:
        """Pending value until the device reports a newer one, else the reported value."""
        state = self.state_data
        reported = feedback_value(state, self._description.feedback_keys) if state else None
        if self._pending is not None:
            value, sent_at = self._pending
            if reported is None or reported[1] is None or reported[1] <= sent_at:
                return value
            self._pending = None
        if reported is not None and isinstance(reported[0], bool | int | float):
            return bool(reported[0])
        return self._restored

    @property
    def assumed_state(self) -> bool:
        """Assumed until the device has reported the value back."""
        return self._pending is not None or not (
            self.state_data and feedback_value(self.state_data, self._description.feedback_keys)
        )

    async def _async_send(self, value: bool) -> None:
        await async_send_payload(
            self.coordinator, self._device_id, {self._description.field: value}
        )
        self._pending = (value, dt_util.utcnow())
        self._restored = value
        self.async_write_ha_state()

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Enable."""
        await self._async_send(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Disable."""
        await self._async_send(False)
