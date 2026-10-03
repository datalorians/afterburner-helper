"""Config flow for Afterburner Helper v2."""

from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.helpers import selector

from .const import (
    CONF_ACTIVE_CONTROL_ENABLED,
    CONF_CLIMATE_ENTITY_ID,
    CONF_DEVICE_NAME,
    CONF_DIESEL_PRICE_PER_LITRE,
    CONF_ELECTRIC_HEATER_1_ENTITY_ID,
    CONF_ELECTRIC_HEATER_2_ENTITY_ID,
    CONF_FUSED_TEMPERATURE_ENTITIES,
    CONF_FAILED_START_RETRY_MINUTES,
    CONF_OUTDOOR_TEMPERATURE_ENTITY_ID,
    CONF_LOWER_OFFSET_C,
    CONF_MAXIMUM_PUMP_HZ,
    CONF_MINIMUM_PUMP_HZ,
    CONF_MINIMUM_ON_CYCLE_MINUTES,
    CONF_MINIMUM_OFF_CYCLE_MINUTES,
    CONF_MQTT_TOPIC_PREFIX,
    CONF_ROOM_TEMPERATURE_ENTITY_ID,
    CONF_USE_FUSED_TEMPERATURE,
    CONF_PUMP_ML_PER_STROKE,
    CONF_EARLY_RECOVERY_ENABLED,
    CONF_RECOVERY_MIN_RISE_C,
    CONF_RECOVERY_SETPOINT_C,
    CONF_RECOVERY_TIMEOUT_S,
    CONF_START_OFFSET_C,
    CONF_STOP_OFFSET_C,
    CONF_TANK_CAPACITY,
    CONF_THERMAL_CYCLING_ENABLED,
    CONF_UPPER_OFFSET_C,
    CONF_USAGE_CORRECTION_FACTOR,
    DEFAULT_DEVICE_NAME,
    DEFAULT_DIESEL_PRICE_PER_LITRE,
    DEFAULT_ELECTRIC_HEATER_1_ENTITY_ID,
    DEFAULT_ELECTRIC_HEATER_2_ENTITY_ID,
    DEFAULT_FUSED_TEMPERATURE_ENTITIES,
    DEFAULT_FAILED_START_RETRY_MINUTES,
    DEFAULT_OUTDOOR_TEMPERATURE_ENTITY_ID,
    DEFAULT_CLIMATE_ENTITY_ID,
    DEFAULT_LOWER_OFFSET_C,
    DEFAULT_MAXIMUM_PUMP_HZ,
    DEFAULT_MINIMUM_PUMP_HZ,
    DEFAULT_MINIMUM_ON_CYCLE_MINUTES,
    DEFAULT_MINIMUM_OFF_CYCLE_MINUTES,
    DEFAULT_MQTT_TOPIC_PREFIX,
    DEFAULT_ROOM_TEMPERATURE_ENTITY_ID,
    DEFAULT_USE_FUSED_TEMPERATURE,
    DEFAULT_PUMP_ML_PER_STROKE,
    DEFAULT_RECOVERY_MIN_RISE_C,
    DEFAULT_RECOVERY_SETPOINT_C,
    DEFAULT_RECOVERY_TIMEOUT_S,
    DEFAULT_START_OFFSET_C,
    DEFAULT_STOP_OFFSET_C,
    DEFAULT_TANK_CAPACITY,
    DEFAULT_UPPER_OFFSET_C,
    DEFAULT_USAGE_CORRECTION_FACTOR,
    DOMAIN,
)


def _initial_schema() -> vol.Schema:
    return vol.Schema(
        {
            vol.Required(CONF_DEVICE_NAME, default=DEFAULT_DEVICE_NAME): str,
            vol.Required(
                CONF_MQTT_TOPIC_PREFIX, default=DEFAULT_MQTT_TOPIC_PREFIX
            ): str,
            vol.Required(
                CONF_TANK_CAPACITY, default=DEFAULT_TANK_CAPACITY
            ): vol.All(vol.Coerce(float), vol.Range(min=1, max=500)),
        }
    )


def _options_schema(defaults: dict[str, Any]) -> vol.Schema:
    return vol.Schema(
        {
            vol.Required(
                CONF_TANK_CAPACITY,
                default=defaults.get(CONF_TANK_CAPACITY, DEFAULT_TANK_CAPACITY),
            ): vol.All(vol.Coerce(float), vol.Range(min=1, max=500)),
            vol.Required(
                CONF_DIESEL_PRICE_PER_LITRE,
                default=defaults.get(
                    CONF_DIESEL_PRICE_PER_LITRE,
                    DEFAULT_DIESEL_PRICE_PER_LITRE,
                ),
            ): vol.All(vol.Coerce(float), vol.Range(min=0, max=5)),
            vol.Required(
                CONF_PUMP_ML_PER_STROKE,
                default=defaults.get(
                    CONF_PUMP_ML_PER_STROKE, DEFAULT_PUMP_ML_PER_STROKE
                ),
            ): vol.All(vol.Coerce(float), vol.Range(min=0.001, max=0.1)),
            vol.Required(
                CONF_USAGE_CORRECTION_FACTOR,
                default=defaults.get(
                    CONF_USAGE_CORRECTION_FACTOR, DEFAULT_USAGE_CORRECTION_FACTOR
                ),
            ): vol.All(vol.Coerce(float), vol.Range(min=0.5, max=1.5)),
            vol.Required(
                CONF_MINIMUM_PUMP_HZ,
                default=defaults.get(CONF_MINIMUM_PUMP_HZ, DEFAULT_MINIMUM_PUMP_HZ),
            ): vol.All(vol.Coerce(float), vol.Range(min=0.5, max=3.0)),
            vol.Required(
                CONF_MAXIMUM_PUMP_HZ,
                default=defaults.get(CONF_MAXIMUM_PUMP_HZ, DEFAULT_MAXIMUM_PUMP_HZ),
            ): vol.All(vol.Coerce(float), vol.Range(min=1.0, max=10.0)),
            vol.Required(
                CONF_THERMAL_CYCLING_ENABLED,
                default=defaults.get(CONF_THERMAL_CYCLING_ENABLED, False),
            ): bool,
            vol.Required(
                CONF_STOP_OFFSET_C,
                default=defaults.get(
                    CONF_STOP_OFFSET_C,
                    defaults.get(CONF_UPPER_OFFSET_C, DEFAULT_STOP_OFFSET_C),
                ),
            ): vol.All(vol.Coerce(float), vol.Range(min=0.5, max=15)),
            vol.Required(
                CONF_START_OFFSET_C,
                default=defaults.get(
                    CONF_START_OFFSET_C,
                    defaults.get(CONF_LOWER_OFFSET_C, DEFAULT_START_OFFSET_C),
                ),
            ): vol.All(vol.Coerce(float), vol.Range(min=0.5, max=15)),
            vol.Required(
                CONF_ACTIVE_CONTROL_ENABLED,
                default=defaults.get(CONF_ACTIVE_CONTROL_ENABLED, False),
            ): bool,
            vol.Required(
                CONF_MINIMUM_ON_CYCLE_MINUTES,
                default=defaults.get(
                    CONF_MINIMUM_ON_CYCLE_MINUTES,
                    DEFAULT_MINIMUM_ON_CYCLE_MINUTES,
                ),
            ): vol.All(vol.Coerce(float), vol.Range(min=0, max=240)),
            vol.Required(
                CONF_MINIMUM_OFF_CYCLE_MINUTES,
                default=defaults.get(
                    CONF_MINIMUM_OFF_CYCLE_MINUTES,
                    DEFAULT_MINIMUM_OFF_CYCLE_MINUTES,
                ),
            ): vol.All(vol.Coerce(float), vol.Range(min=0, max=240)),
            vol.Required(
                CONF_FAILED_START_RETRY_MINUTES,
                default=defaults.get(
                    CONF_FAILED_START_RETRY_MINUTES,
                    DEFAULT_FAILED_START_RETRY_MINUTES,
                ),
            ): vol.All(vol.Coerce(float), vol.Range(min=0.25, max=30)),
            vol.Required(
                CONF_EARLY_RECOVERY_ENABLED,
                default=defaults.get(CONF_EARLY_RECOVERY_ENABLED, True),
            ): bool,
            vol.Required(
                CONF_RECOVERY_SETPOINT_C,
                default=defaults.get(
                    CONF_RECOVERY_SETPOINT_C, DEFAULT_RECOVERY_SETPOINT_C
                ),
            ): vol.All(vol.Coerce(float), vol.Range(min=5, max=35)),
            vol.Required(
                CONF_RECOVERY_TIMEOUT_S,
                default=defaults.get(
                    CONF_RECOVERY_TIMEOUT_S, DEFAULT_RECOVERY_TIMEOUT_S
                ),
            ): vol.All(vol.Coerce(float), vol.Range(min=30, max=600)),
            vol.Required(
                CONF_RECOVERY_MIN_RISE_C,
                default=defaults.get(
                    CONF_RECOVERY_MIN_RISE_C, DEFAULT_RECOVERY_MIN_RISE_C
                ),
            ): vol.All(vol.Coerce(float), vol.Range(min=1, max=30)),
            vol.Required(
                CONF_CLIMATE_ENTITY_ID,
                default=defaults.get(
                    CONF_CLIMATE_ENTITY_ID, DEFAULT_CLIMATE_ENTITY_ID
                ),
            ): str,
            vol.Required(
                CONF_ROOM_TEMPERATURE_ENTITY_ID,
                default=defaults.get(
                    CONF_ROOM_TEMPERATURE_ENTITY_ID,
                    DEFAULT_ROOM_TEMPERATURE_ENTITY_ID,
                ),
            ): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="sensor")
            ),
            vol.Required(
                CONF_USE_FUSED_TEMPERATURE,
                default=defaults.get(
                    CONF_USE_FUSED_TEMPERATURE,
                    DEFAULT_USE_FUSED_TEMPERATURE,
                ),
            ): bool,
            vol.Required(
                CONF_FUSED_TEMPERATURE_ENTITIES,
                default=defaults.get(
                    CONF_FUSED_TEMPERATURE_ENTITIES,
                    list(DEFAULT_FUSED_TEMPERATURE_ENTITIES),
                ),
            ): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="sensor", multiple=True)
            ),
            vol.Required(
                CONF_OUTDOOR_TEMPERATURE_ENTITY_ID,
                default=defaults.get(
                    CONF_OUTDOOR_TEMPERATURE_ENTITY_ID,
                    DEFAULT_OUTDOOR_TEMPERATURE_ENTITY_ID,
                ),
            ): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="sensor")
            ),
            vol.Optional(
                CONF_ELECTRIC_HEATER_1_ENTITY_ID,
                default=defaults.get(
                    CONF_ELECTRIC_HEATER_1_ENTITY_ID,
                    DEFAULT_ELECTRIC_HEATER_1_ENTITY_ID,
                ),
            ): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="switch")
            ),
            vol.Optional(
                CONF_ELECTRIC_HEATER_2_ENTITY_ID,
                description={
                    "suggested_value": defaults.get(
                        CONF_ELECTRIC_HEATER_2_ENTITY_ID,
                        DEFAULT_ELECTRIC_HEATER_2_ENTITY_ID,
                    ) or None
                },
            ): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="switch")
            ),
        }
    )


class ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Create an Afterburner Helper v2 config entry."""

    VERSION = 2

    async def async_step_user(self, user_input: dict[str, Any] | None = None):
        if user_input is not None:
            await self.async_set_unique_id(user_input[CONF_MQTT_TOPIC_PREFIX])
            self._abort_if_unique_id_configured()
            return self.async_create_entry(
                title=user_input[CONF_DEVICE_NAME],
                data=user_input,
            )
        return self.async_show_form(step_id="user", data_schema=_initial_schema())

    @staticmethod
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> config_entries.OptionsFlow:
        return OptionsFlow()


class OptionsFlow(config_entries.OptionsFlow):
    """Edit the canonical fuel and active-controller settings."""

    async def async_step_init(self, user_input: dict[str, Any] | None = None):
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)
        defaults = {**self.config_entry.data, **self.config_entry.options}
        return self.async_show_form(
            step_id="init",
            data_schema=_options_schema(defaults),
        )
