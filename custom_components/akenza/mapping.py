"""Map akenza data-point descriptors to Home Assistant entity attributes."""

from __future__ import annotations

from dataclasses import dataclass

from homeassistant.components.binary_sensor import BinarySensorDeviceClass
from homeassistant.components.sensor import (
    DEVICE_CLASS_STATE_CLASSES,
    DEVICE_CLASS_UNITS,
    SensorDeviceClass,
    SensorStateClass,
)
from homeassistant.const import (
    DEGREE,
    LIGHT_LUX,
    PERCENTAGE,
    SIGNAL_STRENGTH_DECIBELS,
    SIGNAL_STRENGTH_DECIBELS_MILLIWATT,
    EntityCategory,
    UnitOfApparentPower,
    UnitOfDensity,
    UnitOfElectricCurrent,
    UnitOfElectricPotential,
    UnitOfEnergy,
    UnitOfFrequency,
    UnitOfLength,
    UnitOfPower,
    UnitOfPressure,
    UnitOfRatio,
    UnitOfReactiveEnergy,
    UnitOfReactivePower,
    UnitOfSoundPressure,
    UnitOfSpeed,
    UnitOfTemperature,
    UnitOfTime,
)

from .const import (
    DEFAULT_TOPIC,
    DIAGNOSTIC_TOPIC_PREFIXES,
    DIAGNOSTIC_TOPICS,
    DISABLED_TOPICS,
)
from .models import DataPointDescriptor, ValueType

# akenza unit spellings -> HA unit strings
UNIT_ALIASES: dict[str, str] = {
    "°C": UnitOfTemperature.CELSIUS,
    "C": UnitOfTemperature.CELSIUS,
    "°F": UnitOfTemperature.FAHRENHEIT,
    "K": UnitOfTemperature.KELVIN,
    "%": PERCENTAGE,
    "percent": PERCENTAGE,
    "ppm": UnitOfRatio.PARTS_PER_MILLION,
    "ppb": UnitOfRatio.PARTS_PER_BILLION,
    "μg/m3": UnitOfDensity.MICROGRAMS_PER_CUBIC_METER,
    "µg/m3": UnitOfDensity.MICROGRAMS_PER_CUBIC_METER,
    "ug/m3": UnitOfDensity.MICROGRAMS_PER_CUBIC_METER,
    "μg/m³": UnitOfDensity.MICROGRAMS_PER_CUBIC_METER,
    "µg/m³": UnitOfDensity.MICROGRAMS_PER_CUBIC_METER,
    "mcgm3": UnitOfDensity.MICROGRAMS_PER_CUBIC_METER,
    "Pa": UnitOfPressure.PA,
    "hPa": UnitOfPressure.HPA,
    "kPa": UnitOfPressure.KPA,
    "bar": UnitOfPressure.BAR,
    "mbar": UnitOfPressure.MBAR,
    "psi": UnitOfPressure.PSI,
    "lx": LIGHT_LUX,
    "lux": LIGHT_LUX,
    "dB(A)": UnitOfSoundPressure.WEIGHTED_DECIBEL_A,
    "dBA": UnitOfSoundPressure.WEIGHTED_DECIBEL_A,
    "dba": UnitOfSoundPressure.WEIGHTED_DECIBEL_A,
    "dB(SPL)": UnitOfSoundPressure.DECIBEL,
    "dbspl": UnitOfSoundPressure.DECIBEL,
    "dB": UnitOfSoundPressure.DECIBEL,
    "dBm": SIGNAL_STRENGTH_DECIBELS_MILLIWATT,
    "V": UnitOfElectricPotential.VOLT,
    "volt": UnitOfElectricPotential.VOLT,
    "mV": UnitOfElectricPotential.MILLIVOLT,
    "A": UnitOfElectricCurrent.AMPERE,
    "mA": UnitOfElectricCurrent.MILLIAMPERE,
    "W": UnitOfPower.WATT,
    "kW": UnitOfPower.KILO_WATT,
    "Wh": UnitOfEnergy.WATT_HOUR,
    "kWh": UnitOfEnergy.KILO_WATT_HOUR,
    "VA": UnitOfApparentPower.VOLT_AMPERE,
    "VAR": UnitOfReactivePower.VOLT_AMPERE_REACTIVE,
    "var": UnitOfReactivePower.VOLT_AMPERE_REACTIVE,
    "kVAR": UnitOfReactivePower.KILO_VOLT_AMPERE_REACTIVE,
    "VARh": UnitOfReactiveEnergy.VOLT_AMPERE_REACTIVE_HOUR,
    "varh": UnitOfReactiveEnergy.VOLT_AMPERE_REACTIVE_HOUR,
    "kVARh": UnitOfReactiveEnergy.KILO_VOLT_AMPERE_REACTIVE_HOUR,
    "Hz": UnitOfFrequency.HERTZ,
    "mm": UnitOfLength.MILLIMETERS,
    "cm": UnitOfLength.CENTIMETERS,
    "m": UnitOfLength.METERS,
    "km": UnitOfLength.KILOMETERS,
    "km/h": UnitOfSpeed.KILOMETERS_PER_HOUR,
    "m/s": UnitOfSpeed.METERS_PER_SECOND,
    "°": DEGREE,
    "degrees": DEGREE,
    "min": UnitOfTime.MINUTES,
    "s": UnitOfTime.SECONDS,
    "h": UnitOfTime.HOURS,
}

# measurementType "<type>" (second path segment of akenza/<category>/<type>/<unit>) -> sensor device class
_TYPE_DEVICE_CLASS: dict[str, SensorDeviceClass] = {
    "temperature": SensorDeviceClass.TEMPERATURE,
    "humidity": SensorDeviceClass.HUMIDITY,
    "co2": SensorDeviceClass.CO2,
    "tvoc": SensorDeviceClass.VOLATILE_ORGANIC_COMPOUNDS_PARTS,
    "pm1": SensorDeviceClass.PM1,
    "pm2_5": SensorDeviceClass.PM25,
    "pm4": SensorDeviceClass.PM4,
    "pm10": SensorDeviceClass.PM10,
    "pressure": SensorDeviceClass.ATMOSPHERIC_PRESSURE,
    "illuminance": SensorDeviceClass.ILLUMINANCE,
    "soundLevel": SensorDeviceClass.SOUND_PRESSURE,
    "batteryLevel": SensorDeviceClass.BATTERY,
    "batteryVoltage": SensorDeviceClass.VOLTAGE,
    "rssi": SensorDeviceClass.SIGNAL_STRENGTH,
    "voltage": SensorDeviceClass.VOLTAGE,
    "analogInput": SensorDeviceClass.VOLTAGE,
    "current": SensorDeviceClass.CURRENT,
    "activePower": SensorDeviceClass.POWER,
    "activeEnergy": SensorDeviceClass.ENERGY,
    "apparentPower": SensorDeviceClass.APPARENT_POWER,
    "reactivePower": SensorDeviceClass.REACTIVE_POWER,
    "reactiveEnergy": SensorDeviceClass.REACTIVE_ENERGY,
    "frequency": SensorDeviceClass.FREQUENCY,
    "distance": SensorDeviceClass.DISTANCE,
    "fillLevel": SensorDeviceClass.DISTANCE,  # only kept when the unit is a length
    "speed": SensorDeviceClass.SPEED,
}

# measurement types that are monotonically increasing counters
_TOTAL_INCREASING_TYPES = {
    "activeEnergy",
    "reactiveEnergy",
    "apparentEnergy",
    "peopleIn",
    "peopleOut",
    "pulseInput",
    "motion",
    "usage",
}
# measurement types without a state class (events / positions)
_NO_STATE_CLASS_TYPES = {
    "latitude",
    "longitude",
    "buttonEvent",
    "buttonStatus",
    "digitalOutput",
    "system",
}
# akenza measurement categories whose data points are diagnostic
_DIAGNOSTIC_CATEGORIES = {"device", "system"}
_DIAGNOSTIC_KEYS = {
    "rssi",
    "snr",
    "sf",
    "sqi",
    "esp",
    "fcnt",
    "fcntup",
    "fcntdown",
    "framecount",
    "framecountup",
    "framecountdown",
    "batterylevel",
    "batteryvoltage",
    "battery",
    "firmware",
    "fwversion",
    "firmwareversion",
    "port",
    "fport",
    "gateways",
    "numberofgateways",
    "uplinksize",
    "payloadhex",
}

# unit-only fallback when no measurementType is present
_UNIT_DEVICE_CLASS: dict[str, SensorDeviceClass] = {
    UnitOfTemperature.CELSIUS: SensorDeviceClass.TEMPERATURE,
    UnitOfTemperature.FAHRENHEIT: SensorDeviceClass.TEMPERATURE,
    UnitOfTemperature.KELVIN: SensorDeviceClass.TEMPERATURE,
    UnitOfRatio.PARTS_PER_MILLION: SensorDeviceClass.CO2,
    UnitOfRatio.PARTS_PER_BILLION: SensorDeviceClass.VOLATILE_ORGANIC_COMPOUNDS_PARTS,
    LIGHT_LUX: SensorDeviceClass.ILLUMINANCE,
    UnitOfPressure.HPA: SensorDeviceClass.ATMOSPHERIC_PRESSURE,
    UnitOfPressure.PA: SensorDeviceClass.ATMOSPHERIC_PRESSURE,
    UnitOfPressure.KPA: SensorDeviceClass.ATMOSPHERIC_PRESSURE,
    UnitOfPressure.BAR: SensorDeviceClass.ATMOSPHERIC_PRESSURE,
    UnitOfPressure.MBAR: SensorDeviceClass.ATMOSPHERIC_PRESSURE,
    SIGNAL_STRENGTH_DECIBELS_MILLIWATT: SensorDeviceClass.SIGNAL_STRENGTH,
    UnitOfElectricPotential.VOLT: SensorDeviceClass.VOLTAGE,
    UnitOfElectricPotential.MILLIVOLT: SensorDeviceClass.VOLTAGE,
    UnitOfElectricCurrent.AMPERE: SensorDeviceClass.CURRENT,
    UnitOfElectricCurrent.MILLIAMPERE: SensorDeviceClass.CURRENT,
    UnitOfPower.WATT: SensorDeviceClass.POWER,
    UnitOfPower.KILO_WATT: SensorDeviceClass.POWER,
    UnitOfEnergy.WATT_HOUR: SensorDeviceClass.ENERGY,
    UnitOfEnergy.KILO_WATT_HOUR: SensorDeviceClass.ENERGY,
    UnitOfSoundPressure.WEIGHTED_DECIBEL_A: SensorDeviceClass.SOUND_PRESSURE,
    UnitOfDensity.MICROGRAMS_PER_CUBIC_METER: SensorDeviceClass.PM25,
    UnitOfFrequency.HERTZ: SensorDeviceClass.FREQUENCY,
    UnitOfApparentPower.VOLT_AMPERE: SensorDeviceClass.APPARENT_POWER,
    UnitOfReactivePower.VOLT_AMPERE_REACTIVE: SensorDeviceClass.REACTIVE_POWER,
    UnitOfLength.MILLIMETERS: SensorDeviceClass.DISTANCE,
    UnitOfLength.CENTIMETERS: SensorDeviceClass.DISTANCE,
    UnitOfLength.METERS: SensorDeviceClass.DISTANCE,
    UnitOfLength.KILOMETERS: SensorDeviceClass.DISTANCE,
    UnitOfSpeed.KILOMETERS_PER_HOUR: SensorDeviceClass.SPEED,
    UnitOfSpeed.METERS_PER_SECOND: SensorDeviceClass.SPEED,
}

# key-name heuristics (lower-cased substring -> (device class, default unit))
_KEY_HEURISTICS: tuple[tuple[str, SensorDeviceClass, str | None], ...] = (
    ("temperature", SensorDeviceClass.TEMPERATURE, UnitOfTemperature.CELSIUS),
    ("humidity", SensorDeviceClass.HUMIDITY, PERCENTAGE),
    ("co2", SensorDeviceClass.CO2, UnitOfRatio.PARTS_PER_MILLION),
    ("tvoc", SensorDeviceClass.VOLATILE_ORGANIC_COMPOUNDS_PARTS, UnitOfRatio.PARTS_PER_BILLION),
    ("pm2_5", SensorDeviceClass.PM25, UnitOfDensity.MICROGRAMS_PER_CUBIC_METER),
    ("pm25", SensorDeviceClass.PM25, UnitOfDensity.MICROGRAMS_PER_CUBIC_METER),
    ("pm10", SensorDeviceClass.PM10, UnitOfDensity.MICROGRAMS_PER_CUBIC_METER),
    ("pm1", SensorDeviceClass.PM1, UnitOfDensity.MICROGRAMS_PER_CUBIC_METER),
    ("batterylevel", SensorDeviceClass.BATTERY, PERCENTAGE),
    ("batterypercent", SensorDeviceClass.BATTERY, PERCENTAGE),
    ("batteryvoltage", SensorDeviceClass.VOLTAGE, UnitOfElectricPotential.VOLT),
    ("illuminance", SensorDeviceClass.ILLUMINANCE, LIGHT_LUX),
    ("lux", SensorDeviceClass.ILLUMINANCE, LIGHT_LUX),
    ("rssi", SensorDeviceClass.SIGNAL_STRENGTH, SIGNAL_STRENGTH_DECIBELS_MILLIWATT),
    ("snr", SensorDeviceClass.SIGNAL_STRENGTH, SIGNAL_STRENGTH_DECIBELS),
    ("pressure", SensorDeviceClass.ATMOSPHERIC_PRESSURE, None),
    ("voltage", SensorDeviceClass.VOLTAGE, None),
    ("current", SensorDeviceClass.CURRENT, None),
    ("energy", SensorDeviceClass.ENERGY, None),
    ("power", SensorDeviceClass.POWER, None),
    ("distance", SensorDeviceClass.DISTANCE, None),
    ("speed", SensorDeviceClass.SPEED, None),
)

_BINARY_TYPE_CLASS: dict[str, BinarySensorDeviceClass] = {
    "occupied": BinarySensorDeviceClass.OCCUPANCY,
    "occupiedOrWarm": BinarySensorDeviceClass.OCCUPANCY,
    "motion": BinarySensorDeviceClass.MOTION,
    "reedContact": BinarySensorDeviceClass.OPENING,
    "presence": BinarySensorDeviceClass.PRESENCE,
}

_BINARY_KEY_HEURISTICS: tuple[tuple[str, BinarySensorDeviceClass], ...] = (
    ("occupied", BinarySensorDeviceClass.OCCUPANCY),
    ("occupancy", BinarySensorDeviceClass.OCCUPANCY),
    ("presence", BinarySensorDeviceClass.PRESENCE),
    ("motion", BinarySensorDeviceClass.MOTION),
    ("window", BinarySensorDeviceClass.WINDOW),
    ("door", BinarySensorDeviceClass.DOOR),
    ("reed", BinarySensorDeviceClass.OPENING),
    ("open", BinarySensorDeviceClass.OPENING),
    ("leak", BinarySensorDeviceClass.MOISTURE),
    ("water", BinarySensorDeviceClass.MOISTURE),
    ("moisture", BinarySensorDeviceClass.MOISTURE),
    ("tamper", BinarySensorDeviceClass.TAMPER),
    ("vibration", BinarySensorDeviceClass.VIBRATION),
    ("shock", BinarySensorDeviceClass.VIBRATION),
    ("smoke", BinarySensorDeviceClass.SMOKE),
    ("online", BinarySensorDeviceClass.CONNECTIVITY),
    ("connected", BinarySensorDeviceClass.CONNECTIVITY),
    ("lock", BinarySensorDeviceClass.LOCK),
    ("alarm", BinarySensorDeviceClass.PROBLEM),
    ("error", BinarySensorDeviceClass.PROBLEM),
    ("fault", BinarySensorDeviceClass.PROBLEM),
    ("broken", BinarySensorDeviceClass.PROBLEM),
    ("running", BinarySensorDeviceClass.RUNNING),
)

_PRECISION: dict[SensorDeviceClass, int] = {
    SensorDeviceClass.TEMPERATURE: 1,
    SensorDeviceClass.HUMIDITY: 0,
    SensorDeviceClass.CO2: 0,
    SensorDeviceClass.ILLUMINANCE: 0,
    SensorDeviceClass.BATTERY: 0,
    SensorDeviceClass.VOLTAGE: 2,
    SensorDeviceClass.CURRENT: 2,
    SensorDeviceClass.POWER: 1,
    SensorDeviceClass.ENERGY: 3,
    SensorDeviceClass.ATMOSPHERIC_PRESSURE: 1,
    SensorDeviceClass.SIGNAL_STRENGTH: 0,
    SensorDeviceClass.SOUND_PRESSURE: 1,
}


# icons for data points that have no device class (device classes bring their own icons)
_TYPE_ICONS: dict[str, str] = {
    "occupancy": "mdi:account-group",
    "occupied": "mdi:account-check",
    "peopleIn": "mdi:login",
    "peopleOut": "mdi:logout",
    "peopleCount": "mdi:account-multiple",
    "motion": "mdi:motion-sensor",
    "brightness": "mdi:brightness-6",
    "fillLevel": "mdi:cup-water",
    "acceleration": "mdi:axis-arrow",
    "latitude": "mdi:latitude",
    "longitude": "mdi:longitude",
    "buttonEvent": "mdi:gesture-tap-button",
    "buttonStatus": "mdi:gesture-tap-button",
    "digitalInput": "mdi:electric-switch",
    "digitalOutput": "mdi:electric-switch",
    "pulseInput": "mdi:pulse",
    "usage": "mdi:counter",
    "system": "mdi:information-outline",
}
_KEY_ICONS: tuple[tuple[str, str], ...] = (
    ("occupan", "mdi:account-group"),
    ("people", "mdi:account-multiple"),
    ("motion", "mdi:motion-sensor"),
    ("count", "mdi:counter"),
    ("latitude", "mdi:latitude"),
    ("longitude", "mdi:longitude"),
    ("heading", "mdi:compass"),
    ("speed", "mdi:speedometer"),
    ("button", "mdi:gesture-tap-button"),
    ("door", "mdi:door"),
    ("window", "mdi:window-closed-variant"),
    ("valve", "mdi:valve"),
    ("motor", "mdi:engine"),
    ("position", "mdi:arrow-expand-vertical"),
    ("level", "mdi:gauge"),
    ("period", "mdi:timer-outline"),
    ("interval", "mdi:timer-outline"),
    ("time", "mdi:clock-outline"),
    ("version", "mdi:tag-outline"),
    ("firmware", "mdi:chip"),
    ("payload", "mdi:code-braces"),
    ("error", "mdi:alert-circle-outline"),
    ("status", "mdi:information-outline"),
    ("state", "mdi:information-outline"),
    ("mode", "mdi:tune"),
    ("type", "mdi:shape-outline"),
    ("id", "mdi:identifier"),
    ("name", "mdi:tag-text-outline"),
    ("port", "mdi:ethernet"),
    ("rssi", "mdi:signal"),
    ("snr", "mdi:signal-variant"),
    ("sf", "mdi:radio-tower"),
    ("gateway", "mdi:access-point-network"),
    ("voltage", "mdi:flash"),
    ("current", "mdi:current-ac"),
    ("power", "mdi:flash"),
    ("energy", "mdi:lightning-bolt"),
    ("temperature", "mdi:thermometer"),
    ("humidity", "mdi:water-percent"),
    ("co2", "mdi:molecule-co2"),
    ("light", "mdi:brightness-5"),
    ("sound", "mdi:volume-high"),
    ("noise", "mdi:volume-high"),
    ("battery", "mdi:battery"),
    ("distance", "mdi:ruler"),
    ("pressure", "mdi:gauge"),
    ("water", "mdi:water"),
    ("soil", "mdi:sprout"),
    ("trip", "mdi:map-marker-path"),
    ("gnss", "mdi:satellite-variant"),
    ("gps", "mdi:satellite-variant"),
)


def icon_for(descriptor: DataPointDescriptor) -> str | None:
    """Return an mdi icon for data points without a device class."""
    _, mtype, _ = split_measurement_type(descriptor.measurement_type)
    if mtype and mtype in _TYPE_ICONS:
        return _TYPE_ICONS[mtype]
    key_lower = descriptor.key.rsplit(".", 1)[-1].lower()
    for needle, icon in _KEY_ICONS:
        if needle in key_lower:
            return icon
    if descriptor.value_type is ValueType.STRING:
        return "mdi:text"
    if descriptor.value_type is ValueType.BOOLEAN:
        return "mdi:toggle-switch-outline"
    return "mdi:numeric"


@dataclass(frozen=True, slots=True)
class SensorSpec:
    """Resolved HA attributes for a numeric/string data point."""

    device_class: SensorDeviceClass | None
    state_class: SensorStateClass | None
    unit: str | None
    entity_category: EntityCategory | None
    enabled_default: bool
    precision: int | None
    options: tuple[str, ...] | None
    icon: str | None = None


@dataclass(frozen=True, slots=True)
class BinarySpec:
    """Resolved HA attributes for a boolean data point."""

    device_class: BinarySensorDeviceClass | None
    entity_category: EntityCategory | None
    enabled_default: bool
    icon: str | None = None


def split_measurement_type(
    measurement_type: str | None,
) -> tuple[str | None, str | None, str | None]:
    """Split 'akenza/environment/temperature/celsius' -> (category, type, unit)."""
    if not measurement_type:
        return None, None, None
    parts = measurement_type.split("/")
    if parts and parts[0] == "akenza":
        parts = parts[1:]
    category = parts[0] if len(parts) > 0 else None
    mtype = parts[1] if len(parts) > 1 else None
    unit = parts[2] if len(parts) > 2 else None
    return category, mtype, unit


def normalize_unit(unit: str | None) -> str | None:
    """Map an akenza unit spelling to the HA unit string."""
    if not unit:
        return None
    return UNIT_ALIASES.get(unit, UNIT_ALIASES.get(unit.strip(), unit.strip()))


def is_diagnostic(descriptor: DataPointDescriptor) -> bool:
    """Whether the data point should be in the diagnostic entity category."""
    topic = descriptor.topic
    if topic in DIAGNOSTIC_TOPICS or topic.startswith(DIAGNOSTIC_TOPIC_PREFIXES):
        return True
    category, _, _ = split_measurement_type(descriptor.measurement_type)
    if category in _DIAGNOSTIC_CATEGORIES:
        return True
    key = descriptor.key.rsplit(".", 1)[-1].lower()
    return key in _DIAGNOSTIC_KEYS or descriptor.hide_from_kpis


def is_disabled_by_default(descriptor: DataPointDescriptor, *, enable_hidden_kpis: bool) -> bool:
    """Whether the entity should be created disabled."""
    topic = descriptor.topic
    if topic in DISABLED_TOPICS or topic.startswith(DIAGNOSTIC_TOPIC_PREFIXES):
        return True
    return descriptor.hide_from_kpis and not enable_hidden_kpis


def is_default_topic(descriptor: DataPointDescriptor) -> bool:
    """Whether the data point lives on the default topic."""
    return descriptor.topic == DEFAULT_TOPIC


def _valid_unit(device_class: SensorDeviceClass, unit: str | None) -> bool:
    allowed = DEVICE_CLASS_UNITS.get(device_class)
    if allowed is None:
        return True
    return unit in allowed


def _state_class_for(
    device_class: SensorDeviceClass | None, wanted: SensorStateClass | None
) -> SensorStateClass | None:
    if wanted is None:
        return None
    if device_class is None:
        return wanted
    allowed = DEVICE_CLASS_STATE_CLASSES.get(device_class)
    if allowed is None:
        return wanted
    if wanted in allowed:
        return wanted
    if SensorStateClass.MEASUREMENT in allowed:
        return SensorStateClass.MEASUREMENT
    return next(iter(allowed), None)


def sensor_spec(descriptor: DataPointDescriptor, *, enable_hidden_kpis: bool) -> SensorSpec:
    """Resolve HA sensor attributes for a number/integer/string data point."""
    category, mtype, _ = split_measurement_type(descriptor.measurement_type)
    unit = normalize_unit(descriptor.unit)
    key_lower = descriptor.key.rsplit(".", 1)[-1].lower()
    entity_category = EntityCategory.DIAGNOSTIC if is_diagnostic(descriptor) else None
    enabled = not is_disabled_by_default(descriptor, enable_hidden_kpis=enable_hidden_kpis)

    if descriptor.value_type is ValueType.STRING:
        device_class: SensorDeviceClass | None = None
        options = descriptor.enum
        if options:
            device_class = SensorDeviceClass.ENUM
        elif "timestamp" in key_lower or key_lower.endswith("time") or key_lower.endswith("date"):
            device_class = SensorDeviceClass.TIMESTAMP
        return SensorSpec(
            device_class=device_class,
            state_class=None,
            unit=None,
            entity_category=entity_category,
            enabled_default=enabled,
            precision=None,
            options=options,
            icon=icon_for(descriptor) if device_class is None else None,
        )

    device_class = None
    wanted_state_class: SensorStateClass | None = SensorStateClass.MEASUREMENT

    if mtype:
        device_class = _TYPE_DEVICE_CLASS.get(mtype)
        if mtype in _TOTAL_INCREASING_TYPES:
            wanted_state_class = SensorStateClass.TOTAL_INCREASING
        elif mtype in _NO_STATE_CLASS_TYPES:
            wanted_state_class = None
    if device_class is None and unit is not None:
        device_class = _UNIT_DEVICE_CLASS.get(unit)
        if device_class is SensorDeviceClass.CO2 and "co2" not in key_lower:
            device_class = None
        if device_class is SensorDeviceClass.PM25 and "pm" not in key_lower:
            device_class = None
        if device_class is SensorDeviceClass.ENERGY:
            wanted_state_class = SensorStateClass.TOTAL_INCREASING
    if device_class is None and not mtype:
        for needle, candidate, default_unit in _KEY_HEURISTICS:
            if needle in key_lower:
                if unit is None and default_unit is not None:
                    unit = default_unit
                device_class = candidate
                if candidate is SensorDeviceClass.ENERGY:
                    wanted_state_class = SensorStateClass.TOTAL_INCREASING
                break
    if device_class is not None and not _valid_unit(device_class, unit):
        device_class = None
    if not mtype and key_lower in ("latitude", "longitude", "lat", "lon", "lng", "heading", "headingdeg"):
        wanted_state_class = None
    if unit == PERCENTAGE and device_class is None and descriptor.value_type is ValueType.INTEGER:
        wanted_state_class = SensorStateClass.MEASUREMENT
    state_class = _state_class_for(device_class, wanted_state_class)
    precision = _PRECISION.get(device_class) if device_class else None
    return SensorSpec(
        device_class=device_class,
        state_class=state_class,
        unit=unit,
        entity_category=entity_category,
        enabled_default=enabled,
        precision=precision,
        options=None,
        icon=icon_for(descriptor) if device_class is None else None,
    )


def binary_spec(descriptor: DataPointDescriptor, *, enable_hidden_kpis: bool) -> BinarySpec:
    """Resolve HA binary-sensor attributes for a boolean data point."""
    _, mtype, _ = split_measurement_type(descriptor.measurement_type)
    device_class = _BINARY_TYPE_CLASS.get(mtype) if mtype else None
    if device_class is None:
        key_lower = descriptor.key.rsplit(".", 1)[-1].lower()
        for needle, candidate in _BINARY_KEY_HEURISTICS:
            if needle in key_lower:
                device_class = candidate
                break
    return BinarySpec(
        device_class=device_class,
        entity_category=EntityCategory.DIAGNOSTIC if is_diagnostic(descriptor) else None,
        enabled_default=not is_disabled_by_default(
            descriptor, enable_hidden_kpis=enable_hidden_kpis
        ),
    )
