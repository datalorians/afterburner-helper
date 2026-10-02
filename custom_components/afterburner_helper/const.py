"""Constants for the Afterburner Helper redesign."""

from __future__ import annotations

from datetime import timedelta

from homeassistant.const import Platform

DOMAIN = "afterburner_helper"
INTEGRATION_NAME = "Afterburner Helper"
PLATFORMS: list[Platform] = [
    Platform.SENSOR,
    Platform.NUMBER,
    Platform.BUTTON,
    Platform.CLIMATE,
    Platform.SELECT,
    Platform.SWITCH,
]
COORDINATOR_INTERVAL = timedelta(seconds=10)

CONF_DEVICE_NAME = "device_name"
CONF_MQTT_TOPIC_PREFIX = "mqtt_topic_prefix"
CONF_TANK_CAPACITY = "tank_capacity"
CONF_PUMP_ML_PER_STROKE = "pump_ml_per_stroke"
CONF_USAGE_CORRECTION_FACTOR = "usage_correction_factor"
CONF_MAXIMUM_PUMP_HZ = "maximum_pump_hz"
CONF_MINIMUM_PUMP_HZ = "minimum_pump_hz"
CONF_THERMAL_CYCLING_ENABLED = "thermal_cycling_enabled"
# Canonical v2.2 names.  The legacy upper/lower keys remain readable so an
# existing config entry keeps its configured values until options are saved.
CONF_STOP_OFFSET_C = "stop_offset_c"
CONF_START_OFFSET_C = "start_offset_c"
CONF_UPPER_OFFSET_C = "upper_offset_c"
CONF_LOWER_OFFSET_C = "lower_offset_c"
CONF_ACTIVE_CONTROL_ENABLED = "active_control_enabled"
CONF_EARLY_RECOVERY_ENABLED = "early_recovery_enabled"
CONF_RECOVERY_SETPOINT_C = "recovery_setpoint_c"
CONF_RECOVERY_TIMEOUT_S = "recovery_timeout_s"
CONF_RECOVERY_MIN_RISE_C = "recovery_minimum_rise_c"
CONF_CLIMATE_ENTITY_ID = "climate_entity_id"
CONF_DIESEL_PRICE_PER_LITRE = "diesel_price_per_litre"
CONF_ROOM_TEMPERATURE_ENTITY_ID = "room_temperature_entity_id"
CONF_ELECTRIC_HEATER_1_ENTITY_ID = "electric_heater_1_entity_id"
CONF_ELECTRIC_HEATER_2_ENTITY_ID = "electric_heater_2_entity_id"

DEFAULT_DEVICE_NAME = "Afterburner"
DEFAULT_MQTT_TOPIC_PREFIX = "Afterburner"
DEFAULT_TANK_CAPACITY = 20.0
DEFAULT_PUMP_ML_PER_STROKE = 0.022
DEFAULT_USAGE_CORRECTION_FACTOR = 1.0
DEFAULT_MAXIMUM_PUMP_HZ = 3.9
DEFAULT_MINIMUM_PUMP_HZ = 1.2
DEFAULT_STOP_OFFSET_C = 5.0
DEFAULT_START_OFFSET_C = 5.0
DEFAULT_UPPER_OFFSET_C = 5.0
DEFAULT_LOWER_OFFSET_C = 5.0
DEFAULT_CLIMATE_ENTITY_ID = "climate.afterburner"
DEFAULT_RECOVERY_SETPOINT_C = 35.0
DEFAULT_RECOVERY_TIMEOUT_S = 120.0
DEFAULT_RECOVERY_MIN_RISE_C = 5.0
DEFAULT_DIESEL_PRICE_PER_LITRE = 0.0
DEFAULT_ROOM_TEMPERATURE_ENTITY_ID = "sensor.afterburner_temperature_3"
DEFAULT_ELECTRIC_HEATER_1_ENTITY_ID = "switch.s31_3_sonoff_s31_relay"
DEFAULT_ELECTRIC_HEATER_2_ENTITY_ID = ""

HEAT_SOURCES = ("diesel", "electric_1", "electric_2")
HEAT_SOURCE_LABELS = {
    "diesel": "Diesel",
    "electric_1": "Electric 1",
    "electric_2": "Electric 2",
}
PRIORITY_OPTIONS = (
    "Electric 1 → Electric 2 → Diesel",
    "Electric 1 → Diesel → Electric 2",
    "Electric 2 → Electric 1 → Diesel",
    "Electric 2 → Diesel → Electric 1",
    "Diesel → Electric 1 → Electric 2",
    "Diesel → Electric 2 → Electric 1",
)

# Existing MQTT/autodiscovery entities used as read-only sources. These become
# configurable in the next config-flow milestone.
SOURCE_ENTITIES = {
    "run_state": "sensor.afterburner_run_state",
    "error_state": "sensor.afterburner_error_state",
    "pump_hz": "sensor.afterburner_pump_speed",
    "fan_rpm": "sensor.afterburner_fan_speed",
    "body_c": "sensor.afterburner_heater_temperature",
    "room_c": "sensor.afterburner_temperature_3",
    "setpoint_c": "sensor.afterburner_desired",
    "input_v": "sensor.afterburner_input_voltage",
    "glow_v": "sensor.afterburner_glow_plug_voltage",
    "fuel_used_l": "sensor.afterburner_fuel_used",
    "run_request": "binary_sensor.afterburner_run_request",
}
