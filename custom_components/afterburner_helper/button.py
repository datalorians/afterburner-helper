"""Button platform for Afterburner Helper integration."""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.components import mqtt
from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the Afterburner button platform."""
    data = hass.data[DOMAIN][config_entry.entry_id]
    topic_prefix = data["mqtt_topic_prefix"]
    device_name = data["device_name"]

    async_add_entities([
        AfterburnerResetFuelButton(topic_prefix, device_name),
        AfterburnerPrimePumpButton(topic_prefix, device_name),
        AfterburnerTestOnButton(topic_prefix, device_name),
        AfterburnerTestOffButton(topic_prefix, device_name),
    ])


class AfterburnerResetFuelButton(ButtonEntity):
    """Reset fuel usage button."""

    _attr_icon = "mdi:gas-station"

    def __init__(self, topic_prefix: str, device_name: str) -> None:
        """Initialize the button."""
        self._topic_prefix = topic_prefix
        self._device_name = device_name
        self._attr_name = f"{device_name} Reset Fuel Usage"
        self._attr_unique_id = f"{topic_prefix}_reset_fuel_usage"

    @property
    def device_info(self) -> DeviceInfo:
        """Return device information."""
        return DeviceInfo(
            identifiers={(DOMAIN, self._topic_prefix)},
            name=self._device_name,
            manufacturer="Afterburner",
            model="Diesel Heater Controller",
        )

    async def async_press(self) -> None:
        """Press the button."""
        # Publish reset fuel usage command
        topic = f"{self._topic_prefix}/cmd/ResetFuelUsage"
        await mqtt.async_publish(
            self.hass,
            topic,
            "1",
            retain=False,
        )
        _LOGGER.info("Reset fuel usage command sent for %s", self._device_name)


class AfterburnerPrimePumpButton(ButtonEntity):
    """Prime pump button."""

    _attr_icon = "mdi:pump"

    def __init__(self, topic_prefix: str, device_name: str) -> None:
        """Initialize the button."""
        self._topic_prefix = topic_prefix
        self._device_name = device_name
        self._attr_name = f"{device_name} Prime Pump"
        self._attr_unique_id = f"{topic_prefix}_prime_pump"

    @property
    def device_info(self) -> DeviceInfo:
        """Return device information."""
        return DeviceInfo(
            identifiers={(DOMAIN, self._topic_prefix)},
            name=self._device_name,
            manufacturer="Afterburner",
            model="Diesel Heater Controller",
        )

    async def async_press(self) -> None:
        """Press the button."""
        # Publish prime pump command
        topic = f"{self._topic_prefix}/cmd/PumpPrime"
        await mqtt.async_publish(
            self.hass,
            topic,
            "1",
            retain=False,
        )
        _LOGGER.info("Prime pump command sent for %s", self._device_name)


class AfterburnerTestOnButton(ButtonEntity):
    """Test button to turn heater ON."""

    _attr_icon = "mdi:power-on"

    def __init__(self, topic_prefix: str, device_name: str) -> None:
        """Initialize the button."""
        self._topic_prefix = topic_prefix
        self._device_name = device_name
        self._attr_name = f"{device_name} Test ON"
        self._attr_unique_id = f"{topic_prefix}_test_on"

    @property
    def device_info(self) -> DeviceInfo:
        """Return device information."""
        return DeviceInfo(
            identifiers={(DOMAIN, self._topic_prefix)},
            name=self._device_name,
            manufacturer="Afterburner",
            model="Diesel Heater Controller",
        )

    async def async_press(self) -> None:
        """Turn heater on via climate entity."""
        await self.hass.services.async_call(
            "climate",
            "set_hvac_mode",
            {
                "entity_id": "climate.afterburner",
                "hvac_mode": "heat"
            },
            blocking=True
        )
        _LOGGER.info("Test button: Heater ON command sent for %s", self._device_name)


class AfterburnerTestOffButton(ButtonEntity):
    """Test button to turn heater OFF."""

    _attr_icon = "mdi:power-off"

    def __init__(self, topic_prefix: str, device_name: str) -> None:
        """Initialize the button."""
        self._topic_prefix = topic_prefix
        self._device_name = device_name
        self._attr_name = f"{device_name} Test OFF"
        self._attr_unique_id = f"{topic_prefix}_test_off"

    @property
    def device_info(self) -> DeviceInfo:
        """Return device information."""
        return DeviceInfo(
            identifiers={(DOMAIN, self._topic_prefix)},
            name=self._device_name,
            manufacturer="Afterburner",
            model="Diesel Heater Controller",
        )

    async def async_press(self) -> None:
        """Turn heater off via climate entity."""
        await self.hass.services.async_call(
            "climate",
            "set_hvac_mode",
            {
                "entity_id": "climate.afterburner",
                "hvac_mode": "off"
            },
            blocking=True
        )
        _LOGGER.info("Test button: Heater OFF command sent for %s", self._device_name)