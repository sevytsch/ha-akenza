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
            DataPointDescriptor(
                "default",
                "temperature",
                ValueType.NUMBER,
                unit="°C",
                measurement_type="akenza/environment/temperature/celsius",
            ),
            SensorDeviceClass.TEMPERATURE,
            "°C",
            SensorStateClass.MEASUREMENT,
        ),
        (
            DataPointDescriptor(
                "default",
                "humidity",
                ValueType.NUMBER,
                unit="%",
                measurement_type="akenza/environment/humidity/percent",
            ),
            SensorDeviceClass.HUMIDITY,
            "%",
            SensorStateClass.MEASUREMENT,
        ),
        (
            DataPointDescriptor("default", "co2", ValueType.NUMBER, unit="ppm"),
            SensorDeviceClass.CO2,
            "ppm",
            SensorStateClass.MEASUREMENT,
        ),
        (
            DataPointDescriptor(
                "default",
                "pm2_5",
                ValueType.NUMBER,
                unit="μg/m3",
                measurement_type="akenza/environment/pm2_5/mcgm3",
            ),
            SensorDeviceClass.PM25,
            "μg/m³",
            SensorStateClass.MEASUREMENT,
        ),
        (
            DataPointDescriptor(
                "default",
                "sound",
                ValueType.NUMBER,
                unit="dB(A)",
                measurement_type="akenza/environment/soundLevel/dba",
            ),
            SensorDeviceClass.SOUND_PRESSURE,
            "dBA",
            SensorStateClass.MEASUREMENT,
        ),
        (
            DataPointDescriptor(
                "default",
                "energy",
                ValueType.NUMBER,
                unit="kWh",
                measurement_type="akenza/electricity/activeEnergy/kWh",
            ),
            SensorDeviceClass.ENERGY,
            "kWh",
            SensorStateClass.TOTAL_INCREASING,
        ),
        (
            DataPointDescriptor(
                "default",
                "peopleIn",
                ValueType.INTEGER,
                unit="people",
                measurement_type="akenza/spaces/peopleIn/people",
            ),
            None,
            "people",
            SensorStateClass.TOTAL_INCREASING,
        ),
        (
            DataPointDescriptor(
                "default",
                "pressure",
                ValueType.NUMBER,
                unit="hPa",
                measurement_type="akenza/environment/pressure/hPa",
            ),
            SensorDeviceClass.ATMOSPHERIC_PRESSURE,
            "hPa",
            SensorStateClass.MEASUREMENT,
        ),
        (
            DataPointDescriptor("default", "temperature", ValueType.NUMBER, unit="bogus"),
            None,
            "bogus",
            SensorStateClass.MEASUREMENT,
        ),
        (
            DataPointDescriptor("cat", "atHome", ValueType.INTEGER, inferred=True),
            None,
            None,
            SensorStateClass.MEASUREMENT,
        ),
        (
            DataPointDescriptor("default", "roomTemperature", ValueType.NUMBER, inferred=True),
            SensorDeviceClass.TEMPERATURE,
            "°C",
            SensorStateClass.MEASUREMENT,
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
    battery = DataPointDescriptor(
        "lifecycle",
        "batteryLevel",
        ValueType.NUMBER,
        unit="%",
        measurement_type="akenza/device/batteryLevel/percent",
    )
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
        (
            DataPointDescriptor(
                "default",
                "occupied",
                ValueType.BOOLEAN,
                measurement_type="akenza/spaces/occupied/boolean",
            ),
            BinarySensorDeviceClass.OCCUPANCY,
        ),
        (
            DataPointDescriptor("default", "openWindow", ValueType.BOOLEAN),
            BinarySensorDeviceClass.WINDOW,
        ),
        (
            DataPointDescriptor("lifecycle", "brokenSensor", ValueType.BOOLEAN),
            BinarySensorDeviceClass.PROBLEM,
        ),
        (
            DataPointDescriptor("default", "childLock", ValueType.BOOLEAN),
            BinarySensorDeviceClass.LOCK,
        ),
        (DataPointDescriptor("default", "foo", ValueType.BOOLEAN), None),
    ],
)
def test_binary_spec(descriptor, device_class) -> None:
    """Boolean mapping."""
    assert binary_spec(descriptor, enable_hidden_kpis=False).device_class == device_class


@pytest.mark.parametrize(
    ("descriptor", "siblings", "device_class", "unit", "state_class"),
    [
        # EMU Professional II: meter reading vs. interval value with the same measurementType
        (
            DataPointDescriptor(
                "default",
                "activeEnergyPositiveCumulative",
                ValueType.NUMBER,
                unit="kWh",
                measurement_type="akenza/electricity/activeEnergy/kiloWattHours",
            ),
            {"activeenergypositivecumulative", "activeenergypositive"},
            SensorDeviceClass.ENERGY,
            "kWh",
            SensorStateClass.TOTAL_INCREASING,
        ),
        (
            DataPointDescriptor(
                "default",
                "activeEnergyPositive",
                ValueType.NUMBER,
                unit="kWh",
                measurement_type="akenza/electricity/activeEnergy/kiloWattHours",
            ),
            {"activeenergypositivecumulative", "activeenergypositive"},
            None,
            "kWh",
            SensorStateClass.MEASUREMENT,
        ),
        # niagara: consumption vs consumptionCumulative
        (
            DataPointDescriptor(
                "consumption",
                "consumption",
                ValueType.NUMBER,
                unit="kWh",
                measurement_type="akenza/electricity/activeEnergy/kiloWattHours",
            ),
            {"consumption", "consumptioncumulative"},
            None,
            "kWh",
            SensorStateClass.MEASUREMENT,
        ),
        # Triphas'O: measurementType "custom", units Wh / varh
        (
            DataPointDescriptor(
                "phase_abc",
                "activeEnergyPositiveCumulative",
                ValueType.NUMBER,
                unit="Wh",
                measurement_type="custom",
            ),
            set(),
            SensorDeviceClass.ENERGY,
            "Wh",
            SensorStateClass.TOTAL_INCREASING,
        ),
        (
            DataPointDescriptor(
                "phase_abc",
                "reactiveEnergyNegativeCumulative",
                ValueType.NUMBER,
                unit="varh",
                measurement_type="custom",
            ),
            set(),
            SensorDeviceClass.REACTIVE_ENERGY,
            "varh",
            SensorStateClass.TOTAL_INCREASING,
        ),
        # Milesight WS52x: cumulative Wh without measurementType
        (
            DataPointDescriptor("default", "powerConsumption", ValueType.NUMBER, unit="Wh"),
            set(),
            SensorDeviceClass.ENERGY,
            "Wh",
            SensorStateClass.TOTAL_INCREASING,
        ),
        # Milesight VS132: total vs periodic people counters
        (
            DataPointDescriptor(
                "default",
                "totalCounterIn",
                ValueType.INTEGER,
                unit="people",
                measurement_type="akenza/spaces/peopleIn/people",
            ),
            set(),
            None,
            "people",
            SensorStateClass.TOTAL_INCREASING,
        ),
        (
            DataPointDescriptor(
                "default",
                "periodicCounterIn",
                ValueType.INTEGER,
                unit="people",
                measurement_type="akenza/spaces/peopleIn/people",
            ),
            set(),
            None,
            "people",
            SensorStateClass.MEASUREMENT,
        ),
        # Multisense reed counter: absolute vs relative
        (
            DataPointDescriptor(
                "reed_counter",
                "reedCounter",
                ValueType.INTEGER,
                measurement_type="akenza/ios/reedContact/count",
            ),
            set(),
            None,
            None,
            SensorStateClass.TOTAL_INCREASING,
        ),
        (
            DataPointDescriptor(
                "reed_counter",
                "relativeReedCounter",
                ValueType.INTEGER,
                measurement_type="akenza/ios/reedContact/count",
            ),
            set(),
            None,
            None,
            SensorStateClass.MEASUREMENT,
        ),
        # water / gas / volume meters from custom device types
        (
            DataPointDescriptor("default", "waterVolume", ValueType.NUMBER, unit="m3"),
            set(),
            SensorDeviceClass.WATER,
            "m³",
            SensorStateClass.TOTAL_INCREASING,
        ),
        (
            DataPointDescriptor("default", "coldWaterTotal", ValueType.NUMBER, unit="L"),
            set(),
            SensorDeviceClass.WATER,
            "L",
            SensorStateClass.TOTAL_INCREASING,
        ),
        (
            DataPointDescriptor("default", "gasVolume", ValueType.NUMBER, unit="m³"),
            set(),
            SensorDeviceClass.GAS,
            "m³",
            SensorStateClass.TOTAL_INCREASING,
        ),
        (
            DataPointDescriptor("default", "volume", ValueType.NUMBER, unit="m3"),
            set(),
            SensorDeviceClass.VOLUME,
            "m³",
            SensorStateClass.TOTAL_INCREASING,
        ),
        (
            DataPointDescriptor("default", "flow", ValueType.NUMBER, unit="m3/h"),
            set(),
            SensorDeviceClass.VOLUME_FLOW_RATE,
            "m³/h",
            SensorStateClass.MEASUREMENT,
        ),
        # heat meter energy in MWh / GJ, unit only from the measurementType
        (
            DataPointDescriptor("default", "energy", ValueType.NUMBER, unit="MWh"),
            set(),
            SensorDeviceClass.ENERGY,
            "MWh",
            SensorStateClass.TOTAL_INCREASING,
        ),
        (
            DataPointDescriptor("default", "heatEnergy", ValueType.NUMBER, unit="GJ"),
            set(),
            SensorDeviceClass.ENERGY,
            "GJ",
            SensorStateClass.TOTAL_INCREASING,
        ),
        (
            DataPointDescriptor(
                "default",
                "energy",
                ValueType.NUMBER,
                measurement_type="akenza/electricity/activeEnergy/kiloWattHours",
            ),
            set(),
            SensorDeviceClass.ENERGY,
            "kWh",
            SensorStateClass.TOTAL_INCREASING,
        ),
        (
            DataPointDescriptor("default", "powerFactorL1", ValueType.NUMBER),
            set(),
            SensorDeviceClass.POWER_FACTOR,
            None,
            SensorStateClass.MEASUREMENT,
        ),
        # daily consumption is never a meter reading
        (
            DataPointDescriptor("default", "dailyEnergy", ValueType.NUMBER, unit="kWh"),
            set(),
            None,
            "kWh",
            SensorStateClass.MEASUREMENT,
        ),
    ],
)
def test_meter_specs(descriptor, siblings, device_class, unit, state_class) -> None:
    """Meter readings become total_increasing, interval values stay measurements."""
    spec = sensor_spec(descriptor, enable_hidden_kpis=False, sibling_keys=frozenset(siblings))
    assert spec.device_class == device_class
    assert spec.unit == unit
    assert spec.state_class == state_class
