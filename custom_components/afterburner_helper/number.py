"""User-adjustable inputs for Afterburner Helper v2."""

from __future__ import annotations

from dataclasses import dataclass

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    CONF_DEVICE_NAME,
    CONF_DIESEL_PRICE_PER_LITRE,
    CONF_MQTT_TOPIC_PREFIX,
    DEFAULT_DEVICE_NAME,
    DEFAULT_DIESEL_PRICE_PER_LITRE,
    DOMAIN,
)
from .coordinator import AfterburnerCoordinator
from .settings import AfterburnerSettingsHub


@dataclass(frozen=True, kw_only=True)
class SettingDescription:
    key: str
    name: str
    minimum: float
    maximum: float
    step: float
    unit: str | None = None
    icon: str | None = None


SETTING_DESCRIPTIONS = (
    SettingDescription(key="PumpMin", name="Minimum pump frequency", minimum=1.0, maximum=10.0, step=0.1, unit="Hz", icon="mdi:sine-wave"),
    SettingDescription(key="FanMin", name="Minimum fan speed", minimum=500, maximum=5000, step=10, unit="RPM", icon="mdi:fan"),
    SettingDescription(key="PumpMax", name="Maximum pump frequency", minimum=1.0, maximum=10.0, step=0.1, unit="Hz", icon="mdi:sine-wave"),
    SettingDescription(key="FanMax", name="Maximum fan speed", minimum=500, maximum=5000, step=10, unit="RPM", icon="mdi:fan"),
    SettingDescription(key="PumpCal", name="Pump volume per stroke", minimum=0.001, maximum=1.0, step=0.001, unit="mL", icon="mdi:eyedropper"),
    SettingDescription(key="ThermostatWindow", name="Thermostat window", minimum=0.2, maximum=10.0, step=0.1, unit="°C", icon="mdi:thermometer-lines"),
    SettingDescription(key="TempOffset", name="Temperature 1 offset", minimum=-10.0, maximum=10.0, step=0.1, unit="°C", icon="mdi:thermometer-alert"),
    SettingDescription(key="Temp2Offset", name="Temperature 2 offset", minimum=-10.0, maximum=10.0, step=0.1, unit="°C", icon="mdi:thermometer-alert"),
    SettingDescription(key="Temp3Offset", name="Temperature 3 offset", minimum=-10.0, maximum=10.0, step=0.1, unit="°C", icon="mdi:thermometer-alert"),
    SettingDescription(key="Temp4Offset", name="Temperature 4 offset", minimum=-10.0, maximum=10.0, step=0.1, unit="°C", icon="mdi:thermometer-alert"),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: AfterburnerCoordinator = hass.data[DOMAIN][entry.entry_id]
    hub = coordinator.settings_hub
    async_add_entities(
        [DieselPriceNumber(hass, entry)]
        + [AfterburnerSettingNumber(entry, hub, description) for description in SETTING_DESCRIPTIONS]
    )


class AfterburnerSettingNumber(NumberEntity):
    """A persistent numeric setting implemented by Afterburner MQTT commands."""

    _attr_has_entity_name = True
    _attr_mode = NumberMode.BOX

    def __init__(self, entry: ConfigEntry, hub: AfterburnerSettingsHub, description: SettingDescription) -> None:
        self.entry = entry
        self.hub = hub
        self.description = description
        self._attr_name = description.name
        self._attr_unique_id = f"{hub.topic_prefix}_setting_{description.key.lower()}"
        self._attr_native_min_value = description.minimum
        self._attr_native_max_value = description.maximum
        self._attr_native_step = description.step
        self._attr_native_unit_of_measurement = description.unit
        self._attr_icon = description.icon
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, hub.topic_prefix)},
            name=entry.data.get(CONF_DEVICE_NAME, DEFAULT_DEVICE_NAME),
            manufacturer="Afterburner",
            model="Diesel Heater Controller",
        )

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(self.hub.async_add_listener(self._settings_updated))

    @property
    def available(self) -> bool:
        return self.description.key in self.hub.values

    @property
    def native_value(self) -> float | None:
        value = self.hub.values.get(self.description.key)
        try:
            return float(value) if value is not None else None
        except (TypeError, ValueError):
            return None

    async def async_set_native_value(self, value: float) -> None:
        await self.hub.async_publish(self.description.key, value)

    @callback
    def _settings_updated(self) -> None:
        self.async_write_ha_state()


class DieselPriceNumber(NumberEntity):
    """Persistent manually entered diesel price used by every cost sensor."""

    _attr_has_entity_name = True
    _attr_name = "Diesel price per litre"
    _attr_icon = "mdi:currency-usd"
    _attr_mode = NumberMode.BOX
    _attr_native_min_value = 0.0
    _attr_native_max_value = 5.0
    _attr_native_step = 0.001
    _attr_native_unit_of_measurement = "CAD/L"

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.hass = hass
        self.entry = entry
        self._attr_unique_id = f"{entry.entry_id}_v2_diesel_price_per_litre"
        topic = entry.data.get(CONF_MQTT_TOPIC_PREFIX, "Afterburner")
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, topic)},
            name=entry.data.get(CONF_DEVICE_NAME, DEFAULT_DEVICE_NAME),
            manufacturer="Afterburner",
            model="Diesel Heater Controller",
        )

    @property
    def native_value(self) -> float:
        return float(
            self.entry.options.get(
                CONF_DIESEL_PRICE_PER_LITRE,
                self.entry.data.get(
                    CONF_DIESEL_PRICE_PER_LITRE,
                    DEFAULT_DIESEL_PRICE_PER_LITRE,
                ),
            )
        )

    async def async_set_native_value(self, value: float) -> None:
        options = dict(self.entry.options)
        options[CONF_DIESEL_PRICE_PER_LITRE] = round(float(value), 3)
        self.hass.config_entries.async_update_entry(self.entry, options=options)
