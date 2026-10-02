"""Master and member climate controls for the staged heat group."""

from __future__ import annotations

from homeassistant.components.climate import ClimateEntity, ClimateEntityFeature, HVACMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfTemperature
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .coordinator import AfterburnerCoordinator
from .staging import HeatGroupManager


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    coordinator: AfterburnerCoordinator = hass.data[DOMAIN][entry.entry_id]
    manager = coordinator.heat_group
    async_add_entities([
        HeatGroupClimate(entry, manager),
        HeatMemberClimate(entry, manager, "diesel", "Afterburner Diesel Heater"),
        HeatMemberClimate(entry, manager, "electric_1", "Afterburner Electric Heater 1"),
        HeatMemberClimate(entry, manager, "electric_2", "Afterburner Electric Heater 2"),
    ])


class _BaseHeatClimate(ClimateEntity):
    _attr_has_entity_name = False
    _attr_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_supported_features = ClimateEntityFeature.TARGET_TEMPERATURE
    _attr_min_temp = 5
    _attr_max_temp = 35
    _attr_target_temperature_step = 0.5

    def __init__(self, entry: ConfigEntry, manager: HeatGroupManager) -> None:
        self.manager = manager
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, f"{entry.entry_id}_heat_group")},
            name="Climate Control",
            manufacturer="Afterburner Helper",
            model="Staged Heat Group",
        )

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(self.manager.async_add_listener(self._updated))

    @callback
    def _updated(self) -> None:
        self.async_write_ha_state()

    @property
    def current_temperature(self):
        return self.manager.room_temperature


class HeatGroupClimate(_BaseHeatClimate):
    _attr_name = "Afterburner Heat Group"
    _attr_hvac_modes = [HVACMode.OFF, HVACMode.HEAT]

    def __init__(self, entry: ConfigEntry, manager: HeatGroupManager) -> None:
        super().__init__(entry, manager)
        self._attr_unique_id = f"{entry.entry_id}_master_climate"

    @property
    def hvac_mode(self):
        return HVACMode.HEAT if self.manager.master_enabled else HVACMode.OFF

    @property
    def hvac_action(self):
        return "heating" if self.manager.snapshot().active_sources else "idle"

    @property
    def target_temperature(self):
        return self.manager.target_temperature

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        await self.manager.async_set_master_enabled(hvac_mode == HVACMode.HEAT)

    async def async_set_temperature(self, **kwargs) -> None:
        if (temperature := kwargs.get("temperature")) is not None:
            await self.manager.async_set_target(float(temperature))


class HeatMemberClimate(_BaseHeatClimate):
    _attr_hvac_modes = [HVACMode.OFF, HVACMode.HEAT, HVACMode.AUTO]

    def __init__(self, entry: ConfigEntry, manager: HeatGroupManager, source: str, name: str) -> None:
        super().__init__(entry, manager)
        self.source = source
        self._attr_name = name
        self._attr_unique_id = f"{entry.entry_id}_{source}_climate"

    @property
    def available(self):
        return self.source == "diesel" or bool(self.manager.electric_entities.get(self.source))

    @property
    def hvac_mode(self):
        return HVACMode(self.manager.member_modes[self.source])

    @property
    def hvac_action(self):
        return "heating" if self.source in self.manager.snapshot().active_sources else "idle"

    @property
    def target_temperature(self):
        return self.manager.member_targets[self.source]

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        await self.manager.async_set_member_mode(self.source, hvac_mode.value)

    async def async_set_temperature(self, **kwargs) -> None:
        if (temperature := kwargs.get("temperature")) is not None:
            await self.manager.async_set_member_target(self.source, float(temperature))
            await self.manager.async_set_member_mode(self.source, "heat")
