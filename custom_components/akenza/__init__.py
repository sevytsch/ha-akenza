"""The akenza integration."""

from __future__ import annotations

from homeassistant.const import CONF_API_KEY, Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import AkenzaApiClient
from .const import CONF_BASE_URL, DEFAULT_BASE_URL, DOMAIN
from .coordinator import AkenzaConfigEntry, AkenzaCoordinator
from .entity import hub_device_info
from .storage import AkenzaCache

PLATFORMS: list[Platform] = [Platform.BINARY_SENSOR, Platform.IMAGE, Platform.SENSOR]


async def async_setup_entry(hass: HomeAssistant, entry: AkenzaConfigEntry) -> bool:
    """Set up akenza from a config entry."""
    client = AkenzaApiClient(
        async_get_clientsession(hass),
        entry.data[CONF_API_KEY],
        entry.data.get(CONF_BASE_URL, DEFAULT_BASE_URL),
    )
    coordinator = AkenzaCoordinator(hass, entry, client)
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator

    # Create the hub device first so the per-device `via_device` reference resolves.
    dr.async_get(hass).async_get_or_create(
        config_entry_id=entry.entry_id, **hub_device_info(coordinator)
    )
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    coordinator.async_start()
    return True


async def async_unload_entry(hass: HomeAssistant, entry: AkenzaConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        await entry.runtime_data.async_shutdown()
    return unload_ok


async def async_remove_entry(hass: HomeAssistant, entry: AkenzaConfigEntry) -> None:
    """Delete the cache when the entry is removed."""
    await AkenzaCache(hass, entry.entry_id).async_remove()


async def async_remove_config_entry_device(
    hass: HomeAssistant, entry: AkenzaConfigEntry, device_entry: dr.DeviceEntry
) -> bool:
    """Allow removing devices that are no longer part of the organization."""
    coordinator = entry.runtime_data
    for domain, identifier in device_entry.identifiers:
        if domain != DOMAIN:
            continue
        if identifier == f"org_{coordinator.organization_id}":
            return False
        if coordinator.data and identifier in coordinator.data:
            return False
    return True
