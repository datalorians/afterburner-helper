"""Afterburner Helper v2 integration."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import DOMAIN, PLATFORMS
from .coordinator import AfterburnerCoordinator


async def async_migrate_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Migrate the installed v1 entry without changing its working settings."""
    if entry.version == 1:
        hass.config_entries.async_update_entry(
            entry,
            version=2,
            minor_version=1,
        )
    return True


async def _async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Apply option changes immediately."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up one Afterburner helper entry."""
    coordinator = AfterburnerCoordinator(hass, entry)
    await coordinator.async_initialize()
    await coordinator.async_config_entry_first_refresh()
    coordinator.async_start()

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_reload_entry))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload the entry and all event subscriptions."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        coordinator: AfterburnerCoordinator = hass.data[DOMAIN].pop(entry.entry_id)
        coordinator.async_stop()
    return unload_ok
