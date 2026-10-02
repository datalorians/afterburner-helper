"""Staged multi-source heat group for diesel and up to two smart plugs."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import STATE_ON, STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import Context, HomeAssistant, callback
from homeassistant.helpers.event import async_call_later, async_track_state_change_event
from homeassistant.helpers.storage import Store

from .const import (
    CONF_CLIMATE_ENTITY_ID,
    CONF_ELECTRIC_HEATER_1_ENTITY_ID,
    CONF_ELECTRIC_HEATER_2_ENTITY_ID,
    CONF_FUSED_TEMPERATURE_ENTITIES,
    CONF_OUTDOOR_TEMPERATURE_ENTITY_ID,
    CONF_ROOM_TEMPERATURE_ENTITY_ID,
    CONF_USE_FUSED_TEMPERATURE,
    DEFAULT_CLIMATE_ENTITY_ID,
    DEFAULT_ELECTRIC_HEATER_1_ENTITY_ID,
    DEFAULT_ELECTRIC_HEATER_2_ENTITY_ID,
    DEFAULT_FUSED_TEMPERATURE_ENTITIES,
    DEFAULT_OUTDOOR_TEMPERATURE_ENTITY_ID,
    DEFAULT_ROOM_TEMPERATURE_ENTITY_ID,
    DEFAULT_USE_FUSED_TEMPERATURE,
    HEAT_SOURCES,
    PRIORITY_OPTIONS,
    SOURCE_ENTITIES,
)
from .heat_logic import hysteretic_stage_count, requested_sources
from .temperature import fused_temperature


@dataclass(frozen=True, slots=True)
class StageSnapshot:
    room_temperature: float | None
    target_temperature: float
    master_enabled: bool
    active_sources: tuple[str, ...]
    requested_sources: tuple[str, ...]


class HeatGroupManager:
    """Persist group preferences and reconcile requested heat sources."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, diesel_contexts=None) -> None:
        self.hass = hass
        self.entry = entry
        options = {**entry.data, **entry.options}
        self.room_entity = options.get(CONF_ROOM_TEMPERATURE_ENTITY_ID, DEFAULT_ROOM_TEMPERATURE_ENTITY_ID)
        self.use_fused_temperature = bool(
            options.get(CONF_USE_FUSED_TEMPERATURE, DEFAULT_USE_FUSED_TEMPERATURE)
        )
        configured_sources = options.get(
            CONF_FUSED_TEMPERATURE_ENTITIES,
            DEFAULT_FUSED_TEMPERATURE_ENTITIES,
        )
        if isinstance(configured_sources, str):
            configured_sources = [configured_sources]
        self.fused_temperature_entities = tuple(
            dict.fromkeys(
                entity_id
                for entity_id in configured_sources
                if isinstance(entity_id, str) and entity_id
            )
        )
        self.outdoor_temperature_entity = options.get(
            CONF_OUTDOOR_TEMPERATURE_ENTITY_ID,
            DEFAULT_OUTDOOR_TEMPERATURE_ENTITY_ID,
        )
        self.diesel_entity = options.get(CONF_CLIMATE_ENTITY_ID, DEFAULT_CLIMATE_ENTITY_ID)
        self.electric_entities = {
            "electric_1": options.get(CONF_ELECTRIC_HEATER_1_ENTITY_ID, DEFAULT_ELECTRIC_HEATER_1_ENTITY_ID),
            "electric_2": options.get(CONF_ELECTRIC_HEATER_2_ENTITY_ID, DEFAULT_ELECTRIC_HEATER_2_ENTITY_ID),
        }
        self.target_temperature = 22.0
        self.master_enabled = False
        self.priority = PRIORITY_OPTIONS[0]
        self.lockouts = {source: False for source in HEAT_SOURCES}
        self.member_modes = {source: "auto" for source in HEAT_SOURCES}
        self.member_targets = {source: 22.0 for source in HEAT_SOURCES}
        self._listeners: set[Any] = set()
        self._unsub = None
        self._startup_unsub = None
        self._retry_unsub = None
        self._startup_ready = False
        self._startup_seen_temperature_sources: set[str] = set()
        self._lock = asyncio.Lock()
        self._store = Store(hass, 1, f"afterburner_helper.{entry.entry_id}.heat_group")
        self._diesel_contexts = diesel_contexts
        self._last_diesel_command: str | None = None
        self._last_diesel_command_at = 0.0
        self._last_switch_commands: dict[str, str] = {}
        self._last_switch_command_at: dict[str, float] = {}
        self._automatic_stage_count = 0

    async def async_start(self) -> None:
        saved = await self._store.async_load()
        if not saved:
            diesel = self.hass.states.get(self.diesel_entity)
            self.master_enabled = bool(diesel and diesel.state == "heat")
            if diesel:
                try:
                    self.target_temperature = float(diesel.attributes.get("temperature", 22.0))
                except (TypeError, ValueError):
                    pass
            if self.master_enabled:
                self.member_modes["diesel"] = "heat"
            for source, entity_id in self.electric_entities.items():
                state = self.hass.states.get(entity_id) if entity_id else None
                if state and state.state == STATE_ON:
                    self.member_modes[source] = "heat"
            saved = {}
        self.target_temperature = float(saved.get("target_temperature", 22.0))
        self.master_enabled = bool(saved.get("master_enabled", False))
        self.priority = saved.get("priority", PRIORITY_OPTIONS[0])
        self.lockouts.update(saved.get("lockouts", {}))
        self.member_modes.update(saved.get("member_modes", {}))
        self.member_targets.update(saved.get("member_targets", {}))
        watched = [
            self.room_entity,
            self.diesel_entity,
            SOURCE_ENTITIES["run_state"],
            self.outdoor_temperature_entity,
            *self.fused_temperature_entities,
        ]
        watched.extend(entity for entity in self.electric_entities.values() if entity)
        self._unsub = async_track_state_change_event(
            hass=self.hass,
            entity_ids=list(dict.fromkeys(watched)),
            action=self._state_changed,
        )
        # Source integrations restore and reconnect at different times during a
        # Home Assistant boot. Do not stage against a partial fused value (for
        # example, the colder sensor arriving before the warmer one). Reconcile
        # as soon as every control source has emitted a valid state, with a
        # bounded fallback for a sensor that remains unavailable.
        self._startup_unsub = async_call_later(
            self.hass,
            30,
            self._startup_stabilized,
        )
        if saved:
            await self.async_reconcile()
        else:
            await self._changed_without_reconcile()

    async def async_stop(self) -> None:
        if self._unsub:
            self._unsub()
            self._unsub = None
        if self._startup_unsub:
            self._startup_unsub()
            self._startup_unsub = None
        if self._retry_unsub:
            self._retry_unsub()
            self._retry_unsub = None

    @callback
    def _state_changed(self, event) -> None:
        entity_id = event.data.get("entity_id")
        if entity_id in self.control_temperature_entities:
            new_state = event.data.get("new_state")
            if new_state and fused_temperature((new_state.state,)) is not None:
                self._startup_seen_temperature_sources.add(entity_id)
                if set(self.control_temperature_entities).issubset(
                    self._startup_seen_temperature_sources
                ):
                    self._set_startup_ready()
        self.hass.async_create_task(self.async_reconcile())

    @property
    def control_temperature_entities(self) -> tuple[str, ...]:
        """Entities that must settle before startup staging is enabled."""
        if self.use_fused_temperature:
            return self.fused_temperature_entities
        return (self.room_entity,)

    @callback
    def _startup_stabilized(self, _now) -> None:
        """End the bounded startup hold even if one source is unavailable."""
        self._startup_unsub = None
        self._set_startup_ready()

    @callback
    def _set_startup_ready(self) -> None:
        if self._startup_ready:
            return
        self._startup_ready = True
        if self._startup_unsub:
            self._startup_unsub()
            self._startup_unsub = None
        self.hass.async_create_task(self.async_reconcile())

    @callback
    def async_add_listener(self, listener):
        self._listeners.add(listener)
        return lambda: self._listeners.discard(listener)

    @property
    def room_temperature(self) -> float | None:
        if self.use_fused_temperature:
            return self.fused_temperature
        state = self.hass.states.get(self.room_entity)
        try:
            return float(state.state) if state else None
        except (TypeError, ValueError):
            return None

    @property
    def fused_temperature(self) -> float | None:
        """Average every currently valid configured temperature source."""
        return fused_temperature(self.fused_temperature_values.values())

    @property
    def fused_temperature_values(self) -> dict[str, float]:
        """Return valid source values keyed by entity ID."""
        values: dict[str, float] = {}
        for entity_id in self.fused_temperature_entities:
            state = self.hass.states.get(entity_id)
            if state is None or state.state in {STATE_UNAVAILABLE, STATE_UNKNOWN}:
                continue
            value = fused_temperature((state.state,))
            if value is not None:
                values[entity_id] = value
        return values

    @property
    def outdoor_temperature(self) -> float | None:
        """Return the configured outdoor reference temperature."""
        state = self.hass.states.get(self.outdoor_temperature_entity)
        if state is None or state.state in {STATE_UNAVAILABLE, STATE_UNKNOWN}:
            return None
        return fused_temperature((state.state,))

    @property
    def outdoor_demand_delta(self) -> float | None:
        """Return demand minus outdoor temperature."""
        if self.outdoor_temperature is None:
            return None
        return round(self.target_temperature - self.outdoor_temperature, 2)

    @property
    def indoor_outdoor_delta(self) -> float | None:
        """Return controlled indoor temperature minus outdoor temperature."""
        if self.room_temperature is None or self.outdoor_temperature is None:
            return None
        return round(self.room_temperature - self.outdoor_temperature, 2)

    def snapshot(self) -> StageSnapshot:
        requested = self._requested_sources()
        active = []
        diesel = self.hass.states.get(self.diesel_entity)
        if diesel and diesel.state == "heat":
            active.append("diesel")
        for source, entity_id in self.electric_entities.items():
            state = self.hass.states.get(entity_id) if entity_id else None
            if state and state.state == STATE_ON:
                active.append(source)
        return StageSnapshot(self.room_temperature, self.target_temperature, self.master_enabled, tuple(active), requested)

    def _requested_sources(self) -> tuple[str, ...]:
        self._automatic_stage_count = (
            hysteretic_stage_count(
                self.room_temperature,
                self.target_temperature,
                self._automatic_stage_count,
            )
            if self.master_enabled
            else 0
        )
        return requested_sources(
            room=self.room_temperature,
            master_target=self.target_temperature,
            master_enabled=self.master_enabled,
            priority=self.priority,
            lockouts=self.lockouts,
            member_modes=self.member_modes,
            member_targets=self.member_targets,
            automatic_count=self._automatic_stage_count,
        )

    async def async_reconcile(self) -> None:
        async with self._lock:
            if not self._startup_ready:
                self._notify()
                return
            requested = self._requested_sources()
            await self._set_diesel("diesel" in requested)
            for source, entity_id in self.electric_entities.items():
                if entity_id:
                    await self._set_switch(entity_id, source in requested)
            self._notify()

    async def _set_diesel(self, enabled: bool) -> None:
        state = self.hass.states.get(self.diesel_entity)
        if state is None or state.state in {STATE_UNAVAILABLE, STATE_UNKNOWN}:
            return
        current = state.state if state else None
        mode = "heat" if enabled else "off"
        run_state = self.hass.states.get(SOURCE_ENTITIES["run_state"])
        actual_run_state = run_state.state.strip().lower() if run_state else ""
        diesel_is_inactive = actual_run_state in {
            "stopped/ready",
            "stopped",
            "ready",
            "off",
        }
        diesel_is_stopping = actual_run_state in {"stopping", "shutdown"}
        # A MQTT climate can remain in Heat while the physical controller is
        # stopping or stopped. Never treat that stale mode as proof that heat
        # is running. Wait for the mandatory cooldown, then reassert Heat when
        # the real run-state reaches Ready.
        if enabled and diesel_is_stopping:
            return
        if current == mode and not (enabled and diesel_is_inactive):
            self._last_diesel_command = mode
            self._last_diesel_command_at = self.hass.loop.time()
            return
        now = self.hass.loop.time()
        if (
            self._last_diesel_command == mode
            and now - self._last_diesel_command_at < 5
        ):
            if enabled and diesel_is_inactive:
                self._schedule_confirmation_retry(6)
            return
        if enabled:
            await self.hass.services.async_call("climate", "set_temperature", {"entity_id": self.diesel_entity, "temperature": self.target_temperature}, blocking=True, context=Context())
        context = Context()
        self._last_diesel_command = mode
        self._last_diesel_command_at = now
        if self._diesel_contexts is not None:
            self._diesel_contexts.append(context.id)
        await self.hass.services.async_call("climate", "set_hvac_mode", {"entity_id": self.diesel_entity, "hvac_mode": mode}, blocking=True, context=context)
        if enabled:
            self._schedule_confirmation_retry(10)

    async def _set_switch(self, entity_id: str, enabled: bool) -> None:
        state = self.hass.states.get(entity_id)
        if state is None or state.state in {STATE_UNAVAILABLE, STATE_UNKNOWN}:
            return
        desired = STATE_ON if enabled else "off"
        if state.state == desired:
            self._last_switch_commands[entity_id] = desired
            self._last_switch_command_at[entity_id] = self.hass.loop.time()
            return
        now = self.hass.loop.time()
        if (
            self._last_switch_commands.get(entity_id) == desired
            and now - self._last_switch_command_at.get(entity_id, 0) < 2
        ):
            return
        if state.state != desired:
            context = Context()
            self._last_switch_commands[entity_id] = desired
            self._last_switch_command_at[entity_id] = now
            await self.hass.services.async_call(
                "switch",
                "turn_on" if enabled else "turn_off",
                {"entity_id": entity_id},
                blocking=True,
                context=context,
            )
            self._schedule_confirmation_retry(3)

    def _schedule_confirmation_retry(self, delay: int) -> None:
        """Retry an unconfirmed physical command without waiting for polling."""
        if self._retry_unsub is not None:
            return

        @callback
        def _retry(_now) -> None:
            self._retry_unsub = None
            self.hass.async_create_task(self.async_reconcile())

        self._retry_unsub = async_call_later(self.hass, delay, _retry)

    async def async_set_master_enabled(self, enabled: bool) -> None:
        self.master_enabled = enabled
        await self._changed()

    async def async_set_target(self, temperature: float) -> None:
        self.target_temperature = temperature
        # The master thermostat is the group's demand control. Keep every
        # member's target aligned whenever it changes; member modes and
        # lockouts remain independent, and a member can still be adjusted
        # manually afterward.
        for source in HEAT_SOURCES:
            self.member_targets[source] = temperature
        await self._changed()

    async def async_set_priority(self, priority: str) -> None:
        if priority not in PRIORITY_OPTIONS:
            return
        self.priority = priority
        await self._changed()

    async def async_set_lockout(self, source: str, locked: bool) -> None:
        self.lockouts[source] = locked
        # Lockout is an immediate actuator command. Automatic mode stays
        # selected so unlocking can return the source to group control; only
        # an explicit member Heat mode is allowed to override the lockout.
        if locked and self.member_modes[source] != "heat":
            if source == "diesel":
                await self._set_diesel(False)
            else:
                entity_id = self.electric_entities.get(source)
                if entity_id:
                    await self._set_switch(entity_id, False)
        await self._changed()

    async def async_set_member_mode(self, source: str, mode: str) -> None:
        self.member_modes[source] = mode
        await self._changed()

    async def async_set_member_target(self, source: str, temperature: float) -> None:
        self.member_targets[source] = temperature
        await self._changed()

    async def _changed(self) -> None:
        self._last_diesel_command = None
        self._last_diesel_command_at = 0.0
        self._last_switch_commands.clear()
        self._last_switch_command_at.clear()
        await self._changed_without_reconcile()
        await self.async_reconcile()

    async def _changed_without_reconcile(self) -> None:
        await self._store.async_save({
            "target_temperature": self.target_temperature,
            "master_enabled": self.master_enabled,
            "priority": self.priority,
            "lockouts": self.lockouts,
            "member_modes": self.member_modes,
            "member_targets": self.member_targets,
        })
        self._notify()

    def _notify(self) -> None:
        for listener in tuple(self._listeners):
            listener()
