"""Staged multi-source heat group for diesel and up to two smart plugs."""

from __future__ import annotations

import asyncio
from collections import deque
from dataclasses import dataclass
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import STATE_ON, STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import Context, HomeAssistant, callback
from homeassistant.helpers.event import async_track_state_change_event
from homeassistant.helpers.storage import Store

from .const import (
    CONF_CLIMATE_ENTITY_ID,
    CONF_ELECTRIC_HEATER_1_ENTITY_ID,
    CONF_ELECTRIC_HEATER_2_ENTITY_ID,
    CONF_FUSED_TEMPERATURE_ENTITIES,
    CONF_ROOM_TEMPERATURE_ENTITY_ID,
    CONF_USE_FUSED_TEMPERATURE,
    DEFAULT_CLIMATE_ENTITY_ID,
    DEFAULT_ELECTRIC_HEATER_1_ENTITY_ID,
    DEFAULT_ELECTRIC_HEATER_2_ENTITY_ID,
    DEFAULT_FUSED_TEMPERATURE_ENTITIES,
    DEFAULT_ROOM_TEMPERATURE_ENTITY_ID,
    DEFAULT_USE_FUSED_TEMPERATURE,
    HEAT_SOURCES,
    PRIORITY_OPTIONS,
)
from .heat_logic import requested_sources
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
        self._lock = asyncio.Lock()
        self._store = Store(hass, 1, f"afterburner_helper.{entry.entry_id}.heat_group")
        self._owned_contexts: deque[str] = deque(maxlen=20)
        self._diesel_contexts = diesel_contexts
        self._last_diesel_command: str | None = None
        self._last_switch_commands: dict[str, str] = {}

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
        watched = [self.room_entity, self.diesel_entity, *self.fused_temperature_entities]
        watched.extend(entity for entity in self.electric_entities.values() if entity)
        self._unsub = async_track_state_change_event(
            hass=self.hass,
            entity_ids=list(dict.fromkeys(watched)),
            action=self._state_changed,
        )
        if saved:
            await self.async_reconcile()
        else:
            await self._changed_without_reconcile()

    async def async_stop(self) -> None:
        if self._unsub:
            self._unsub()
            self._unsub = None

    @callback
    def _state_changed(self, event) -> None:
        source = next(
            (
                name
                for name, entity_id in self.electric_entities.items()
                if entity_id == event.data.get("entity_id")
            ),
            None,
        )
        if source and event.context.id not in self._owned_contexts:
            new_state = event.data.get("new_state")
            if new_state and new_state.state in {STATE_ON, "off"}:
                self.member_modes[source] = "heat" if new_state.state == STATE_ON else "off"
                self.hass.async_create_task(self._changed_without_reconcile())
                return
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
        return requested_sources(
            room=self.room_temperature,
            master_target=self.target_temperature,
            master_enabled=self.master_enabled,
            priority=self.priority,
            lockouts=self.lockouts,
            member_modes=self.member_modes,
            member_targets=self.member_targets,
        )

    async def async_reconcile(self) -> None:
        async with self._lock:
            requested = self._requested_sources()
            await self._set_diesel("diesel" in requested)
            for source, entity_id in self.electric_entities.items():
                if entity_id:
                    if self.lockouts[source] and self.member_modes[source] == "auto":
                        continue
                    await self._set_switch(entity_id, source in requested)
            self._notify()

    async def _set_diesel(self, enabled: bool) -> None:
        state = self.hass.states.get(self.diesel_entity)
        if state is None or state.state in {STATE_UNAVAILABLE, STATE_UNKNOWN}:
            return
        current = state.state if state else None
        mode = "heat" if enabled else "off"
        if self._last_diesel_command == mode:
            return
        if current == mode:
            self._last_diesel_command = mode
            return
        if enabled:
            await self.hass.services.async_call("climate", "set_temperature", {"entity_id": self.diesel_entity, "temperature": self.target_temperature}, blocking=True, context=Context())
        context = Context()
        self._last_diesel_command = mode
        if self._diesel_contexts is not None:
            self._diesel_contexts.append(context.id)
        await self.hass.services.async_call("climate", "set_hvac_mode", {"entity_id": self.diesel_entity, "hvac_mode": mode}, blocking=True, context=context)

    async def _set_switch(self, entity_id: str, enabled: bool) -> None:
        state = self.hass.states.get(entity_id)
        if state is None or state.state in {STATE_UNAVAILABLE, STATE_UNKNOWN}:
            return
        desired = STATE_ON if enabled else "off"
        if self._last_switch_commands.get(entity_id) == desired:
            return
        if state.state == desired:
            self._last_switch_commands[entity_id] = desired
            return
        if state.state != desired:
            context = Context()
            self._owned_contexts.append(context.id)
            self._last_switch_commands[entity_id] = desired
            await self.hass.services.async_call(
                "switch",
                "turn_on" if enabled else "turn_off",
                {"entity_id": entity_id},
                blocking=True,
                context=context,
            )

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
        await self._changed()

    async def async_set_member_mode(self, source: str, mode: str) -> None:
        self.member_modes[source] = mode
        await self._changed()

    async def async_set_member_target(self, source: str, temperature: float) -> None:
        self.member_targets[source] = temperature
        await self._changed()

    async def _changed(self) -> None:
        self._last_diesel_command = None
        self._last_switch_commands.clear()
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
