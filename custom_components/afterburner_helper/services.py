"""Services for Afterburner Helper integration."""
from __future__ import annotations

import asyncio
import logging
from typing import Any

# Removed MQTT import - using climate entity instead
from homeassistant.core import HomeAssistant

from .const import RECOVERABLE_ERRORS

_LOGGER = logging.getLogger(__name__)


async def async_flameout_recovery(
    hass: HomeAssistant,
    topic_prefix: str,
    device_name: str,
    retry_attempts: int | None = None,
    retry_delay: int | None = None,
    cooling_wait: int | None = None,
    off_wait: int | None = None,
) -> None:
    """Execute flameout recovery sequence."""
    
    # Get current settings from number entities if not provided
    if retry_attempts is None:
        retry_attempts_entity = f"number.{topic_prefix}_retry_attempts"
        retry_attempts_state = hass.states.get(retry_attempts_entity)
        retry_attempts = 3
        if retry_attempts_state and retry_attempts_state.state not in ("unknown", "unavailable"):
            retry_attempts = int(float(retry_attempts_state.state))
    
    if retry_delay is None:
        retry_delay_entity = f"number.{topic_prefix}_retry_delay"
        retry_delay_state = hass.states.get(retry_delay_entity)
        retry_delay = 60
        if retry_delay_state and retry_delay_state.state not in ("unknown", "unavailable"):
            retry_delay = int(float(retry_delay_state.state))
    
    if cooling_wait is None:
        cooling_wait_entity = f"number.{topic_prefix}_cooling_wait"
        cooling_wait_state = hass.states.get(cooling_wait_entity)
        cooling_wait = 300  # 5 minutes
        if cooling_wait_state and cooling_wait_state.state not in ("unknown", "unavailable"):
            cooling_wait = int(float(cooling_wait_state.state))
    
    if off_wait is None:
        off_wait_entity = f"number.{topic_prefix}_off_wait"
        off_wait_state = hass.states.get(off_wait_entity)
        off_wait = 120  # 2 minutes
        if off_wait_state and off_wait_state.state not in ("unknown", "unavailable"):
            off_wait = int(float(off_wait_state.state))
    
    # Check if recovery is enabled
    recovery_switch_entity = f"switch.{topic_prefix}_flameout_recovery"
    recovery_switch = hass.states.get(recovery_switch_entity)
    if not recovery_switch or recovery_switch.state != "on":
        _LOGGER.warning("Recovery switch is OFF - Aborting recovery sequence")
        return

    _LOGGER.info("═══ FLAMEOUT RECOVERY SEQUENCE STARTING ═══")
    _LOGGER.info("Device: %s | Attempts: %d | Delay: %ds | Cooling wait: %ds | Off wait: %ds", 
                device_name, retry_attempts, retry_delay, cooling_wait, off_wait)
    
    # Send notification for recovery sequence start
    await hass.services.async_call(
        "persistent_notification",
        "create",
        {
            "title": "═══ Recovery Sequence Starting ═══",
            "message": f"Device: {device_name}\nAttempts: {retry_attempts}\nDelay: {retry_delay}s\nCooling wait: {cooling_wait}s\nOff wait: {off_wait}s",
            "notification_id": "afterburner_recovery_sequence"
        }
    )

    for attempt in range(retry_attempts):
        _LOGGER.info("─── Attempt %d of %d ───", attempt + 1, retry_attempts)
        
        # Send notification for attempt start
        await hass.services.async_call(
            "persistent_notification",
            "create",
            {
                "title": f"─── Attempt {attempt + 1} of {retry_attempts} ───",
                "message": f"Step 1: Waiting for cooling cycle (max {cooling_wait}s)...",
                "notification_id": "afterburner_recovery_progress"
            }
        )
        
        # Step 1: Verify status of heater - check if cooling or fans still running
        await _async_wait_for_heater_ready(hass, cooling_wait)
        
        # Send notification for step 2
        await hass.services.async_call(
            "persistent_notification",
            "create",
            {
                "title": f"─── Attempt {attempt + 1} of {retry_attempts} ───",
                "message": f"Step 2: Waiting for off state (max {off_wait}s)...",
                "notification_id": "afterburner_recovery_progress"
            }
        )
        
        # Step 2: Wait for ready heater - off state
        await _async_wait_for_heater_off(hass, off_wait)
        
        # Send notification for step 3
        await hass.services.async_call(
            "persistent_notification",
            "create",
            {
                "title": f"─── Attempt {attempt + 1} of {retry_attempts} ───",
                "message": "Step 3: Sending restart command...",
                "notification_id": "afterburner_recovery_progress"
            }
        )
        
        # Step 3: Turn on heater using climate entity
        await hass.services.async_call(
            "climate",
            "set_hvac_mode",
            {
                "entity_id": "climate.afterburner",
                "hvac_mode": "heat"
            },
            blocking=True
        )
        
        _LOGGER.info("Heater start command sent for %s, waiting %d seconds before next attempt", 
                    device_name, retry_delay)
        
        # Send notification for step 4
        await hass.services.async_call(
            "persistent_notification",
            "create",
            {
                "title": f"─── Attempt {attempt + 1} of {retry_attempts} ───",
                "message": f"Step 4: Monitoring result ({retry_delay}s)...",
                "notification_id": "afterburner_recovery_progress"
            }
        )
        
        # Step 4: Wait for configured delay - heater will generate its own errors
        await asyncio.sleep(retry_delay)
        
        # Check if error is resolved AND heater is actually running
        error_state = hass.states.get("sensor.afterburner_error_state")
        run_state = hass.states.get("sensor.afterburner_run_state")
        
        if error_state and error_state.state == "E-00: OK":
            # Also verify the heater is actually running
            if run_state and run_state.state == "Running":
                _LOGGER.info("✓✓✓ RECOVERY SUCCESSFUL - Heater restarted after %d attempt(s) ✓✓✓", attempt + 1)
                
                # Send success notification
                await hass.services.async_call(
                    "persistent_notification",
                    "create",
                    {
                        "title": "✓✓✓ RECOVERY SUCCESSFUL ✓✓✓",
                        "message": f"Heater restarted successfully after {attempt + 1} attempt(s)!",
                        "notification_id": "afterburner_recovery_success"
                    }
                )
                return
            else:
                _LOGGER.warning("Error cleared but heater not running yet (state: %s), continuing to next attempt", 
                               run_state.state if run_state else "unknown")
    
    _LOGGER.error("❌❌❌ RECOVERY FAILED - All %d attempts exhausted ❌❌❌", retry_attempts)
    
    # Send failure notification
    await hass.services.async_call(
        "persistent_notification",
        "create",
        {
            "title": "❌❌❌ RECOVERY FAILED ❌❌❌",
            "message": f"All {retry_attempts} restart attempts failed. Manual intervention required!",
            "notification_id": "afterburner_recovery_failed"
        }
    )


async def _async_wait_for_heater_ready(hass: HomeAssistant, max_wait_time: int) -> None:
    """Wait for heater to be ready (not cooling, fans stopped)."""
    _LOGGER.info("Waiting for heater to be ready (cooling cycle complete)... Max wait: %d seconds", max_wait_time)
    
    check_interval = 10  # Check every 10 seconds
    
    for _ in range(max_wait_time // check_interval):
        # Check run state - should not be "Cooling" or "Stopping"
        run_state = hass.states.get("sensor.afterburner_run_state")
        if run_state and run_state.state not in ("Cooling", "Stopping", "Running"):
            _LOGGER.info("Heater ready state detected: %s", run_state.state)
            return
        
        # Check fan speed - should be 0 or very low
        fan_speed = hass.states.get("sensor.afterburner_fan_speed")
        if fan_speed and fan_speed.state not in ("unknown", "unavailable"):
            try:
                speed = float(fan_speed.state)
                if speed < 100:  # Fan speed below 100 RPM indicates ready
                    _LOGGER.info("Fan speed indicates heater ready: %s RPM", speed)
                    return
            except (ValueError, TypeError):
                pass
        
        await asyncio.sleep(check_interval)
    
    _LOGGER.warning("Heater did not reach ready state within %d seconds", max_wait_time)


async def _async_wait_for_heater_off(hass: HomeAssistant, max_wait_time: int) -> None:
    """Wait for heater to be completely off."""
    _LOGGER.info("Waiting for heater to be completely off... Max wait: %d seconds", max_wait_time)
    
    check_interval = 5   # Check every 5 seconds
    
    for _ in range(max_wait_time // check_interval):
        # Check run state - should be "Off" or "Stopped"
        run_state = hass.states.get("sensor.afterburner_run_state")
        if run_state and run_state.state in ("Off", "Stopped", "Stopped/Ready"):
            _LOGGER.info("Heater confirmed off: %s", run_state.state)
            return
        
        await asyncio.sleep(check_interval)
    
    _LOGGER.warning("Heater did not reach off state within %d seconds", max_wait_time)
