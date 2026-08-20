"""Base entities and device-info helpers."""

from __future__ import annotations

from homeassistant.core import callback
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, PORTAL_DEVICE_URL_TEMPLATE, PORTAL_ORG_URL_TEMPLATE
from .coordinator import HUB_KEY, AkenzaCoordinator
from .models import DeviceState


def hub_identifier(coordinator: AkenzaCoordinator) -> tuple[str, str]:
    """Registry identifier of the per-entry hub device."""
    return (DOMAIN, f"org_{coordinator.organization_id}")


def hub_device_info(coordinator: AkenzaCoordinator) -> DeviceInfo:
    """DeviceInfo for the per-organization hub device."""
    return DeviceInfo(
        identifiers={hub_identifier(coordinator)},
        name=coordinator.organization_name,
        manufacturer="akenza",
        model="Organization",
        entry_type=DeviceEntryType.SERVICE,
        configuration_url=PORTAL_ORG_URL_TEMPLATE.format(
            organization_id=coordinator.organization_id
        ),
    )


def build_device_info(state: DeviceState, coordinator: AkenzaCoordinator) -> DeviceInfo:
    """DeviceInfo for an akenza device."""
    device = state.device
    device_type = state.device_type
    model = (
        device_type.name
        if device_type
        else device.device_type_name or f"{device.connectivity or 'Generic'} device"
    )
    return DeviceInfo(
        identifiers={(DOMAIN, device.id)},
        name=device.name,
        manufacturer=(device_type.manufacturer if device_type else None) or "akenza",
        model=model,
        model_id=device.device_type_id,
        sw_version=device_type.firmware_version if device_type else None,
        serial_number=device.device_id,
        configuration_url=PORTAL_DEVICE_URL_TEMPLATE.format(
            organization_id=device.organization_id or coordinator.organization_id,
            workspace_id=device.workspace_id,
            device_id=device.id,
        ),
        via_device=hub_identifier(coordinator),
    )


class AkenzaBaseEntity(CoordinatorEntity[AkenzaCoordinator]):
    """Entity that re-renders on coordinator refreshes and targeted device pushes."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: AkenzaCoordinator, listen_key: str) -> None:
        """Initialise with the key used for targeted notifications."""
        super().__init__(coordinator)
        self._listen_key = listen_key

    async def async_added_to_hass(self) -> None:
        """Subscribe to targeted device updates."""
        await super().async_added_to_hass()
        self.async_on_remove(
            self.coordinator.async_add_device_listener(self._listen_key, self._handle_device_update)
        )

    @callback
    def _handle_device_update(self) -> None:
        self.async_write_ha_state()


class AkenzaHubEntity(AkenzaBaseEntity):
    """Entity attached to the per-organization hub device."""

    def __init__(self, coordinator: AkenzaCoordinator) -> None:
        """Initialise a hub entity."""
        super().__init__(coordinator, HUB_KEY)
        self._attr_device_info = hub_device_info(coordinator)


class AkenzaDeviceEntity(AkenzaBaseEntity):
    """Entity attached to one akenza device."""

    def __init__(self, coordinator: AkenzaCoordinator, device_id: str) -> None:
        """Initialise a device entity."""
        super().__init__(coordinator, device_id)
        self._device_id = device_id
        self._attr_device_info = build_device_info(coordinator.data[device_id], coordinator)

    @property
    def state_data(self) -> DeviceState | None:
        """Current device state."""
        return self.coordinator.data.get(self._device_id) if self.coordinator.data else None

    @property
    def available(self) -> bool:
        """Available while the device is still part of the organization.

        A failed metadata poll must not mark live-streamed entities unavailable,
        so this deliberately does not depend on ``coordinator.last_update_success``.
        """
        return self.state_data is not None
