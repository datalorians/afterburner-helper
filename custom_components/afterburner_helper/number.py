"""User-adjustable inputs for Afterburner Helper v2."""

from __future__ import annotations

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
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


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    async_add_entities([DieselPriceNumber(hass, entry)])


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
