"""Switch platform for Afterburner Helper integration."""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.switch import SwitchEntity
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
    """Set up the Afterburner switch platform."""
    data = hass.data[DOMAIN][config_entry.entry_id]
    topic_prefix = data["mqtt_topic_prefix"]
    device_name = data["device_name"]

    async_add_entities([AfterburnerFlameoutRecoverySwitch(topic_prefix, device_name, config_entry.entry_id)])


class AfterburnerFlameoutRecoverySwitch(SwitchEntity):
    """Flameout recovery automation switch."""

    _attr_icon = "mdi:fire-alert"

    def __init__(self, topic_prefix: str, device_name: str, entry_id: str) -> None:
        """Initialize the switch."""
        self._topic_prefix = topic_prefix
        self._device_name = device_name
        self._entry_id = entry_id
        self._attr_name = f"{device_name} Flameout Recovery"
        self._attr_unique_id = f"{topic_prefix}_flameout_recovery"
        self._attr_is_on = False

    @property
    def device_info(self) -> DeviceInfo:
        """Return device information."""
        return DeviceInfo(
            identifiers={(DOMAIN, self._topic_prefix)},
            name=self._device_name,
            manufacturer="Afterburner",
            model="Diesel Heater Controller",
        )

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn on flameout recovery."""
        self._attr_is_on = True
        self.async_write_ha_state()
        _LOGGER.info("✓ Flameout recovery ENABLED for %s - Will automatically recover from E-08 errors", self._device_name)
        
        # Send notification
        await self.hass.services.async_call(
            "persistent_notification",
            "create",
            {
                "title": "✓ Flameout Recovery Enabled",
                "message": f"Automatic recovery is now active for {self._device_name}. E-08 errors will trigger automatic restart attempts.",
                "notification_id": "afterburner_recovery_enabled"
            }
        )

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn off flameout recovery."""
        self._attr_is_on = False
        self.async_write_ha_state()
        _LOGGER.info("✗ Flameout recovery DISABLED for %s - No automatic recovery will occur", self._device_name)
        
        # Send notification
        await self.hass.services.async_call(
            "persistent_notification",
            "create",
            {
                "title": "✗ Flameout Recovery Disabled",
                "message": f"Automatic recovery is disabled. E-08 errors will NOT trigger automatic restarts.",
                "notification_id": "afterburner_recovery_disabled"
            }
        )
