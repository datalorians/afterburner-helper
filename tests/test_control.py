from __future__ import annotations

from pathlib import Path
import sys
import unittest

sys.path.insert(
    0,
    str(Path(__file__).resolve().parents[1] / "custom_components" / "afterburner_helper"),
)

from control import (
    ControlAction,
    CycleMode,
    FlameoutDetector,
    EarlyRecoveryController,
    FlameoutWarning,
    RecoveryAction,
    RecoveryConfig,
    RunPhase,
    Telemetry,
    ThermalCycleConfig,
    ThermalCycleController,
    WarningCode,
    normalize_run_state,
)


def sample(
    timestamp: float,
    *,
    state: str = "Running",
    pump: float = 1.2,
    fan: float = 1776,
    body: float = 131,
    room: float = 25,
    setpoint: float = 25,
    volts: float = 14.2,
    glow: float = 0,
    error: str = "E-00: OK",
) -> Telemetry:
    return Telemetry(timestamp, state, error, pump, fan, body, room, setpoint, volts, glow)


class StateNormalizationTests(unittest.TestCase):
    def test_real_ready_state_whitespace_is_normalized(self) -> None:
        self.assertIs(normalize_run_state(" Stopped/Ready "), RunPhase.OFF)

    def test_v352_states_are_recognized(self) -> None:
        self.assertIs(normalize_run_state("Heating glow plug"), RunPhase.PREHEAT)
        self.assertIs(normalize_run_state("Igniting..."), RunPhase.IGNITING)
        self.assertIs(normalize_run_state("Shutting down"), RunPhase.STOPPING)


class DetectionTests(unittest.TestCase):
    def test_known_good_overnight_low_fire_does_not_warn(self) -> None:
        detector = FlameoutDetector()
        warnings = []
        for minute in range(12):
            warnings = detector.update(sample(minute * 60, body=132 - min(minute, 2)))
        self.assertEqual(warnings, [])

    def test_historical_ramp_collapse_warns(self) -> None:
        detector = FlameoutDetector()
        detector.update(sample(0, state="Ignited", pump=3.1, fan=4100, body=68))
        detector.update(sample(30, state="Ignited", pump=3.8, fan=4450, body=60))
        warnings = detector.update(sample(60, state="Ignited", pump=3.9, fan=4460, body=51))
        self.assertIn(WarningCode.RAMP_TEMPERATURE_COLLAPSE, {item.code for item in warnings})

    def test_historical_low_fire_collapse_warns(self) -> None:
        detector = FlameoutDetector()
        warnings = []
        for minute in range(11):
            body = 95 - minute * 2 if minute < 8 else 79 - (minute - 8) * 6
            warnings = detector.update(sample(minute * 60, pump=1.2, fan=2000, body=body))
        codes = {item.code for item in warnings}
        self.assertIn(WarningCode.LOW_FIRE_UNSTABLE, codes)
        self.assertIn(WarningCode.PROBABLE_FLAME_LOSS, codes)


class ThermalCycleTests(unittest.TestCase):
    def setUp(self) -> None:
        self.controller = ThermalCycleController(
            ThermalCycleConfig(
                enabled=True,
                temperature_hold_s=120,
                minimum_pump_hold_s=120,
                minimum_run_s=300,
                minimum_off_s=300,
            )
        )

    def test_stops_at_setpoint_plus_five_only_at_minimum_fire(self) -> None:
        self.controller.update(sample(0, room=25), run_request_armed=True)
        self.controller.update(sample(300, room=30, pump=1.2), run_request_armed=True)
        decision = self.controller.update(sample(421, room=30, pump=1.2), run_request_armed=True)
        self.assertIs(decision.action, ControlAction.NORMAL_STOP)
        self.assertIs(decision.mode, CycleMode.AUTO_STOPPED)

    def test_does_not_stop_above_threshold_when_not_at_minimum(self) -> None:
        self.controller.update(sample(0, room=25), run_request_armed=True)
        self.controller.update(sample(300, room=30, pump=2.0), run_request_armed=True)
        decision = self.controller.update(sample(500, room=31, pump=2.0), run_request_armed=True)
        self.assertIs(decision.action, ControlAction.NONE)

    def test_auto_stopped_heater_restarts_at_setpoint_minus_five(self) -> None:
        self.controller.update(sample(0), run_request_armed=True)
        self.controller.update(sample(300, room=30), run_request_armed=True)
        stop = self.controller.update(sample(421, room=30), run_request_armed=True)
        self.assertIs(stop.action, ControlAction.NORMAL_STOP)

        self.controller.update(sample(500, state="Cooling", pump=0, fan=3000, body=80, room=25), run_request_armed=True)
        self.controller.update(sample(721, state=" Stopped/Ready ", pump=0, fan=0, body=30, room=20), run_request_armed=True)
        start = self.controller.update(sample(842, state=" Stopped/Ready ", pump=0, fan=0, body=25, room=20), run_request_armed=True)
        self.assertIs(start.action, ControlAction.NORMAL_START)
        self.assertIs(start.mode, CycleMode.RESTART_PENDING)

    def test_manual_stop_cancels_restart(self) -> None:
        self.controller.memory.auto_stopped = True
        self.controller.memory.auto_stopped_at = 0
        self.controller.manual_stop()
        decision = self.controller.update(
            sample(1000, state="Stopped/Ready", pump=0, fan=0, room=19),
            run_request_armed=False,
        )
        self.assertIs(decision.action, ControlAction.NONE)
        self.assertFalse(self.controller.memory.auto_stopped)
        self.assertTrue(self.controller.memory.manual_stop_latched)

    def test_manual_stop_stays_off_without_a_setpoint_change(self) -> None:
        self.controller.update(
            sample(0, state="Stopped/Ready", pump=0, fan=0, room=20, setpoint=25),
            run_request_armed=False,
        )
        self.controller.manual_stop()
        decision = self.controller.update(
            sample(1000, state="Stopped/Ready", pump=0, fan=0, room=15, setpoint=25),
            run_request_armed=False,
        )
        self.assertIs(decision.action, ControlAction.NONE)
        self.assertIs(decision.mode, CycleMode.MANUAL_STOPPED)
        self.assertTrue(self.controller.memory.manual_stop_latched)

    def test_setpoint_change_outside_start_range_stays_off(self) -> None:
        self.controller.update(
            sample(0, state="Stopped/Ready", pump=0, fan=0, room=20, setpoint=25),
            run_request_armed=False,
        )
        self.controller.manual_stop()
        decision = self.controller.update(
            sample(1000, state="Stopped/Ready", pump=0, fan=0, room=20, setpoint=22),
            run_request_armed=False,
        )
        self.assertIs(decision.action, ControlAction.NONE)
        self.assertIs(decision.mode, CycleMode.MANUAL_STOPPED)
        self.assertTrue(self.controller.memory.manual_stop_latched)

    def test_setpoint_change_into_start_range_starts_when_fully_cooled(self) -> None:
        self.controller.update(
            sample(0, state="Stopped/Ready", pump=0, fan=0, room=20, setpoint=25),
            run_request_armed=False,
        )
        self.controller.manual_stop()
        start = self.controller.update(
            sample(1000, state="Stopped/Ready", pump=0, fan=0, room=20, setpoint=30),
            run_request_armed=False,
        )
        self.assertIs(start.action, ControlAction.NORMAL_START)
        self.assertIs(start.mode, CycleMode.RESTART_PENDING)
        self.assertFalse(self.controller.memory.manual_stop_latched)

    def test_missing_sensor_inhibits_without_latching_lockout(self) -> None:
        missing = sample(0, room=25)
        missing = Telemetry(
            missing.timestamp,
            missing.run_state,
            missing.error,
            missing.pump_hz,
            missing.fan_rpm,
            missing.body_c,
            None,
            missing.setpoint_c,
            missing.input_v,
            missing.glow_v,
        )
        inhibited = self.controller.update(missing, run_request_armed=True)
        self.assertIs(inhibited.mode, CycleMode.INHIBITED)
        recovered = self.controller.update(sample(10), run_request_armed=True)
        self.assertIs(recovered.mode, CycleMode.MONITORING)


class EarlyRecoveryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.controller = EarlyRecoveryController(
            RecoveryConfig(
                enabled=True,
                boost_setpoint_c=35,
                response_timeout_s=90,
                required_temperature_rise_c=5,
            )
        )
        self.warning = FlameoutWarning(
            WarningCode.LOW_FIRE_UNSTABLE,
            "historical low-fire signature",
        )

    def test_one_bounded_boost_then_restore_on_success(self) -> None:
        boost = self.controller.update(sample(0, body=85, setpoint=20), [self.warning])
        self.assertIs(boost.action, RecoveryAction.BOOST)
        self.assertEqual(boost.target_setpoint_c, 35)
        restore = self.controller.update(sample(91, body=92, setpoint=35), [])
        self.assertIs(restore.action, RecoveryAction.RESTORE)
        self.assertEqual(restore.target_setpoint_c, 20)

    def test_failed_response_restores_and_stops(self) -> None:
        self.controller.update(sample(0, body=85, setpoint=20), [self.warning])
        failed = self.controller.update(sample(91, body=83, setpoint=35), [])
        self.assertIs(failed.action, RecoveryAction.RESTORE_AND_STOP)

    def test_only_one_attempt_per_running_session(self) -> None:
        self.controller.update(sample(0, body=85, setpoint=20), [self.warning])
        self.controller.update(sample(91, body=92, setpoint=35), [])
        again = self.controller.update(sample(120, body=85, setpoint=20), [self.warning])
        self.assertIs(again.action, RecoveryAction.NONE)


if __name__ == "__main__":
    unittest.main()
