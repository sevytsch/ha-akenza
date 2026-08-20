"""Tests for schema parsing."""

from custom_components.akenza.models import DataPointDescriptor, ValueType
from custom_components.akenza.schema import (
    descriptors_from_schema,
    descriptors_from_schemas,
    flatten_sample_data,
    infer_descriptor,
    merge_descriptors,
)

from .conftest import load_fixture


def test_device_type_schema_parsing() -> None:
    """Schemas arrive as JSON strings and are parsed into descriptors."""
    from custom_components.akenza.models import AkenzaDeviceType

    device_type = AkenzaDeviceType.from_api(load_fixture("device_type_ers_eco.json"))
    assert device_type.manufacturer == "Elsys"
    assert set(device_type.schemas) == {"default", "lifecycle", "configuration"}
    descriptors = descriptors_from_schemas(device_type.schemas)
    temp = descriptors["default_temperature"]
    assert temp.value_type is ValueType.NUMBER
    assert temp.unit == "°C"
    assert temp.measurement_type == "akenza/environment/temperature/celsius"
    assert descriptors["lifecycle_batteryLevel"].maximum == 100
    assert descriptors["configuration_nfcDisable"].hide_from_kpis is True
    assert descriptors["configuration_nfcDisable"].value_type is ValueType.BOOLEAN


def test_nested_and_unsupported() -> None:
    """Nested objects are flattened one level; arrays are ignored."""
    schema = {
        "properties": {
            "pos": {"type": "object", "properties": {"lat": {"type": "number"}, "deep": {"type": "object"}}},
            "list": {"type": "array"},
            "state": {"type": ["string", "null"], "enum": ["a", "b"]},
        }
    }
    result = {d.key: d for d in descriptors_from_schema("t", schema)}
    assert set(result) == {"pos.lat", "state"}
    assert result["state"].enum == ("a", "b")


def test_flatten_and_infer() -> None:
    """Live data keys are flattened and inferred."""
    flat = flatten_sample_data({"a": 1, "b": {"c": True, "d": {"e": 1}}, "l": [1], "n": None})
    assert flat == {"a": 1, "b.c": True, "n": None}
    assert infer_descriptor("t", "a", 1.5).value_type is ValueType.NUMBER
    assert infer_descriptor("t", "a", 1).value_type is ValueType.INTEGER
    assert infer_descriptor("t", "a", True).value_type is ValueType.BOOLEAN
    assert infer_descriptor("t", "a", "x").value_type is ValueType.STRING
    assert infer_descriptor("t", "a", None) is None
    assert infer_descriptor("t", "a", [1]) is None


def test_merge_precedence() -> None:
    """First source wins, gaps are filled from later sources."""
    primary = {"t_k": DataPointDescriptor("t", "k", ValueType.NUMBER, title=None, unit="°C")}
    secondary = {
        "t_k": DataPointDescriptor("t", "k", ValueType.INTEGER, title="Temp", unit="K", inferred=True),
        "t_o": DataPointDescriptor("t", "o", ValueType.STRING, inferred=True),
    }
    merged = merge_descriptors(primary, secondary)
    assert merged["t_k"].unit == "°C"
    assert merged["t_k"].title == "Temp"
    assert merged["t_k"].value_type is ValueType.NUMBER
    assert merged["t_k"].inferred is False
    assert merged["t_o"].inferred is True
