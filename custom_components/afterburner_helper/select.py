"""Priority selector for staged heat sources."""

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import CONF_DEVICE_NAME, DEFAULT_DEVICE_NAME, DOMAIN, PRIORITY_OPTIONS
from .coordinator import AfterburnerCoordinator


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    coordinator: AfterburnerCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([
        HeatPrioritySelect(entry, coordinator.heat_group),
        AfterburnerSettingSelect(
            entry,
            coordinator.settings_hub,
            "ThermostatMethod",
            "Thermostat control method",
            {
                "Standard heater control": 0,
                "Narrow hysteresis": 1,
                "Managed pump frequency": 2,
                "External thermostat contact": 3,
                "Automatic stop/start": 4,
            },
            "mdi:thermostat-cog",
        ),
        AfterburnerSettingSelect(
            entry,
            coordinator.settings_hub,
            "FanSensor",
            "Fan sensor type",
            {"SN-1": 1, "SN-2": 2},
            "mdi:fan-auto",
        ),
        AfterburnerSettingSelect(
            entry,
            coordinator.settings_hub,
            "SystemVoltage",
            "System voltage",
            {"12 V": 12, "24 V": 24},
            "mdi:car-battery",
        ),
    ])


class HeatPrioritySelect(SelectEntity):
    _attr_has_entity_name = False
    _attr_name = "Afterburner Heat Source Priority"
    _attr_icon = "mdi:format-list-numbered"
    _attr_options = list(PRIORITY_OPTIONS)

    def __init__(self, entry, manager) -> None:
        self.manager = manager
        self._attr_unique_id = f"{entry.entry_id}_heat_source_priority"
        self._attr_device_info = DeviceInfo(identifiers={(DOMAIN, f"{entry.entry_id}_heat_group")}, name="Climate Control", manufacturer="Afterburner Helper", model="Staged Heat Group")

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(self.manager.async_add_listener(self._updated))

    @callback
    def _updated(self):
        self.async_write_ha_state()

    @property
    def current_option(self):
        return self.manager.priority

    async def async_select_option(self, option: str) -> None:
        await self.manager.async_set_priority(option)


class AfterburnerSettingSelect(SelectEntity):
    """Persistent enumerated Afterburner setting."""

    _attr_has_entity_name = True

    def __init__(self, entry, hub, key: str, name: str, options: dict[str, int], icon: str) -> None:
        self.hub = hub
        self.key = key
        self.option_values = options
        self._attr_name = name
        self._attr_options = list(options)
        self._attr_icon = icon
        self._attr_unique_id = f"{hub.topic_prefix}_setting_{key.lower()}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, hub.topic_prefix)},
            name=entry.data.get(CONF_DEVICE_NAME, DEFAULT_DEVICE_NAME),
            manufacturer="Afterburner",
            model="Diesel Heater Controller",
        )

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(self.hub.async_add_listener(self._updated))

    @property
    def available(self) -> bool:
        return self.key in self.hub.values

    @property
    def current_option(self):
        try:
            value = int(float(self.hub.values[self.key]))
        except (KeyError, TypeError, ValueError):
            return None
        return next((label for label, raw in self.option_values.items() if raw == value), None)

    async def async_select_option(self, option: str) -> None:
        await self.hub.async_publish(self.key, self.option_values[option])

    @callback
    def _updated(self):
        self.async_write_ha_state()
