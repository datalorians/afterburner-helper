"""Switch platform for Afterburner Helper integration."""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .coordinator import AfterburnerCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the Afterburner switch platform."""
    coordinator: AfterburnerCoordinator = hass.data[DOMAIN][config_entry.entry_id]
    topic_prefix = coordinator.settings_hub.topic_prefix
    device_name = config_entry.title

    async_add_entities([
        AfterburnerFlameoutRecoverySwitch(topic_prefix, device_name, config_entry.entry_id),
        HeatSourceLockoutSwitch(config_entry, coordinator.heat_group, "diesel", "Afterburner Diesel Lockout"),
        HeatSourceLockoutSwitch(config_entry, coordinator.heat_group, "electric_1", "Afterburner Electric Heater 1 Lockout"),
        HeatSourceLockoutSwitch(config_entry, coordinator.heat_group, "electric_2", "Afterburner Electric Heater 2 Lockout"),
        AfterburnerCommandSwitch(config_entry, coordinator.settings_hub, "Thermostat", "Thermostat enable", "mdi:thermostat"),
        AfterburnerCommandSwitch(config_entry, coordinator.settings_hub, "GPout1", "GPIO output 1", "mdi:electric-switch"),
        AfterburnerCommandSwitch(config_entry, coordinator.settings_hub, "GPout2", "GPIO output 2", "mdi:electric-switch"),
    ])


class HeatSourceLockoutSwitch(SwitchEntity):
    """Exclude one source from automatic staging without losing its target."""

    _attr_has_entity_name = False
    _attr_icon = "mdi:lock-outline"

    def __init__(self, entry, manager, source: str, name: str) -> None:
        self.manager = manager
        self.source = source
        self._attr_name = name
        self._attr_unique_id = f"{entry.entry_id}_{source}_lockout"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, f"{entry.entry_id}_heat_group")},
            name="Climate Control",
            manufacturer="Afterburner Helper",
            model="Staged Heat Group",
        )

    @property
    def is_on(self) -> bool:
        return self.manager.lockouts[self.source]

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self.manager.async_set_lockout(self.source, True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self.manager.async_set_lockout(self.source, False)


class AfterburnerCommandSwitch(SwitchEntity):
    """Live controller switch backed by JSONout and an MQTT command."""

    _attr_has_entity_name = True

    def __init__(self, entry, hub, key: str, name: str, icon: str) -> None:
        self.hub = hub
        self.key = key
        self._attr_name = name
        self._attr_icon = icon
        self._attr_unique_id = f"{hub.topic_prefix}_command_switch_{key.lower()}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, hub.topic_prefix)},
            name=entry.title,
            manufacturer="Afterburner",
            model="Diesel Heater Controller",
        )

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(self.hub.async_add_listener(self._updated))

    @property
    def available(self) -> bool:
        return self.key in self.hub.values

    @property
    def is_on(self) -> bool:
        try:
            return bool(int(float(self.hub.values.get(self.key, 0))))
        except (TypeError, ValueError):
            return False

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self.hub.async_publish(self.key, 1, save=False)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self.hub.async_publish(self.key, 0, save=False)

    @callback
    def _updated(self) -> None:
        self.async_write_ha_state()


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
