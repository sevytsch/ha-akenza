"""Tests for the measurementType -> Home Assistant mapping."""

import pytest
from homeassistant.components.binary_sensor import BinarySensorDeviceClass
from homeassistant.components.sensor import SensorDeviceClass, SensorStateClass
from homeassistant.const import EntityCategory

from custom_components.akenza.mapping import binary_spec, sensor_spec
from custom_components.akenza.models import DataPointDescriptor, ValueType


@pytest.mark.parametrize(
    ("descriptor", "device_class", "unit", "state_class"),
    [
        (
            DataPointDescriptor("default", "temperature", ValueType.NUMBER, unit="°C", measurement_type="akenza/environment/temperature/celsius"),
            SensorDeviceClass.TEMPERATURE, "°C", SensorStateClass.MEASUREMENT,
        ),
        (
            DataPointDescriptor("default", "humidity", ValueType.NUMBER, unit="%", measurement_type="akenza/environment/humidity/percent"),
            SensorDeviceClass.HUMIDITY, "%", SensorStateClass.MEASUREMENT,
        ),
        (
            DataPointDescriptor("default", "co2", ValueType.NUMBER, unit="ppm"),
            SensorDeviceClass.CO2, "ppm", SensorStateClass.MEASUREMENT,
        ),
        (
            DataPointDescriptor("default", "pm2_5", ValueType.NUMBER, unit="μg/m3", measurement_type="akenza/environment/pm2_5/mcgm3"),
            SensorDeviceClass.PM25, "μg/m³", SensorStateClass.MEASUREMENT,
        ),
        (
            DataPointDescriptor("default", "sound", ValueType.NUMBER, unit="dB(A)", measurement_type="akenza/environment/soundLevel/dba"),
            SensorDeviceClass.SOUND_PRESSURE, "dBA", SensorStateClass.MEASUREMENT,
        ),
        (
            DataPointDescriptor("default", "energy", ValueType.NUMBER, unit="kWh", measurement_type="akenza/electricity/activeEnergy/kWh"),
            SensorDeviceClass.ENERGY, "kWh", SensorStateClass.TOTAL_INCREASING,
        ),
        (
            DataPointDescriptor("default", "peopleIn", ValueType.INTEGER, unit="people", measurement_type="akenza/spaces/peopleIn/people"),
            None, "people", SensorStateClass.TOTAL_INCREASING,
        ),
        (
            DataPointDescriptor("default", "pressure", ValueType.NUMBER, unit="hPa", measurement_type="akenza/environment/pressure/hPa"),
            SensorDeviceClass.ATMOSPHERIC_PRESSURE, "hPa", SensorStateClass.MEASUREMENT,
        ),
        (
            DataPointDescriptor("default", "temperature", ValueType.NUMBER, unit="bogus"),
            None, "bogus", SensorStateClass.MEASUREMENT,
        ),
        (
            DataPointDescriptor("cat", "atHome", ValueType.INTEGER, inferred=True),
            None, None, SensorStateClass.MEASUREMENT,
        ),
        (
            DataPointDescriptor("default", "roomTemperature", ValueType.NUMBER, inferred=True),
            SensorDeviceClass.TEMPERATURE, "°C", SensorStateClass.MEASUREMENT,
        ),
    ],
)
def test_sensor_spec(descriptor, device_class, unit, state_class) -> None:
    """Numeric mapping table."""
    spec = sensor_spec(descriptor, enable_hidden_kpis=False)
    assert spec.device_class == device_class
    assert spec.unit == unit
    assert spec.state_class == state_class


def test_diagnostic_and_disabled() -> None:
    """Lifecycle keys are diagnostic; raw_payload is disabled by default."""
    battery = DataPointDescriptor("lifecycle", "batteryLevel", ValueType.NUMBER, unit="%", measurement_type="akenza/device/batteryLevel/percent")
    spec = sensor_spec(battery, enable_hidden_kpis=False)
    assert spec.device_class is SensorDeviceClass.BATTERY
    assert spec.entity_category is EntityCategory.DIAGNOSTIC
    assert spec.enabled_default is True
    raw = DataPointDescriptor("raw_payload", "rssi", ValueType.NUMBER, inferred=True)
    spec = sensor_spec(raw, enable_hidden_kpis=False)
    assert spec.enabled_default is False
    hidden = DataPointDescriptor("default", "x", ValueType.NUMBER, hide_from_kpis=True)
    assert sensor_spec(hidden, enable_hidden_kpis=False).enabled_default is False
    assert sensor_spec(hidden, enable_hidden_kpis=True).enabled_default is True


def test_string_specs() -> None:
    """Enum and timestamp strings."""
    enum = DataPointDescriptor("default", "status", ValueType.STRING, enum=("ok", "nok"))
    spec = sensor_spec(enum, enable_hidden_kpis=False)
    assert spec.device_class is SensorDeviceClass.ENUM
    assert spec.options == ("ok", "nok")
    ts = DataPointDescriptor("default", "lastTimestamp", ValueType.STRING)
    assert sensor_spec(ts, enable_hidden_kpis=False).device_class is SensorDeviceClass.TIMESTAMP


@pytest.mark.parametrize(
    ("descriptor", "device_class"),
    [
        (DataPointDescriptor("default", "occupied", ValueType.BOOLEAN, measurement_type="akenza/spaces/occupied/boolean"), BinarySensorDeviceClass.OCCUPANCY),
        (DataPointDescriptor("default", "openWindow", ValueType.BOOLEAN), BinarySensorDeviceClass.WINDOW),
        (DataPointDescriptor("lifecycle", "brokenSensor", ValueType.BOOLEAN), BinarySensorDeviceClass.PROBLEM),
        (DataPointDescriptor("default", "childLock", ValueType.BOOLEAN), BinarySensorDeviceClass.LOCK),
        (DataPointDescriptor("default", "foo", ValueType.BOOLEAN), None),
    ],
)
def test_binary_spec(descriptor, device_class) -> None:
    """Boolean mapping."""
    assert binary_spec(descriptor, enable_hidden_kpis=False).device_class == device_class
