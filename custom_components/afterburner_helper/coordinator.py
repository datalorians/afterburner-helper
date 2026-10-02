"""Event-driven coordinator and bounded actuator for Afterburner Helper v2."""

from __future__ import annotations

import asyncio
import logging
from collections import deque
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import ATTR_ENTITY_ID, EVENT_CALL_SERVICE
from homeassistant.core import Context, Event, HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.event import async_track_state_change_event, async_track_time_interval
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import (
    CONF_ACTIVE_CONTROL_ENABLED,
    CONF_CLIMATE_ENTITY_ID,
    CONF_DIESEL_PRICE_PER_LITRE,
    CONF_EARLY_RECOVERY_ENABLED,
    CONF_LOWER_OFFSET_C,
    CONF_MAXIMUM_PUMP_HZ,
    CONF_MINIMUM_PUMP_HZ,
    CONF_PUMP_ML_PER_STROKE,
    CONF_RECOVERY_MIN_RISE_C,
    CONF_RECOVERY_SETPOINT_C,
    CONF_RECOVERY_TIMEOUT_S,
    CONF_START_OFFSET_C,
    CONF_STOP_OFFSET_C,
    CONF_TANK_CAPACITY,
    CONF_THERMAL_CYCLING_ENABLED,
    CONF_UPPER_OFFSET_C,
    CONF_USAGE_CORRECTION_FACTOR,
    COORDINATOR_INTERVAL,
    DEFAULT_CLIMATE_ENTITY_ID,
    DEFAULT_DIESEL_PRICE_PER_LITRE,
    DEFAULT_LOWER_OFFSET_C,
    DEFAULT_MAXIMUM_PUMP_HZ,
    DEFAULT_MINIMUM_PUMP_HZ,
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
    SOURCE_ENTITIES,
)
from .control import (
    ControlAction,
    ControlDecision,
    CycleMode,
    EarlyRecoveryController,
    FlameoutDetector,
    FlameoutWarning,
    RecoveryAction,
    RecoveryConfig,
    RecoveryDecision,
    RecoveryMemory,
    Telemetry,
    ThermalCycleConfig,
    ThermalCycleController,
    ThermalCycleMemory,
)
from .fuel import (
    FuelConfig,
    FuelCostLedger,
    FuelCostSnapshot,
    FuelSnapshot,
    calculate_fuel,
    calculate_fuel_costs,
)

_LOGGER = logging.getLogger(__name__)
STORAGE_VERSION = 1


@dataclass(frozen=True, slots=True)
class AfterburnerData:
    telemetry: Telemetry
    fuel: FuelSnapshot
    costs: FuelCostSnapshot
    warnings: tuple[FlameoutWarning, ...]
    cycle_decision: ControlDecision
    recovery_decision: RecoveryDecision
    active_control_enabled: bool
    last_command: str | None
    last_command_at: str | None
    decision_history: tuple[str, ...]


def _float_state(hass: HomeAssistant, entity_id: str) -> float | None:
    state = hass.states.get(entity_id)
    if state is None or state.state in {"unknown", "unavailable", "none", ""}:
        return None
    try:
        return float(state.state)
    except (TypeError, ValueError):
        return None


def _text_state(hass: HomeAssistant, entity_id: str) -> str:
    state = hass.states.get(entity_id)
    return state.state if state is not None else "unavailable"


def _float_attribute(
    hass: HomeAssistant,
    entity_id: str,
    attribute: str,
) -> float | None:
    state = hass.states.get(entity_id)
    if state is None:
        return None
    try:
        return float(state.attributes[attribute])
    except (KeyError, TypeError, ValueError):
        return None


def _option(entry: ConfigEntry, key: str, default: Any) -> Any:
    """Options override initial data; this removes the old two-source bug."""
    return entry.options.get(key, entry.data.get(key, default))


def _migrated_option(
    entry: ConfigEntry,
    key: str,
    legacy_key: str,
    default: Any,
) -> Any:
    """Read the canonical key, falling back to the pre-v2.2 option name."""
    if key in entry.options or key in entry.data:
        return _option(entry, key, default)
    return _option(entry, legacy_key, default)


class AfterburnerCoordinator(DataUpdateCoordinator[AfterburnerData]):
    """Build coherent telemetry and execute explicitly enabled bounded actions."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=DOMAIN,
            update_interval=None,
        )
        self.entry = entry
        self._detector = FlameoutDetector()
        self._cycle = ThermalCycleController(self._cycle_config())
        self._recovery = EarlyRecoveryController(self._recovery_config())
        self._unsubscribers: list[Any] = []
        self._actuation_lock = asyncio.Lock()
        self._store = Store(
            hass,
            STORAGE_VERSION,
            f"{DOMAIN}.{entry.entry_id}.controller_state",
        )
        self._last_command: str | None = None
        self._last_command_at: str | None = None
        self._decision_history: deque[str] = deque(maxlen=50)
        self._owned_service_contexts: deque[str] = deque(maxlen=20)
        self._cost_ledger = FuelCostLedger()
        self.heat_group = None

    @property
    def active_control_enabled(self) -> bool:
        return bool(_option(self.entry, CONF_ACTIVE_CONTROL_ENABLED, False))

    @property
    def climate_entity_id(self) -> str:
        return str(
            _option(self.entry, CONF_CLIMATE_ENTITY_ID, DEFAULT_CLIMATE_ENTITY_ID)
        )

    def _cycle_config(self) -> ThermalCycleConfig:
        return ThermalCycleConfig(
            enabled=bool(
                _option(self.entry, CONF_THERMAL_CYCLING_ENABLED, False)
            ),
            stop_offset_c=float(
                _migrated_option(
                    self.entry,
                    CONF_STOP_OFFSET_C,
                    CONF_UPPER_OFFSET_C,
                    DEFAULT_STOP_OFFSET_C,
                )
            ),
            start_offset_c=float(
                _migrated_option(
                    self.entry,
                    CONF_START_OFFSET_C,
                    CONF_LOWER_OFFSET_C,
                    DEFAULT_START_OFFSET_C,
                )
            ),
            minimum_pump_hz=float(
                _option(
                    self.entry,
                    CONF_MINIMUM_PUMP_HZ,
                    DEFAULT_MINIMUM_PUMP_HZ,
                )
            ),
        )

    def _recovery_config(self) -> RecoveryConfig:
        return RecoveryConfig(
            enabled=bool(_option(self.entry, CONF_EARLY_RECOVERY_ENABLED, True)),
            boost_setpoint_c=float(
                _option(
                    self.entry,
                    CONF_RECOVERY_SETPOINT_C,
                    DEFAULT_RECOVERY_SETPOINT_C,
                )
            ),
            response_timeout_s=float(
                _option(
                    self.entry,
                    CONF_RECOVERY_TIMEOUT_S,
                    DEFAULT_RECOVERY_TIMEOUT_S,
                )
            ),
            required_temperature_rise_c=float(
                _option(
                    self.entry,
                    CONF_RECOVERY_MIN_RISE_C,
                    DEFAULT_RECOVERY_MIN_RISE_C,
                )
            ),
        )

    async def async_initialize(self) -> None:
        """Restore only controller-owned state needed across HA restarts."""
        stored = await self._store.async_load()
        if not stored:
            return
        try:
            cycle_data = stored.get("cycle", {})
            cycle_memory = ThermalCycleMemory(
                mode=CycleMode(cycle_data.get("mode", CycleMode.DISABLED)),
                auto_stopped=bool(cycle_data.get("auto_stopped", False)),
                auto_stopped_at=cycle_data.get("auto_stopped_at"),
                run_started_at=cycle_data.get("run_started_at"),
                restart_commanded_at=cycle_data.get("restart_commanded_at"),
                manual_stop_latched=bool(
                    cycle_data.get("manual_stop_latched", False)
                ),
                last_setpoint_c=cycle_data.get("last_setpoint_c"),
                lockout_reason=cycle_data.get("lockout_reason"),
                start_times=deque(cycle_data.get("start_times", [])),
            )
            recovery_data = stored.get("recovery", {})
            recovery_memory = RecoveryMemory(
                active=bool(recovery_data.get("active", False)),
                attempted_this_run=bool(
                    recovery_data.get("attempted_this_run", False)
                ),
                started_at=recovery_data.get("started_at"),
                starting_body_c=recovery_data.get("starting_body_c"),
                original_setpoint_c=recovery_data.get("original_setpoint_c"),
                lockout_reason=recovery_data.get("lockout_reason"),
            )
            self._cycle = ThermalCycleController(
                self._cycle_config(),
                cycle_memory,
            )
            self._recovery = EarlyRecoveryController(
                self._recovery_config(),
                recovery_memory,
            )
            self._last_command = stored.get("last_command")
            self._last_command_at = stored.get("last_command_at")
            self._decision_history.extend(stored.get("decision_history", []))
            cost_data = stored.get("fuel_cost", {})
            last_cost_fuel = cost_data.get("last_corrected_fuel_used_l")
            self._cost_ledger = FuelCostLedger(
                used_since_reset=float(cost_data.get("used_since_reset", 0.0)),
                recorded_total=float(cost_data.get("recorded_total", 0.0)),
                last_corrected_fuel_used_l=(
                    float(last_cost_fuel) if last_cost_fuel is not None else None
                ),
            )
        except (TypeError, ValueError) as err:
            _LOGGER.warning("Ignoring invalid stored controller state: %s", err)

    @callback
    def async_start(self) -> None:
        """Subscribe after the first refresh so entities can attach safely."""
        source_entities = set(SOURCE_ENTITIES.values())
        source_entities.add(self.climate_entity_id)
        self._unsubscribers.append(
            async_track_state_change_event(
                self.hass,
                list(source_entities),
                self._source_changed,
            )
        )
        self._unsubscribers.append(
            self.hass.bus.async_listen(
                EVENT_CALL_SERVICE,
                self._service_called,
            )
        )
        self._unsubscribers.append(
            async_track_time_interval(
                self.hass,
                self._periodic_refresh,
                COORDINATOR_INTERVAL,
            )
        )

    @callback
    def async_stop(self) -> None:
        for unsubscribe in self._unsubscribers:
            unsubscribe()
        self._unsubscribers.clear()

    @callback
    def _source_changed(self, event: Event) -> None:
        self.hass.async_create_task(self._async_refresh_and_control())

    @callback
    def _periodic_refresh(self, now: datetime) -> None:
        self.hass.async_create_task(self._async_refresh_and_control())

    @callback
    def _service_called(self, event: Event) -> None:
        """Treat an external climate Off command as a manual-stop override."""
        # The staged heat group is the sole owner of diesel start/stop. Its
        # commands must not be reinterpreted by the retired diesel-only cycle
        # controller as a user manual stop.
        if self.heat_group is not None:
            return
        if event.data.get("domain") != "climate":
            return
        if event.data.get("service") != "set_hvac_mode":
            return
        if event.context.id in self._owned_service_contexts:
            return
        service_data = event.data.get("service_data", {})
        if service_data.get("hvac_mode") != "off":
            return
        if not self._event_targets_climate(event.data, service_data):
            return

        self._cycle.manual_stop()
        self._recovery.manual_stop()
        self._record_command(
            "manual-stop-observed",
            "external climate Off command cancelled automatic restart and recovery",
        )
        self.hass.async_create_task(self._async_save_state())

    def _event_targets_climate(
        self,
        event_data: dict[str, Any],
        service_data: dict[str, Any],
    ) -> bool:
        target = event_data.get("target", {})
        candidates = service_data.get(ATTR_ENTITY_ID, target.get(ATTR_ENTITY_ID, []))
        if isinstance(candidates, str):
            candidates = [candidates]
        return self.climate_entity_id in candidates

    async def _async_refresh_and_control(self) -> None:
        await self.async_request_refresh()
        if self.last_update_success and self.data is not None:
            await self._async_apply_control(self.data)

    async def _async_update_data(self) -> AfterburnerData:
        cycle_state_before = self._persistent_cycle_state()
        telemetry = Telemetry(
            timestamp=datetime.now().timestamp(),
            run_state=_text_state(self.hass, SOURCE_ENTITIES["run_state"]),
            error=_text_state(self.hass, SOURCE_ENTITIES["error_state"]),
            pump_hz=_float_state(self.hass, SOURCE_ENTITIES["pump_hz"]),
            fan_rpm=_float_state(self.hass, SOURCE_ENTITIES["fan_rpm"]),
            body_c=_float_state(self.hass, SOURCE_ENTITIES["body_c"]),
            room_c=_float_state(self.hass, SOURCE_ENTITIES["room_c"]),
            setpoint_c=(
                _float_attribute(
                    self.hass,
                    self.climate_entity_id,
                    "temperature",
                )
                or _float_state(self.hass, SOURCE_ENTITIES["setpoint_c"])
            ),
            input_v=_float_state(self.hass, SOURCE_ENTITIES["input_v"]),
            glow_v=_float_state(self.hass, SOURCE_ENTITIES["glow_v"]),
        )
        controller_used = _float_state(
            self.hass,
            SOURCE_ENTITIES["fuel_used_l"],
        )
        if controller_used is None:
            raise UpdateFailed(
                f"source unavailable: {SOURCE_ENTITIES['fuel_used_l']}"
            )

        fuel_config = FuelConfig(
                tank_capacity_l=float(
                    _option(
                        self.entry,
                        CONF_TANK_CAPACITY,
                        DEFAULT_TANK_CAPACITY,
                    )
                ),
                pump_ml_per_stroke=float(
                    _option(
                        self.entry,
                        CONF_PUMP_ML_PER_STROKE,
                        DEFAULT_PUMP_ML_PER_STROKE,
                    )
                ),
                usage_correction_factor=float(
                    _option(
                        self.entry,
                        CONF_USAGE_CORRECTION_FACTOR,
                        DEFAULT_USAGE_CORRECTION_FACTOR,
                    )
                ),
                maximum_pump_hz=float(
                    _option(
                        self.entry,
                        CONF_MAXIMUM_PUMP_HZ,
                        DEFAULT_MAXIMUM_PUMP_HZ,
                    )
                ),
            )
        fuel = calculate_fuel(
            fuel_config,
            controller_used_l=controller_used,
            pump_hz=telemetry.pump_hz or 0,
        )
        price_per_litre = float(
            _option(
                self.entry,
                CONF_DIESEL_PRICE_PER_LITRE,
                DEFAULT_DIESEL_PRICE_PER_LITRE,
            )
        )
        ledger_changed = self._cost_ledger.update(
            fuel.corrected_used_l,
            price_per_litre,
        )
        costs = calculate_fuel_costs(
            fuel_config,
            fuel,
            price_per_litre=price_per_litre,
            cost_used_since_reset=self._cost_ledger.used_since_reset,
            recorded_total_cost=self._cost_ledger.recorded_total,
        )
        warnings = tuple(self._detector.update(telemetry))
        if self.active_control_enabled:
            source_run_request = (
                _text_state(self.hass, SOURCE_ENTITIES["run_request"]) == "on"
            )
            # A controller-owned auto-stop is itself authorization for exactly
            # one matching restart. An external climate Off event cancels it.
            run_request_armed = (
                source_run_request or self._cycle.memory.auto_stopped
            )
            cycle_decision = self._cycle.update(
                telemetry,
                run_request_armed=run_request_armed,
            )
            recovery_decision = self._recovery.update(telemetry, warnings)
        else:
            self._cycle.disable(telemetry.setpoint_c)
            self._recovery.manual_stop()
            cycle_decision = ControlDecision(
                ControlAction.NONE,
                CycleMode.DISABLED,
                "active control is disabled",
            )
            recovery_decision = RecoveryDecision(
                RecoveryAction.NONE,
                "active control is disabled",
            )
        if ledger_changed or cycle_state_before != self._persistent_cycle_state():
            await self._async_save_state()
        return AfterburnerData(
            telemetry=telemetry,
            fuel=fuel,
            costs=costs,
            warnings=warnings,
            cycle_decision=cycle_decision,
            recovery_decision=recovery_decision,
            active_control_enabled=self.active_control_enabled,
            last_command=self._last_command,
            last_command_at=self._last_command_at,
            decision_history=tuple(self._decision_history),
        )

    def _persistent_cycle_state(self) -> tuple[Any, ...]:
        """Return controller-owned state whose changes must survive a restart."""
        cycle = self._cycle.memory
        return (
            cycle.mode,
            cycle.auto_stopped,
            cycle.auto_stopped_at,
            cycle.run_started_at,
            cycle.restart_commanded_at,
            cycle.manual_stop_latched,
            cycle.last_setpoint_c,
            cycle.lockout_reason,
            tuple(cycle.start_times),
        )

    async def _async_apply_control(self, data: AfterburnerData) -> None:
        if not self.active_control_enabled:
            return
        # Multi-source staging owns the diesel climate entity. Running the
        # legacy thermal-cycle actuator in parallel creates two controllers
        # with different temperature inputs and causes short cycling.
        if self.heat_group is not None:
            return
        async with self._actuation_lock:
            try:
                if data.recovery_decision.action is RecoveryAction.RESTORE_AND_STOP:
                    await self._async_restore_recovery_setpoint(
                        data.recovery_decision
                    )
                    await self._async_set_hvac_mode("off", data.recovery_decision.reason)
                elif data.cycle_decision.action is ControlAction.NORMAL_STOP:
                    await self._async_set_hvac_mode(
                        "off",
                        data.cycle_decision.reason,
                    )
                elif data.recovery_decision.action in {
                    RecoveryAction.BOOST,
                    RecoveryAction.RESTORE,
                }:
                    await self._async_set_temperature(
                        data.recovery_decision.target_setpoint_c,
                        data.recovery_decision.reason,
                    )
                elif data.cycle_decision.action is ControlAction.NORMAL_START:
                    await self._async_set_hvac_mode(
                        "heat",
                        data.cycle_decision.reason,
                    )
                else:
                    return
                await self._async_save_state()
            except HomeAssistantError as err:
                reason = f"Home Assistant command failed: {err}"
                _LOGGER.error(reason)
                self._cycle.memory.lockout_reason = reason
                self._recovery.memory.lockout_reason = reason
                await self._async_save_state()

    async def _async_restore_recovery_setpoint(
        self,
        decision: RecoveryDecision,
    ) -> None:
        if decision.target_setpoint_c is not None:
            await self._async_set_temperature(
                decision.target_setpoint_c,
                "restoring the pre-recovery setpoint",
            )

    async def _async_set_hvac_mode(self, mode: str, reason: str) -> None:
        context = Context()
        self._owned_service_contexts.append(context.id)
        await self.hass.services.async_call(
            "climate",
            "set_hvac_mode",
            {
                "entity_id": self.climate_entity_id,
                "hvac_mode": mode,
            },
            blocking=True,
            context=context,
        )
        self._record_command(f"hvac:{mode}", reason)

    async def _async_set_temperature(
        self,
        temperature: float | None,
        reason: str,
    ) -> None:
        if temperature is None:
            raise HomeAssistantError("recovery target temperature is unavailable")
        context = Context()
        self._owned_service_contexts.append(context.id)
        await self.hass.services.async_call(
            "climate",
            "set_temperature",
            {
                "entity_id": self.climate_entity_id,
                "temperature": temperature,
            },
            blocking=True,
            context=context,
        )
        self._record_command(f"setpoint:{temperature:g}", reason)

    def _record_command(self, command: str, reason: str) -> None:
        self._last_command = command
        self._last_command_at = datetime.now().astimezone().isoformat(
            timespec="seconds"
        )
        record = f"{self._last_command_at} {command}: {reason}"
        self._decision_history.append(record)
        _LOGGER.warning("Afterburner automatic command: %s", record)

    async def _async_save_state(self) -> None:
        cycle = self._cycle.memory
        recovery = self._recovery.memory
        await self._store.async_save(
            {
                "cycle": {
                    "mode": cycle.mode.value,
                    "auto_stopped": cycle.auto_stopped,
                    "auto_stopped_at": cycle.auto_stopped_at,
                    "run_started_at": cycle.run_started_at,
                    "restart_commanded_at": cycle.restart_commanded_at,
                    "manual_stop_latched": cycle.manual_stop_latched,
                    "last_setpoint_c": cycle.last_setpoint_c,
                    "lockout_reason": cycle.lockout_reason,
                    "start_times": list(cycle.start_times),
                },
                "recovery": {
                    "active": recovery.active,
                    "attempted_this_run": recovery.attempted_this_run,
                    "started_at": recovery.started_at,
                    "starting_body_c": recovery.starting_body_c,
                    "original_setpoint_c": recovery.original_setpoint_c,
                    "lockout_reason": recovery.lockout_reason,
                },
                "last_command": self._last_command,
                "last_command_at": self._last_command_at,
                "decision_history": list(self._decision_history),
                "fuel_cost": {
                    "used_since_reset": self._cost_ledger.used_since_reset,
                    "recorded_total": self._cost_ledger.recorded_total,
                    "last_corrected_fuel_used_l": self._cost_ledger.last_corrected_fuel_used_l,
                },
            }
        )
