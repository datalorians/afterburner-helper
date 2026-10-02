"""Priority selector for staged heat sources."""

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN, PRIORITY_OPTIONS
from .coordinator import AfterburnerCoordinator


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    coordinator: AfterburnerCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([HeatPrioritySelect(entry, coordinator.heat_group)])


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
