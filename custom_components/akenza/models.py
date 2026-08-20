"""Data models for the akenza integration (no Home Assistant imports)."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any

_LOGGER = logging.getLogger(__name__)


def parse_timestamp(value: Any) -> datetime | None:
    """Parse an ISO-8601 timestamp as returned by akenza."""
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


class ValueType(StrEnum):
    """JSON-schema value types we create entities for."""

    NUMBER = "number"
    INTEGER = "integer"
    BOOLEAN = "boolean"
    STRING = "string"


@dataclass(frozen=True, slots=True)
class DataPointDescriptor:
    """Describes one data key on one topic of a device."""

    topic: str
    key: str
    value_type: ValueType
    title: str | None = None
    unit: str | None = None
    measurement_type: str | None = None
    description: str | None = None
    minimum: float | None = None
    maximum: float | None = None
    enum: tuple[str, ...] | None = None
    hide_from_kpis: bool = False
    inferred: bool = False

    @property
    def key_id(self) -> str:
        """Stable identifier of this data point within a device."""
        return f"{self.topic}_{self.key}"

    def to_dict(self) -> dict[str, Any]:
        """Serialize for the storage cache."""
        return {
            "topic": self.topic,
            "key": self.key,
            "value_type": self.value_type.value,
            "title": self.title,
            "unit": self.unit,
            "measurement_type": self.measurement_type,
            "description": self.description,
            "minimum": self.minimum,
            "maximum": self.maximum,
            "enum": list(self.enum) if self.enum else None,
            "hide_from_kpis": self.hide_from_kpis,
            "inferred": self.inferred,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> DataPointDescriptor:
        """Deserialize from the storage cache."""
        return cls(
            topic=data["topic"],
            key=data["key"],
            value_type=ValueType(data["value_type"]),
            title=data.get("title"),
            unit=data.get("unit"),
            measurement_type=data.get("measurement_type"),
            description=data.get("description"),
            minimum=data.get("minimum"),
            maximum=data.get("maximum"),
            enum=tuple(data["enum"]) if data.get("enum") else None,
            hide_from_kpis=bool(data.get("hide_from_kpis", False)),
            inferred=bool(data.get("inferred", False)),
        )


@dataclass(frozen=True, slots=True)
class UplinkMetrics:
    """Metadata about the last uplink of a device."""

    timestamp: datetime | None = None
    rssi: float | None = None
    snr: float | None = None
    sf: int | None = None
    sqi: int | None = None
    battery_level: float | None = None
    number_of_gateways: int | None = None

    @classmethod
    def from_api(cls, data: dict[str, Any] | None) -> UplinkMetrics | None:
        """Create from an API object."""
        if not data:
            return None
        return cls(
            timestamp=parse_timestamp(data.get("timestamp")),
            rssi=_num(data.get("rssi")),
            snr=_num(data.get("snr")),
            sf=_int(data.get("sf")),
            sqi=_int(data.get("sqi")),
            battery_level=_num(data.get("batteryLevel")),
            number_of_gateways=_int(data.get("numberOfGateways")),
        )


@dataclass(frozen=True, slots=True)
class AkenzaDeviceType:
    """A device type with its per-topic JSON schemas."""

    id: str
    name: str
    manufacturer: str | None = None
    firmware_version: str | None = None
    picture_url: str | None = None
    url: str | None = None
    schemas: dict[str, dict[str, Any]] = field(default_factory=dict)

    @classmethod
    def from_api(cls, data: dict[str, Any]) -> AkenzaDeviceType:
        """Create from the /v3/device-types/{id} response."""
        meta = data.get("meta") or {}
        schemas: dict[str, dict[str, Any]] = {}
        for topic, raw in (data.get("schemas") or {}).items():
            parsed: Any = raw
            if isinstance(raw, str):
                try:
                    parsed = json.loads(raw)
                except ValueError:
                    _LOGGER.debug(
                        "Invalid schema JSON for device type %s topic %s", data.get("id"), topic
                    )
                    continue
            if isinstance(parsed, dict):
                schemas[str(topic)] = parsed
        return cls(
            id=str(data["id"]),
            name=str(data.get("name") or data["id"]),
            manufacturer=meta.get("manufacturer") or None,
            firmware_version=meta.get("firmwareVersion") or None,
            picture_url=data.get("pictureUrl") or None,
            url=meta.get("url") or None,
            schemas=schemas,
        )

    def to_dict(self) -> dict[str, Any]:
        """Serialize for the storage cache."""
        return {
            "id": self.id,
            "name": self.name,
            "manufacturer": self.manufacturer,
            "firmware_version": self.firmware_version,
            "picture_url": self.picture_url,
            "url": self.url,
            "schemas": self.schemas,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AkenzaDeviceType:
        """Deserialize from the storage cache."""
        return cls(
            id=data["id"],
            name=data["name"],
            manufacturer=data.get("manufacturer"),
            firmware_version=data.get("firmware_version"),
            picture_url=data.get("picture_url"),
            url=data.get("url"),
            schemas=dict(data.get("schemas") or {}),
        )


@dataclass(frozen=True, slots=True)
class AkenzaDevice:
    """An akenza device (asset of type DEVICE)."""

    id: str
    name: str
    workspace_id: str
    organization_id: str
    device_id: str | None = None
    description: str | None = None
    connectivity: str | None = None
    online: bool | None = None
    online_state: str | None = None
    tag_ids: frozenset[str] = frozenset()
    tag_names: tuple[str, ...] = ()
    device_type_id: str | None = None
    device_type_name: str | None = None
    uplink_metrics: UplinkMetrics | None = None
    custom_fields: dict[str, str | float] = field(default_factory=dict)

    @classmethod
    def from_api(cls, data: dict[str, Any]) -> AkenzaDevice:
        """Create from an asset-list / device object. loraProperties are never read."""
        data_flow = data.get("dataFlow") or {}
        device_type = data_flow.get("deviceType") or {}
        tags = [t for t in (data.get("tags") or []) if isinstance(t, dict)]
        custom_fields: dict[str, str | float] = {}
        for entry in data.get("customFields") or []:
            if not isinstance(entry, dict):
                continue
            meta = entry.get("meta") or {}
            name = entry.get("fieldMetaName") or meta.get("name")
            if not name:
                continue
            value: Any = None
            for key in ("STRING", "NUMBER", "DATE"):
                if entry.get(key) not in (None, ""):
                    value = entry[key]
                    break
            if isinstance(value, str):
                custom_fields[str(name)] = value
            elif isinstance(value, int | float) and not isinstance(value, bool):
                custom_fields[str(name)] = float(value)
        return cls(
            id=str(data["id"]),
            name=str(data.get("name") or data["id"]),
            workspace_id=str(data.get("workspaceId") or ""),
            organization_id=str(data.get("organizationId") or ""),
            device_id=data.get("deviceId") or None,
            description=data.get("description") or None,
            connectivity=data.get("connectivity") or None,
            online=data.get("online") if isinstance(data.get("online"), bool) else None,
            online_state=data.get("onlineState") or None,
            tag_ids=frozenset(str(t["id"]) for t in tags if "id" in t),
            tag_names=tuple(str(t.get("name")) for t in tags if t.get("name")),
            device_type_id=str(device_type["id"]) if device_type.get("id") else None,
            device_type_name=device_type.get("name") or None,
            uplink_metrics=UplinkMetrics.from_api(data.get("uplinkMetrics")),
            custom_fields=custom_fields,
        )


@dataclass(frozen=True, slots=True)
class Sample:
    """One data sample of a device on a topic."""

    device_id: str
    topic: str
    timestamp: datetime
    data: dict[str, Any]

    @classmethod
    def from_api(cls, data: dict[str, Any], device_id: str | None = None) -> Sample | None:
        """Create from a REST query sample or a WebSocket sample object."""
        payload = data.get("data")
        if not isinstance(payload, dict):
            return None
        timestamp = parse_timestamp(data.get("timestamp"))
        if timestamp is None:
            return None
        dev = data.get("deviceId") or device_id
        if not dev:
            return None
        return cls(
            device_id=str(dev),
            topic=str(data.get("topic") or "default"),
            timestamp=timestamp,
            data=payload,
        )


@dataclass(slots=True)
class DeviceState:
    """Mutable runtime state of a device held by the coordinator."""

    device: AkenzaDevice
    device_type: AkenzaDeviceType | None = None
    descriptors: dict[str, DataPointDescriptor] = field(default_factory=dict)
    values: dict[str, Any] = field(default_factory=dict)
    topic_timestamps: dict[str, datetime] = field(default_factory=dict)
    last_sample_keys: dict[str, frozenset[str]] = field(default_factory=dict)
    last_seen: datetime | None = None
    seeded: bool = False


@dataclass(frozen=True, slots=True)
class Organization:
    """Minimal organization info."""

    id: str
    name: str


@dataclass(frozen=True, slots=True)
class Workspace:
    """Minimal workspace info."""

    id: str
    name: str


@dataclass(frozen=True, slots=True)
class Tag:
    """Minimal tag info."""

    id: str
    name: str
    workspace_id: str


@dataclass(frozen=True, slots=True)
class WorkspaceAccess:
    """Result of /v3/workspace-access."""

    all: bool
    ids: frozenset[str]


def _num(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int | float):
        return float(value)
    return None


def _int(value: Any) -> int | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return None
