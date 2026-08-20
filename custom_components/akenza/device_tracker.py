"""Device tracker platform: GPS positions from latitude/longitude data keys."""

from __future__ import annotations

from homeassistant.components.device_tracker import SourceType, TrackerEntity
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import DOMAIN, GPS_ACCURACY_KEYS, LATITUDE_KEYS, LONGITUDE_KEYS
from .coordinator import AkenzaConfigEntry, AkenzaCoordinator
from .entity import AkenzaDeviceEntity
from .models import DeviceState

PARALLEL_UPDATES = 0


def _find_key(state: DeviceState, topic: str, candidates: tuple[str, ...]) -> str | None:
    keys = {d.key for d in state.descriptors.values() if d.topic == topic}
    lower = {k.lower(): k for k in keys}
    for candidate in candidates:
        if candidate.lower() in lower:
            return lower[candidate.lower()]
    return None


def gps_topics(state: DeviceState) -> list[tuple[str, str, str, str | None]]:
    """Return (topic, lat_key, lon_key, accuracy_key) for every topic with a position."""
    result = []
    for topic in sorted({d.topic for d in state.descriptors.values()}):
        lat = _find_key(state, topic, LATITUDE_KEYS)
        lon = _find_key(state, topic, LONGITUDE_KEYS)
        if lat and lon:
            result.append((topic, lat, lon, _find_key(state, topic, GPS_ACCURACY_KEYS)))
    return result


async def async_setup_entry(
    hass: HomeAssistant,
    entry: AkenzaConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up one tracker per device topic that carries a position."""
    coordinator = entry.runtime_data
    known: set[str] = set()

    @callback
    def _sync() -> None:
        new: list[TrackerEntity] = []
        for device_id, state in coordinator.data.items():
            for topic, lat, lon, acc in gps_topics(state):
                if coordinator.default_topic_only and topic != "default":
                    continue
                uid = f"{DOMAIN}_{device_id}_{topic}_position"
                if uid in known:
                    continue
                known.add(uid)
                new.append(AkenzaTracker(coordinator, device_id, topic, lat, lon, acc, uid))
        if new:
            async_add_entities(new)

    _sync()
    entry.async_on_unload(coordinator.async_add_listener(_sync))


class AkenzaTracker(AkenzaDeviceEntity, TrackerEntity):
    """GPS position of a device."""

    _attr_translation_key = "position"

    def __init__(
        self,
        coordinator: AkenzaCoordinator,
        device_id: str,
        topic: str,
        lat_key: str,
        lon_key: str,
        accuracy_key: str | None,
        unique_id: str,
    ) -> None:
        """Initialise."""
        super().__init__(coordinator, device_id)
        self._attr_unique_id = unique_id
        self._topic = topic
        self._lat = f"{topic}_{lat_key}"
        self._lon = f"{topic}_{lon_key}"
        self._acc = f"{topic}_{accuracy_key}" if accuracy_key else None
        if topic != "default":
            self._attr_translation_placeholders = {"topic": topic}
            self._attr_translation_key = "position_topic"

    def _coord(self, key_id: str) -> float | None:
        state = self.state_data
        value = state.values.get(key_id) if state else None
        if isinstance(value, bool) or not isinstance(value, int | float):
            return None
        return float(value)

    @property
    def source_type(self) -> SourceType:
        """GPS."""
        return SourceType.GPS

    @property
    def latitude(self) -> float | None:
        """Latitude."""
        lat = self._coord(self._lat)
        return lat if lat is not None and -90 <= lat <= 90 and lat != 0 else None

    @property
    def longitude(self) -> float | None:
        """Longitude."""
        lon = self._coord(self._lon)
        return lon if lon is not None and -180 <= lon <= 180 and lon != 0 else None

    @property
    def location_accuracy(self) -> float:
        """Accuracy in metres when a matching key exists."""
        if self._acc and (acc := self._coord(self._acc)) is not None and acc >= 0:
            return acc
        return 0

    @property
    def extra_state_attributes(self) -> dict[str, str]:
        """Topic and last sample."""
        attrs = {"topic": self._topic}
        state = self.state_data
        if state and (ts := state.topic_timestamps.get(self._topic)):
            attrs["last_sample"] = ts.isoformat()
        return attrs
