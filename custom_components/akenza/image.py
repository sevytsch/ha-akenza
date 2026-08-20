"""Image platform: product picture of the device type."""

from __future__ import annotations

from homeassistant.components.image import ImageEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.util import dt as dt_util

from .const import DOMAIN
from .coordinator import AkenzaConfigEntry, AkenzaCoordinator
from .entity import AkenzaDeviceEntity

PARALLEL_UPDATES = 0


def _picture_url(coordinator: AkenzaCoordinator, device_id: str) -> str | None:
    state = coordinator.data.get(device_id)
    if state is None or state.device_type is None:
        return None
    url = state.device_type.picture_url
    return url if url and url.startswith(("https://", "http://")) else None


async def async_setup_entry(
    hass: HomeAssistant,
    entry: AkenzaConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up one product image per device whose device type has a picture."""
    coordinator = entry.runtime_data
    if not coordinator.device_images:
        return
    known: set[str] = set()

    @callback
    def _sync() -> None:
        new: list[ImageEntity] = []
        for device_id in coordinator.data:
            uid = f"{DOMAIN}_{device_id}_meta_product_image"
            if uid in known or _picture_url(coordinator, device_id) is None:
                continue
            known.add(uid)
            new.append(AkenzaProductImage(hass, coordinator, device_id, uid))
        if new:
            async_add_entities(new)

    _sync()
    entry.async_on_unload(coordinator.async_add_listener(_sync))


class AkenzaProductImage(AkenzaDeviceEntity, ImageEntity):
    """Product picture from the akenza device-type library."""

    _attr_translation_key = "product_image"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(
        self, hass: HomeAssistant, coordinator: AkenzaCoordinator, device_id: str, unique_id: str
    ) -> None:
        """Initialise with the current picture URL."""
        AkenzaDeviceEntity.__init__(self, coordinator, device_id)
        ImageEntity.__init__(self, hass, verify_ssl=True)
        self._attr_unique_id = unique_id
        self._attr_image_url = _picture_url(coordinator, device_id)
        self._attr_image_last_updated = dt_util.utcnow()

    @callback
    def _handle_device_update(self) -> None:
        """Pick up a changed picture URL (device type changed)."""
        url = _picture_url(self.coordinator, self._device_id)
        if url and url != self._attr_image_url:
            self._attr_image_url = url
            self._cached_image = None
            self._attr_image_last_updated = dt_util.utcnow()
        super()._handle_device_update()
