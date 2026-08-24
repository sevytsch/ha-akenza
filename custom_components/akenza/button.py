"""Button entities for akenza."""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import DOMAIN
from .coordinator import AkenzaConfigEntry, AkenzaCoordinator
from .entity import AkenzaHubEntity

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: AkenzaConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the hub buttons."""
    coordinator = entry.runtime_data
    async_add_entities(
        [AkenzaScanButton(coordinator, f"{DOMAIN}_org_{coordinator.organization_id}_scan_devices")]
    )


class AkenzaScanButton(AkenzaHubEntity, ButtonEntity):
    """Refresh the device list now instead of waiting for the next metadata poll."""

    _attr_translation_key = "scan_devices"
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, coordinator: AkenzaCoordinator, unique_id: str) -> None:
        """Initialise the button."""
        super().__init__(coordinator)
        self._attr_unique_id = unique_id

    async def async_press(self) -> None:
        """Run a metadata refresh (new devices are seeded immediately)."""
        await self.coordinator.async_refresh()
