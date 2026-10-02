"""MQTT-backed access to persistent Afterburner controller settings."""

from __future__ import annotations

import json
import logging
import asyncio
from collections.abc import Callable
from typing import Any

from homeassistant.components import mqtt
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback

from .const import CONF_MQTT_TOPIC_PREFIX, DEFAULT_MQTT_TOPIC_PREFIX

_LOGGER = logging.getLogger(__name__)


class AfterburnerSettingsHub:
    """Collect JSONout settings and publish validated controller commands."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.hass = hass
        self.entry = entry
        self.topic_prefix = str(
            entry.data.get(CONF_MQTT_TOPIC_PREFIX, DEFAULT_MQTT_TOPIC_PREFIX)
        )
        self.values: dict[str, Any] = {}
        self._listeners: set[Callable[[], None]] = set()
        self._unsubscribe: Callable[[], None] | None = None

    async def async_start(self) -> None:
        self._unsubscribe = await mqtt.async_subscribe(
            self.hass,
            f"{self.topic_prefix}/JSONout",
            self._message_received,
            qos=0,
        )
        await self.async_publish("Refresh", 1, save=False)

    async def async_stop(self) -> None:
        if self._unsubscribe is not None:
            self._unsubscribe()
            self._unsubscribe = None

    @callback
    def _message_received(self, message: mqtt.ReceiveMessage) -> None:
        try:
            payload = json.loads(message.payload)
        except (TypeError, ValueError):
            _LOGGER.debug("Ignoring invalid Afterburner JSONout payload")
            return
        if not isinstance(payload, dict):
            return
        self.values.update(payload)
        for listener in tuple(self._listeners):
            listener()

    @callback
    def async_add_listener(self, listener: Callable[[], None]) -> Callable[[], None]:
        self._listeners.add(listener)

        def remove_listener() -> None:
            self._listeners.discard(listener)

        return remove_listener

    async def async_publish(self, command: str, value: Any, *, save: bool = True) -> None:
        await mqtt.async_publish(
            self.hass,
            f"{self.topic_prefix}/cmd/{command}",
            str(value),
            qos=0,
            retain=False,
        )
        self.values[command] = value
        for listener in tuple(self._listeners):
            listener()
        if save:
            await mqtt.async_publish(
                self.hass,
                f"{self.topic_prefix}/cmd/NVsave",
                "8861",
                qos=0,
                retain=False,
            )

    async def async_reboot(self) -> None:
        """Complete Afterburner's two-step reboot challenge over MQTT."""
        self.values.pop("Reboot", None)
        challenge_received = asyncio.Event()

        @callback
        def challenge_listener() -> None:
            try:
                challenge = int(self.values.get("Reboot", 0))
            except (TypeError, ValueError):
                return
            if challenge > 0:
                challenge_received.set()

        remove_listener = self.async_add_listener(challenge_listener)
        try:
            await mqtt.async_publish(
                self.hass,
                f"{self.topic_prefix}/cmd/Reboot",
                "0",
                qos=0,
                retain=False,
            )
            await asyncio.wait_for(challenge_received.wait(), timeout=10)
            challenge = int(self.values["Reboot"])
            await mqtt.async_publish(
                self.hass,
                f"{self.topic_prefix}/cmd/Reboot",
                str(challenge),
                qos=0,
                retain=False,
            )
        finally:
            remove_listener()
