"""Persistent cache of device types and descriptors for fast restarts."""

from __future__ import annotations

from typing import Any, TypedDict

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store

from .const import DOMAIN, STORAGE_VERSION
from .models import AkenzaDeviceType, DataPointDescriptor


class _StoredData(TypedDict, total=False):
    device_types: dict[str, dict[str, Any]]
    descriptors: dict[str, list[dict[str, Any]]]


class AkenzaCache:
    """Wrapper around a Store holding device types and per-device descriptors."""

    def __init__(self, hass: HomeAssistant, entry_id: str) -> None:
        """Initialise the cache for a config entry."""
        self._store: Store[_StoredData] = Store(hass, STORAGE_VERSION, f"{DOMAIN}.{entry_id}")
        self.device_types: dict[str, AkenzaDeviceType] = {}
        self.descriptors: dict[str, dict[str, DataPointDescriptor]] = {}

    async def async_load(self) -> None:
        """Load the cache from disk."""
        data = await self._store.async_load() or {}
        for type_id, raw in (data.get("device_types") or {}).items():
            try:
                self.device_types[type_id] = AkenzaDeviceType.from_dict(raw)
            except KeyError, TypeError, ValueError:
                continue
        for device_id, raw_list in (data.get("descriptors") or {}).items():
            parsed: dict[str, DataPointDescriptor] = {}
            for raw in raw_list:
                try:
                    descriptor = DataPointDescriptor.from_dict(raw)
                except KeyError, TypeError, ValueError:
                    continue
                parsed[descriptor.key_id] = descriptor
            self.descriptors[device_id] = parsed

    def async_schedule_save(self) -> None:
        """Schedule a delayed save."""
        self._store.async_delay_save(self._data_to_save, 10)

    def _data_to_save(self) -> _StoredData:
        return {
            "device_types": {k: v.to_dict() for k, v in self.device_types.items()},
            "descriptors": {
                device_id: [d.to_dict() for d in descriptors.values()]
                for device_id, descriptors in self.descriptors.items()
            },
        }

    async def async_remove(self) -> None:
        """Delete the cache file."""
        await self._store.async_remove()
