"""Schema parsing: akenza JSON schemas and live samples -> DataPointDescriptors."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any

from .models import DataPointDescriptor, ValueType

_LOGGER = logging.getLogger(__name__)

_TYPE_MAP = {
    "number": ValueType.NUMBER,
    "integer": ValueType.INTEGER,
    "boolean": ValueType.BOOLEAN,
    "string": ValueType.STRING,
}


def _schema_type(prop: Mapping[str, Any]) -> str | None:
    """Return the JSON-schema type, tolerating ["number","null"] style unions."""
    raw = prop.get("type")
    if isinstance(raw, list):
        for item in raw:
            if item != "null":
                return str(item)
        return None
    return str(raw) if raw else None


def _num(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    return float(value)


def descriptors_from_schema(
    topic: str, schema: Mapping[str, Any], *, inferred: bool = False
) -> list[DataPointDescriptor]:
    """Build descriptors from one topic schema (object with `properties`)."""
    result: list[DataPointDescriptor] = []
    properties = schema.get("properties")
    if not isinstance(properties, Mapping):
        return result
    for key, prop in properties.items():
        if not isinstance(prop, Mapping):
            continue
        kind = _schema_type(prop)
        nested = prop.get("properties")
        if kind == "object" or (kind is None and isinstance(nested, Mapping) and nested):
            # one level of nesting: parent.child
            if isinstance(nested, Mapping):
                for child_key, child in nested.items():
                    if not isinstance(child, Mapping):
                        continue
                    child_kind = _schema_type(child)
                    if child_kind in _TYPE_MAP:
                        result.append(
                            _descriptor(
                                topic, f"{key}.{child_key}", child, _TYPE_MAP[child_kind], inferred
                            )
                        )
            continue
        if kind in _TYPE_MAP:
            result.append(_descriptor(topic, str(key), prop, _TYPE_MAP[kind], inferred))
        else:
            _LOGGER.debug("Ignoring data key %s/%s with schema type %s", topic, key, kind)
    return result


def _descriptor(
    topic: str, key: str, prop: Mapping[str, Any], value_type: ValueType, inferred: bool
) -> DataPointDescriptor:
    enum_raw = prop.get("enum")
    enum = (
        tuple(str(e) for e in enum_raw if e is not None)
        if isinstance(enum_raw, list) and enum_raw
        else None
    )
    return DataPointDescriptor(
        topic=topic,
        key=key,
        value_type=value_type,
        title=str(prop["title"]) if prop.get("title") else None,
        unit=str(prop["unit"]) if prop.get("unit") else None,
        measurement_type=str(prop["measurementType"]) if prop.get("measurementType") else None,
        description=str(prop["description"]) if prop.get("description") else None,
        minimum=_num(prop.get("minimum")),
        maximum=_num(prop.get("maximum")),
        enum=enum,
        hide_from_kpis=bool(prop.get("hideFromKpis", False)),
        inferred=inferred or bool(prop.get("inferred", False)),
    )


def descriptors_from_schemas(
    schemas: Mapping[str, Mapping[str, Any]], *, inferred: bool = False
) -> dict[str, DataPointDescriptor]:
    """Build descriptors keyed by key_id from a {topic: schema} mapping."""
    result: dict[str, DataPointDescriptor] = {}
    for topic, schema in schemas.items():
        for descriptor in descriptors_from_schema(str(topic), schema, inferred=inferred):
            result[descriptor.key_id] = descriptor
    return result


def flatten_sample_data(data: Mapping[str, Any]) -> dict[str, Any]:
    """Flatten one level of nested objects: {"a": {"b": 1}} -> {"a.b": 1}.

    Lists and deeper objects are dropped.
    """
    flat: dict[str, Any] = {}
    for key, value in data.items():
        if isinstance(value, Mapping):
            for child_key, child in value.items():
                if not isinstance(child, Mapping | list):
                    flat[f"{key}.{child_key}"] = child
        elif not isinstance(value, list):
            flat[str(key)] = value
    return flat


def infer_descriptor(topic: str, key: str, value: Any) -> DataPointDescriptor | None:
    """Infer a descriptor from a live value (None for null/unsupported values)."""
    if value is None:
        return None
    if isinstance(value, bool):
        value_type = ValueType.BOOLEAN
    elif isinstance(value, int):
        value_type = ValueType.INTEGER
    elif isinstance(value, float):
        value_type = ValueType.NUMBER
    elif isinstance(value, str):
        value_type = ValueType.STRING
    else:
        return None
    return DataPointDescriptor(topic=topic, key=key, value_type=value_type, inferred=True)


def merge_descriptors(
    *sources: Mapping[str, DataPointDescriptor],
) -> dict[str, DataPointDescriptor]:
    """Merge descriptor maps; the first source wins on conflicts, later ones fill gaps."""
    merged: dict[str, DataPointDescriptor] = {}
    for source in sources:
        for key_id, descriptor in source.items():
            if key_id in merged:
                merged[key_id] = _fill_gaps(merged[key_id], descriptor)
            else:
                merged[key_id] = descriptor
    return merged


def _fill_gaps(primary: DataPointDescriptor, secondary: DataPointDescriptor) -> DataPointDescriptor:
    """Return primary, with None fields filled from secondary."""
    if primary.topic != secondary.topic or primary.key != secondary.key:
        return primary
    return DataPointDescriptor(
        topic=primary.topic,
        key=primary.key,
        value_type=primary.value_type,
        title=primary.title or secondary.title,
        unit=primary.unit or secondary.unit,
        measurement_type=primary.measurement_type or secondary.measurement_type,
        description=primary.description or secondary.description,
        minimum=primary.minimum if primary.minimum is not None else secondary.minimum,
        maximum=primary.maximum if primary.maximum is not None else secondary.maximum,
        enum=primary.enum or secondary.enum,
        hide_from_kpis=primary.hide_from_kpis or secondary.hide_from_kpis,
        inferred=primary.inferred and secondary.inferred,
    )
