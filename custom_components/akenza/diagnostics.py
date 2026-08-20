"""Diagnostics support for akenza."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.const import CONF_API_KEY
from homeassistant.core import HomeAssistant

from .const import CONF_ORGANIZATION_ID
from .coordinator import AkenzaConfigEntry

TO_REDACT = {CONF_API_KEY, CONF_ORGANIZATION_ID, "device_id", "organization_id", "serial_number"}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: AkenzaConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    coordinator = entry.runtime_data
    devices = []
    for state in (coordinator.data or {}).values():
        devices.append(
            {
                "device": asdict(state.device),
                "device_type": state.device_type.name if state.device_type else None,
                "descriptors": [d.to_dict() for d in state.descriptors.values()],
                "values": state.values,
                "topic_timestamps": {k: v.isoformat() for k, v in state.topic_timestamps.items()},
                "last_seen": state.last_seen.isoformat() if state.last_seen else None,
                "seeded": state.seeded,
            }
        )
    return async_redact_data(
        {
            "entry": {"data": dict(entry.data), "options": dict(entry.options)},
            "stream": {
                "connected": coordinator.stream_connected,
                "subscribed_assets": coordinator.stream.subscribed_count,
            },
            "seeding": {
                "done": coordinator.seeding_done,
                "seeded_devices": coordinator.seeded_devices,
            },
            "device_types_cached": len(coordinator.cache.device_types),
            "devices": devices,
        },
        TO_REDACT,
    )
