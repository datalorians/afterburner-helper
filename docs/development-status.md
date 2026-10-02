# Development status

This file tracks the remaining work needed to make Home Assistant a complete
replacement for the Afterburner web interface.

## Implemented

- Active mixture map: minimum/maximum pump frequency and fan speed
- Pump calibration and four environmental sensor offsets
- Thermostat method/window and live thermostat enable
- Cyclic pivot, start, and stop thresholds
- Frost start and temperature-rise thresholds
- Fan sensor type, 12/24 V system selection, and low-voltage cutout
- GPIO input/output state, modes, analogue value, user outputs, and thresholds
- BME altitude/humidity and controller hardware/status telemetry
- Firmware version/date, uptime, free memory, heater runtime, and glow runtime
- Refresh commands and the controller's two-step MQTT reboot handshake
- Configurable fused indoor temperature and outdoor reference/delta logging

## Next implementation groups

1. Model all 14 indexed timers as native Home Assistant time, day, repeat, and
   demand controls. Timer MQTT payloads include a one-based record number and
   therefore cannot use the ordinary one-key setting entities.
2. Add a bounded log/console viewer. Afterburner's web console is a websocket
   stream, not a JSONout MQTT setting, so this requires a separate local client.
3. Add firmware-management status without exposing network credentials.

## Firmware limitations

The current Afterburner source does not provide writable MQTT commands for the
four alternate altitude-indexed mixture maps or GPIO pin-mode assignment.
Home Assistant can display reported altitude and GPIO modes, but controls for
those items would be misleading until the controller firmware gains commands.
