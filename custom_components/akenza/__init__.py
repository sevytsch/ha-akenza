"""The akenza integration."""

from __future__ import annotations

import voluptuous as vol
from homeassistant.const import ATTR_DEVICE_ID, CONF_API_KEY, Platform
from homeassistant.core import HomeAssistant, ServiceCall, callback
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.typing import ConfigType

from .api import AkenzaApiClient, AkenzaAuthError, AkenzaError, AkenzaForbiddenError
from .const import (
    ATTR_CONFIRMED,
    ATTR_PAYLOAD,
    ATTR_PAYLOAD_HEX,
    ATTR_PORT,
    ATTR_TOPIC,
    CONF_BASE_URL,
    DEFAULT_BASE_URL,
    DOMAIN,
    SERVICE_SEND_DOWNLINK,
)
from .coordinator import AkenzaConfigEntry, AkenzaCoordinator
from .downlink import build_downlink_body
from .entity import hub_device_info
from .storage import AkenzaCache

PLATFORMS: list[Platform] = [
    Platform.BINARY_SENSOR,
    Platform.BUTTON,
    Platform.DEVICE_TRACKER,
    Platform.EVENT,
    Platform.IMAGE,
    Platform.LIGHT,
    Platform.NUMBER,
    Platform.SENSOR,
    Platform.SWITCH,
]

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

SEND_DOWNLINK_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_DEVICE_ID): vol.All(cv.ensure_list, [cv.string]),
        vol.Optional(ATTR_PAYLOAD): dict,
        vol.Optional(ATTR_PAYLOAD_HEX): cv.string,
        vol.Optional(ATTR_PORT, default=1): vol.All(vol.Coerce(int), vol.Range(min=1, max=223)),
        vol.Optional(ATTR_CONFIRMED, default=False): cv.boolean,
        vol.Optional(ATTR_TOPIC): cv.string,
    }
)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Register integration-wide services."""
    hass.services.async_register(
        DOMAIN, SERVICE_SEND_DOWNLINK, _async_send_downlink, schema=SEND_DOWNLINK_SCHEMA
    )
    return True


@callback
def _find_device(hass: HomeAssistant, ha_device_id: str) -> tuple[AkenzaCoordinator, str]:
    """Resolve a Home Assistant device id to (coordinator, akenza device id)."""
    device = dr.async_get(hass).async_get(ha_device_id)
    if device is None:
        raise ServiceValidationError(translation_domain=DOMAIN, translation_key="device_not_found")
    akenza_ids = {ident for domain, ident in device.identifiers if domain == DOMAIN}
    for entry_id in device.config_entries:
        entry = hass.config_entries.async_get_entry(entry_id)
        if entry is None or entry.domain != DOMAIN or not hasattr(entry, "runtime_data"):
            continue
        coordinator: AkenzaCoordinator = entry.runtime_data
        for akenza_id in akenza_ids:
            if coordinator.data and akenza_id in coordinator.data:
                return coordinator, akenza_id
    raise ServiceValidationError(translation_domain=DOMAIN, translation_key="device_not_found")


async def _async_send_downlink(call: ServiceCall) -> None:
    """Handle akenza.send_downlink."""
    for ha_device_id in call.data[ATTR_DEVICE_ID]:
        coordinator, akenza_id = _find_device(call.hass, ha_device_id)
        device = coordinator.data[akenza_id].device
        body = build_downlink_body(
            device.connectivity,
            payload=call.data.get(ATTR_PAYLOAD),
            payload_hex=call.data.get(ATTR_PAYLOAD_HEX),
            port=call.data[ATTR_PORT],
            confirmed=call.data[ATTR_CONFIRMED],
            topic=call.data.get(ATTR_TOPIC),
        )
        try:
            await coordinator.client.async_send_downlink(akenza_id, body)
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
    device_registry = dr.async_get(hass)
    hub = device_registry.async_get_or_create(
        config_entry_id=entry.entry_id, **hub_device_info(coordinator)
    )
    coordinator.hub_device_id = hub.id
    # Versions < 0.2.2 stored the device-type id as model_id; the registry keeps
    # stale values unless they are cleared explicitly.
    for device in dr.async_entries_for_config_entry(device_registry, entry.entry_id):
        if device.model_id is not None:
            device_registry.async_update_device(device.id, model_id=None)
    coordinator.async_purge_excluded_entities()
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
