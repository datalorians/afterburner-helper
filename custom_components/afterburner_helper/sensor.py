"""Canonical and diagnostic sensors for Afterburner Helper v2."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity, SensorStateClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    PERCENTAGE,
    UnitOfTemperature,
    UnitOfTime,
    UnitOfVolume,
    UnitOfVolumeFlowRate,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import CONF_DEVICE_NAME, CONF_MQTT_TOPIC_PREFIX, DEFAULT_DEVICE_NAME, DOMAIN
from .coordinator import AfterburnerCoordinator, AfterburnerData
from .staging import HeatGroupManager


@dataclass(frozen=True, kw_only=True)
class Description:
    key: str
    name: str
    value: Callable[[AfterburnerData], Any]
    unit: str | None = None
    device_class: SensorDeviceClass | None = None
    state_class: SensorStateClass | None = None
    icon: str | None = None


DESCRIPTIONS = (
    Description(
        key="diesel_price_per_litre",
        name="Diesel price per litre",
        value=lambda data: round(data.costs.price_per_litre, 3),
        unit="CAD/L",
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:currency-usd",
    ),
    Description(
        key="fuel_remaining_l",
        name="Fuel remaining",
        value=lambda data: round(data.fuel.remaining_l, 3),
        unit=UnitOfVolume.LITERS,
        device_class=SensorDeviceClass.VOLUME,
    ),
    Description(
        key="fuel_remaining_percent",
        name="Fuel remaining percent",
        value=lambda data: round(data.fuel.remaining_percent, 2),
        unit=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:barrel",
    ),
    Description(
        key="fuel_rate",
        name="Fuel rate",
        value=lambda data: round(data.fuel.current_rate_lph, 4),
        unit=UnitOfVolumeFlowRate.LITERS_PER_HOUR,
        device_class=SensorDeviceClass.VOLUME_FLOW_RATE,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    Description(
        key="runtime_current_rate",
        name="Fuel runtime at current rate",
        value=lambda data: (
            round(data.fuel.runtime_at_current_rate_h, 1)
            if data.fuel.runtime_at_current_rate_h is not None
            else None
        ),
        unit=UnitOfTime.HOURS,
        device_class=SensorDeviceClass.DURATION,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    Description(
        key="runtime_maximum_rate",
        name="Fuel runtime at maximum rate",
        value=lambda data: round(data.fuel.runtime_at_maximum_rate_h, 1),
        unit=UnitOfTime.HOURS,
        device_class=SensorDeviceClass.DURATION,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    Description(
        key="fuel_cost_per_hour",
        name="Fuel cost per hour",
        value=lambda data: round(data.costs.current_per_hour, 2),
        unit="CAD/h",
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:cash-clock",
    ),
    Description(
        key="fuel_cost_per_day",
        name="Fuel cost per 24h at current output",
        value=lambda data: round(data.costs.current_per_24h, 2),
        unit="CAD",
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:calendar-today",
    ),
    Description(
        key="fuel_cost_per_month",
        name="Fuel cost per 30d at current output",
        value=lambda data: round(data.costs.current_per_30d, 2),
        unit="CAD",
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:calendar-month",
    ),
    Description(
        key="fuel_cost_maximum_per_hour",
        name="Fuel cost per hour at maximum output",
        value=lambda data: round(data.costs.maximum_per_hour, 2),
        unit="CAD/h",
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:cash-fast",
    ),
    Description(
        key="fuel_cost_maximum_per_day",
        name="Fuel cost per 24h at maximum output",
        value=lambda data: round(data.costs.maximum_per_24h, 2),
        unit="CAD",
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:calendar-alert",
    ),
    Description(
        key="fuel_cost_maximum_per_month",
        name="Fuel cost per 30d at maximum output",
        value=lambda data: round(data.costs.maximum_per_30d, 2),
        unit="CAD",
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:calendar-star",
    ),
    Description(
        key="fuel_cost_used",
        name="Fuel cost this tank interval",
        value=lambda data: round(data.costs.used_since_reset, 2),
        unit="CAD",
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:cash-minus",
    ),
    Description(
        key="fuel_cost_recorded_total",
        name="Fuel cost recorded total",
        value=lambda data: round(data.costs.recorded_total, 2),
        unit="CAD",
        device_class=SensorDeviceClass.MONETARY,
        # Home Assistant permits monetary sensors to use TOTAL, not
        # TOTAL_INCREASING.  The ledger itself remains monotonic; TOTAL keeps
        # Recorder statistics valid without changing its historical meaning.
        state_class=SensorStateClass.TOTAL,
        icon="mdi:cash-multiple",
    ),
    Description(
        key="fuel_value_remaining",
        name="Fuel value remaining",
        value=lambda data: round(data.costs.remaining_value, 2),
        unit="CAD",
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:cash-check",
    ),
    Description(
        key="fuel_full_tank_cost",
        name="Full tank cost",
        value=lambda data: round(data.costs.full_tank_cost, 2),
        unit="CAD",
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:gas-station",
    ),
    Description(
        key="control_state",
        name="Control state",
        value=lambda data: data.cycle_decision.mode.value,
        icon="mdi:state-machine",
    ),
    Description(
        key="control_recommendation",
        name="Control recommendation",
        value=lambda data: data.cycle_decision.action.value,
        icon="mdi:comment-alert-outline",
    ),
    Description(
        key="recovery_state",
        name="Recovery state",
        value=lambda data: data.recovery_decision.action.value,
        icon="mdi:fire-circle",
    ),
    Description(
        key="flameout_warning",
        name="Flameout warning",
        value=lambda data: data.warnings[-1].code.value if data.warnings else "clear",
        icon="mdi:fire-alert",
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: AfterburnerCoordinator = hass.data[DOMAIN][entry.entry_id]
    entities: list[SensorEntity] = [
        AfterburnerSensor(coordinator, entry, description)
        for description in DESCRIPTIONS
    ]
    entities.append(FusedRoomTemperatureSensor(entry, coordinator.heat_group))
    async_add_entities(entities)


class AfterburnerSensor(CoordinatorEntity[AfterburnerCoordinator], SensorEntity):
    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: AfterburnerCoordinator,
        entry: ConfigEntry,
        description: Description,
    ) -> None:
        super().__init__(coordinator)
        self.description = description
        self._attr_name = description.name
        self._attr_unique_id = f"{entry.entry_id}_v2_{description.key}"
        self._attr_native_unit_of_measurement = description.unit
        self._attr_device_class = description.device_class
        self._attr_state_class = description.state_class
        self._attr_icon = description.icon
        topic = entry.data.get(CONF_MQTT_TOPIC_PREFIX, "Afterburner")
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, topic)},
            name=entry.data.get(CONF_DEVICE_NAME, DEFAULT_DEVICE_NAME),
            manufacturer="Afterburner",
            model="Diesel Heater Controller",
        )

    @property
    def native_value(self) -> Any:
        return self.description.value(self.coordinator.data)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        if self.description.key == "control_recommendation":
            return {
                "reason": self.coordinator.data.cycle_decision.reason,
                "active_control_enabled": self.coordinator.data.active_control_enabled,
                "last_command": self.coordinator.data.last_command,
                "last_command_at": self.coordinator.data.last_command_at,
                "decision_history": list(self.coordinator.data.decision_history),
            }
        if self.description.key == "recovery_state":
            return {
                "reason": self.coordinator.data.recovery_decision.reason,
                "target_setpoint_c": self.coordinator.data.recovery_decision.target_setpoint_c,
            }
        if self.description.key == "flameout_warning":
            return {
                "active_warnings": [
                    warning.code.value for warning in self.coordinator.data.warnings
                ],
                "details": [
                    warning.detail for warning in self.coordinator.data.warnings
                ],
            }
        if self.description.key == "fuel_remaining_l":
            return {
                "raw_remaining_l": round(
                    self.coordinator.data.fuel.raw_remaining_l, 3
                ),
                "out_of_range": self.coordinator.data.fuel.out_of_range,
                "corrected_used_l": round(
                    self.coordinator.data.fuel.corrected_used_l, 3
                ),
            }
        return None


class FusedRoomTemperatureSensor(SensorEntity):
    """Virtual room temperature formed from configured HA sensors."""

    _attr_has_entity_name = True
    _attr_name = "Fused room temperature"
    _attr_icon = "mdi:thermometer-lines"
    _attr_device_class = SensorDeviceClass.TEMPERATURE
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS

    def __init__(self, entry: ConfigEntry, manager: HeatGroupManager) -> None:
        self.manager = manager
        self._attr_unique_id = f"{entry.entry_id}_fused_room_temperature"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, f"{entry.entry_id}_heat_group")},
            name="Climate Control",
            manufacturer="Afterburner Helper",
            model="Staged Heat Group",
        )

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(self.manager.async_add_listener(self._updated))

    def _updated(self) -> None:
        self.async_write_ha_state()

    @property
    def available(self) -> bool:
        return self.manager.fused_temperature is not None

    @property
    def native_value(self) -> float | None:
        return self.manager.fused_temperature

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        values = self.manager.fused_temperature_values
        return {
            "method": "arithmetic_mean",
            "used_by_master_climate": self.manager.use_fused_temperature,
            "configured_sources": list(self.manager.fused_temperature_entities),
            "active_sources": values,
            "unavailable_sources": [
                entity_id
                for entity_id in self.manager.fused_temperature_entities
                if entity_id not in values
            ],
            "active_source_count": len(values),
        }
