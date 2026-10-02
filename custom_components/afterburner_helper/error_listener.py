"""Error listener for automatic flameout recovery."""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.event import async_track_state_change_event

_LOGGER = logging.getLogger(__name__)


async def async_setup_error_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Set up error state listener."""
    topic_prefix = entry.data["mqtt_topic_prefix"]
    recovery_running = False
    
    async def error_state_changed(event):
        nonlocal recovery_running
        new_state = event.data.get("new_state")
        old_state = event.data.get("old_state")
        
        if new_state is None or new_state.state in ("unknown", "unavailable"):
            return
        
        # Log all error state changes
        if old_state and old_state.state != new_state.state:
            _LOGGER.info("Error state changed: %s → %s", old_state.state, new_state.state)
        
        # Extract error code
        error_code = new_state.state.split(":")[0].strip()
        
        # Log all non-OK errors
        if error_code != "E-00":
            _LOGGER.warning("Heater error detected: %s", new_state.state)
        
        # Only trigger on E-08
        if error_code != "E-08":
            if error_code == "E-10":
                _LOGGER.info("E-10 (Ignition failure) detected - This indicates a failed restart attempt, not triggering new recovery")
            return
        
        _LOGGER.warning("🔥 E-08 FLAMEOUT DETECTED for %s - Checking if automatic recovery is enabled", topic_prefix)
        
        # Send notification for E-08 detection
        await hass.services.async_call(
            "persistent_notification",
            "create",
            {
                "title": "🔥 Flameout Detected",
                "message": f"E-08 error detected. Checking recovery settings...",
                "notification_id": "afterburner_flameout_detected"
            }
        )
        
        # Check if recovery is enabled
        recovery_switch = hass.states.get(f"switch.{topic_prefix}_flameout_recovery")
        if not recovery_switch:
            _LOGGER.error("Recovery switch not found: switch.%s_flameout_recovery", topic_prefix)
            return
            
        if recovery_switch.state != "on":
            _LOGGER.warning("⚠️ Flameout recovery is DISABLED - No automatic recovery will occur")
            _LOGGER.info("Enable recovery by turning on switch.%s_flameout_recovery", topic_prefix)
            
            # Send notification for disabled recovery
            await hass.services.async_call(
                "persistent_notification",
                "create",
                {
                    "title": "⚠️ Recovery Disabled",
                    "message": "Flameout detected but automatic recovery is OFF. Enable the recovery switch to allow automatic restarts.",
                    "notification_id": "afterburner_recovery_disabled_warning"
                }
            )
            return
        
        _LOGGER.info("✓ Flameout recovery is ENABLED - Initiating recovery sequence")
        
        # Send notification for starting recovery
        await hass.services.async_call(
            "persistent_notification",
            "create",
            {
                "title": "🚀 Starting Recovery",
                "message": "Automatic flameout recovery initiated. Monitoring progress...",
                "notification_id": "afterburner_recovery_starting"
            }
        )
        
        # Prevent concurrent recovery
        if recovery_running:
            _LOGGER.warning("⏳ Recovery already in progress, skipping duplicate attempt")
            return
        
        recovery_running = True
        try:
            _LOGGER.info("🚀 Starting automatic flameout recovery sequence")
            await hass.services.async_call(
                "afterburner_helper",
                "flameout_recovery",
                {},
                blocking=True
            )
            _LOGGER.info("✓ Automatic flameout recovery completed")
        except Exception as e:
            _LOGGER.error("❌ Automatic flameout recovery failed: %s", e)
        finally:
            recovery_running = False
    
    # Register state change listener for error sensor
    async_track_state_change_event(
        hass,
        "sensor.afterburner_error_state",
        error_state_changed
    )
    
    _LOGGER.info("📡 Error listener registered and actively monitoring sensor.afterburner_error_state")
