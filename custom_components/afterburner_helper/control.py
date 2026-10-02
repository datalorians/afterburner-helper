"""Pure control and detection logic for the Afterburner helper redesign.

No function in this module sends a command.  Home Assistant adapters consume
the decisions and enforce feature enables, service calls, and persistence.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from enum import StrEnum


class RunPhase(StrEnum):
    OFF = "off"
    STARTING = "starting"
    PREHEAT = "preheat"
    IGNITING = "igniting"
    IGNITED = "ignited"
    RUNNING = "running"
    STOPPING = "stopping"
    COOLING = "cooling"
    UNKNOWN = "unknown"


class WarningCode(StrEnum):
    RAMP_TEMPERATURE_COLLAPSE = "ramp_temperature_collapse"
    LOW_FIRE_UNSTABLE = "low_fire_unstable"
    PROBABLE_FLAME_LOSS = "probable_flame_loss"


class ControlAction(StrEnum):
    NONE = "none"
    NORMAL_STOP = "normal_stop"
    NORMAL_START = "normal_start"


class RecoveryAction(StrEnum):
    NONE = "none"
    BOOST = "boost"
    RESTORE = "restore"
    RESTORE_AND_STOP = "restore_and_stop"


class CycleMode(StrEnum):
    DISABLED = "disabled"
    INHIBITED = "inhibited"
    MONITORING = "monitoring"
    AUTO_STOPPED = "auto_stopped"
    MANUAL_STOPPED = "manual_stopped"
    RESTART_PENDING = "restart_pending"
    LOCKED_OUT = "locked_out"


def normalize_run_state(value: str | None) -> RunPhase:
    """Normalize the exact and inconsistent strings published by V3.5.2."""
    normalized = " ".join((value or "").strip().lower().split())
    return {
        "off": RunPhase.OFF,
        "stopped": RunPhase.OFF,
        "stopped/ready": RunPhase.OFF,
        "starting": RunPhase.STARTING,
        "starting...": RunPhase.STARTING,
        "heating glow plug": RunPhase.PREHEAT,
        "igniting": RunPhase.IGNITING,
        "igniting...": RunPhase.IGNITING,
        "ignition retry": RunPhase.IGNITING,
        "ignited": RunPhase.IGNITED,
        "running": RunPhase.RUNNING,
        "shutting down": RunPhase.STOPPING,
        "stopping": RunPhase.STOPPING,
        "cooling": RunPhase.COOLING,
    }.get(normalized, RunPhase.UNKNOWN)


@dataclass(frozen=True, slots=True)
class Telemetry:
    timestamp: float
    run_state: str
    error: str
    pump_hz: float | None
    fan_rpm: float | None
    body_c: float | None
    room_c: float | None
    setpoint_c: float | None
    input_v: float | None
    glow_v: float | None = None

    @property
    def phase(self) -> RunPhase:
        return normalize_run_state(self.run_state)

    @property
    def error_ok(self) -> bool:
        return self.error.strip().upper().startswith("E-00")


@dataclass(frozen=True, slots=True)
class FlameoutWarning:
    code: WarningCode
    detail: str


class FlameoutDetector:
    """Detect signatures found in the two recorded E-08 traces."""

    def __init__(self) -> None:
        self._history: deque[Telemetry] = deque()

    def update(self, sample: Telemetry) -> list[FlameoutWarning]:
        self._history.append(sample)
        cutoff = sample.timestamp - 660
        while self._history and self._history[0].timestamp < cutoff:
            self._history.popleft()
        return self._classify(sample)

    def _window(self, seconds: float) -> list[Telemetry]:
        if not self._history:
            return []
        cutoff = self._history[-1].timestamp - seconds
        return [sample for sample in self._history if sample.timestamp >= cutoff]

    def _at_or_before(self, timestamp: float) -> Telemetry | None:
        for sample in reversed(self._history):
            if sample.timestamp <= timestamp:
                return sample
        return None

    def _temperature_drop(self, seconds: float) -> float | None:
        current = self._history[-1]
        prior = self._at_or_before(current.timestamp - seconds)
        if prior is None or prior.body_c is None or current.body_c is None:
            return None
        return prior.body_c - current.body_c

    def _continuous_low_fire(self, seconds: float) -> bool:
        current = self._history[-1]
        samples = self._window(seconds)
        if not samples or samples[0].timestamp > current.timestamp - seconds + 15:
            return False
        return all(
            sample.phase is RunPhase.RUNNING
            and sample.pump_hz is not None
            and 0 < sample.pump_hz <= 1.5
            for sample in samples
        )

    def _classify(self, sample: Telemetry) -> list[FlameoutWarning]:
        if sample.pump_hz is None or sample.fan_rpm is None or sample.body_c is None:
            return []

        warnings: list[FlameoutWarning] = []
        prior_60 = self._at_or_before(sample.timestamp - 60)
        ramp_window = self._window(90)
        ramp_temperatures = [point.body_c for point in ramp_window if point.body_c is not None]
        ramp_drop = max(ramp_temperatures) - sample.body_c if ramp_temperatures else 0
        demand_not_falling = (
            prior_60 is not None
            and prior_60.pump_hz is not None
            and prior_60.fan_rpm is not None
            and (sample.pump_hz >= prior_60.pump_hz or sample.fan_rpm >= prior_60.fan_rpm)
        )

        if (
            sample.phase is RunPhase.IGNITED
            and (sample.glow_v is None or sample.glow_v <= 0.5)
            and sample.pump_hz > 2
            and ramp_drop >= 8
            and demand_not_falling
        ):
            warnings.append(
                FlameoutWarning(
                    WarningCode.RAMP_TEMPERATURE_COLLAPSE,
                    f"body temperature fell {ramp_drop:.1f} C from its 90-second peak while demand did not fall",
                )
            )

        drop_180 = self._temperature_drop(180)
        low_window = self._window(600)
        low_temperatures = [point.body_c for point in low_window if point.body_c is not None]
        low_span = max(low_temperatures) - min(low_temperatures) if low_temperatures else 0
        if (
            sample.phase is RunPhase.RUNNING
            and self._continuous_low_fire(600)
            and sample.body_c < 100
            and ((drop_180 is not None and drop_180 >= 8) or low_span >= 15)
        ):
            warnings.append(
                FlameoutWarning(
                    WarningCode.LOW_FIRE_UNSTABLE,
                    f"low fire is {sample.body_c:.1f} C with a 3-minute drop of {drop_180 or 0:.1f} C and 10-minute span of {low_span:.1f} C",
                )
            )

        drop_60 = self._temperature_drop(60)
        if (
            sample.phase in {RunPhase.IGNITED, RunPhase.RUNNING}
            and sample.pump_hz > 0
            and sample.body_c < 70
            and drop_60 is not None
            and drop_60 >= 2
        ):
            warnings.append(
                FlameoutWarning(
                    WarningCode.PROBABLE_FLAME_LOSS,
                    f"pump remains active at {sample.body_c:.1f} C after a {drop_60:.1f} C/60-second fall",
                )
            )
        return warnings


@dataclass(frozen=True, slots=True)
class ThermalCycleConfig:
    enabled: bool = False
    stop_offset_c: float = 5.0
    start_offset_c: float = 5.0
    temperature_hold_s: float = 120.0
    minimum_pump_hold_s: float = 180.0
    minimum_run_s: float = 1800.0
    minimum_off_s: float = 600.0
    minimum_pump_hz: float = 1.2
    minimum_pump_tolerance_hz: float = 0.05
    minimum_voltage: float = 11.5
    maximum_starts_per_hour: int = 2


@dataclass(slots=True)
class ThermalCycleMemory:
    mode: CycleMode = CycleMode.DISABLED
    auto_stopped: bool = False
    auto_stopped_at: float | None = None
    run_started_at: float | None = None
    over_temperature_since: float | None = None
    minimum_pump_since: float | None = None
    under_temperature_since: float | None = None
    restart_commanded_at: float | None = None
    manual_stop_latched: bool = False
    last_setpoint_c: float | None = None
    lockout_reason: str | None = None
    start_times: deque[float] = field(default_factory=deque)


@dataclass(frozen=True, slots=True)
class ControlDecision:
    action: ControlAction
    mode: CycleMode
    reason: str


class ThermalCycleController:
    """Stateful setpoint-demand controller with a manual-stop latch."""

    def __init__(self, config: ThermalCycleConfig, memory: ThermalCycleMemory | None = None) -> None:
        self.config = config
        self.memory = memory or ThermalCycleMemory()
        self._last_phase = RunPhase.UNKNOWN

    def manual_stop(self) -> None:
        """Latch Off until a later setpoint change enters the start range."""
        self.memory.auto_stopped = False
        self.memory.auto_stopped_at = None
        self.memory.restart_commanded_at = None
        self.memory.under_temperature_since = None
        self.memory.manual_stop_latched = True
        self.memory.mode = CycleMode.MANUAL_STOPPED if self.config.enabled else CycleMode.DISABLED

    def disable(self, setpoint_c: float | None) -> None:
        """Observe the current setpoint without treating enable as an adjustment."""
        self.manual_stop()
        self.memory.last_setpoint_c = setpoint_c
        self.memory.mode = CycleMode.DISABLED

    def clear_lockout(self) -> None:
        self.memory.lockout_reason = None
        self.memory.mode = CycleMode.MONITORING if self.config.enabled else CycleMode.DISABLED

    def update(self, sample: Telemetry, *, run_request_armed: bool) -> ControlDecision:
        now = sample.timestamp
        phase = sample.phase
        self._record_transitions(phase, now)

        setpoint_changed = self._setpoint_changed(sample.setpoint_c)

        if not self.config.enabled:
            self.memory.mode = CycleMode.DISABLED
            return ControlDecision(ControlAction.NONE, self.memory.mode, "automatic temperature cycling is disabled")

        if self.memory.lockout_reason:
            self.memory.mode = CycleMode.LOCKED_OUT
            return ControlDecision(ControlAction.NONE, self.memory.mode, self.memory.lockout_reason)

        if not sample.error_ok:
            return self._lock_out(f"controller error is {sample.error}")
        if sample.room_c is None or sample.setpoint_c is None:
            self.memory.mode = CycleMode.INHIBITED
            return ControlDecision(
                ControlAction.NONE,
                self.memory.mode,
                "room temperature or setpoint is unavailable",
            )
        if sample.input_v is None or sample.input_v < self.config.minimum_voltage:
            self.memory.mode = CycleMode.INHIBITED
            return ControlDecision(
                ControlAction.NONE,
                self.memory.mode,
                "input voltage is unavailable or below the configured minimum",
            )

        if self.memory.auto_stopped:
            return self._while_auto_stopped(sample, run_request_armed)
        if sample.phase in {RunPhase.OFF, RunPhase.COOLING, RunPhase.STOPPING}:
            return self._while_manually_stopped(sample, setpoint_changed)
        return self._while_running(sample)

    def _setpoint_changed(self, setpoint_c: float | None) -> bool:
        if setpoint_c is None:
            return False
        previous = self.memory.last_setpoint_c
        self.memory.last_setpoint_c = setpoint_c
        return previous is not None and abs(setpoint_c - previous) >= 0.05

    def _record_transitions(self, phase: RunPhase, now: float) -> None:
        if phase is RunPhase.RUNNING and self._last_phase is not RunPhase.RUNNING:
            self.memory.run_started_at = now
            if self.memory.restart_commanded_at is not None:
                self.memory.start_times.append(now)
                self.memory.restart_commanded_at = None
                self.memory.auto_stopped = False
        self._last_phase = phase
        while self.memory.start_times and self.memory.start_times[0] < now - 3600:
            self.memory.start_times.popleft()

    def _while_running(self, sample: Telemetry) -> ControlDecision:
        now = sample.timestamp
        self.memory.mode = CycleMode.MONITORING
        if sample.phase is not RunPhase.RUNNING or sample.pump_hz is None:
            self.memory.over_temperature_since = None
            self.memory.minimum_pump_since = None
            return ControlDecision(ControlAction.NONE, self.memory.mode, "heater is not in a controllable running state")

        upper = sample.setpoint_c + self.config.stop_offset_c
        if sample.room_c >= upper:
            if self.memory.over_temperature_since is None:
                self.memory.over_temperature_since = now
        else:
            self.memory.over_temperature_since = None

        if sample.pump_hz <= self.config.minimum_pump_hz + self.config.minimum_pump_tolerance_hz:
            if self.memory.minimum_pump_since is None:
                self.memory.minimum_pump_since = now
        else:
            self.memory.minimum_pump_since = None

        run_started_at = self.memory.run_started_at if self.memory.run_started_at is not None else now
        runtime = now - run_started_at
        temperature_held = (
            self.memory.over_temperature_since is not None
            and now - self.memory.over_temperature_since >= self.config.temperature_hold_s
        )
        minimum_held = (
            self.memory.minimum_pump_since is not None
            and now - self.memory.minimum_pump_since >= self.config.minimum_pump_hold_s
        )
        if temperature_held and minimum_held and runtime >= self.config.minimum_run_s:
            self.memory.auto_stopped = True
            self.memory.auto_stopped_at = now
            self.memory.under_temperature_since = None
            self.memory.manual_stop_latched = False
            self.memory.mode = CycleMode.AUTO_STOPPED
            return ControlDecision(
                ControlAction.NORMAL_STOP,
                self.memory.mode,
                f"room temperature {sample.room_c:.1f} C remained above {upper:.1f} C while the pump remained at minimum",
            )
        return ControlDecision(ControlAction.NONE, self.memory.mode, "upper threshold or minimum-output hold has not been satisfied")

    def _while_manually_stopped(
        self,
        sample: Telemetry,
        setpoint_changed: bool,
    ) -> ControlDecision:
        """Require a new, demanding setpoint before automatic startup."""
        self.memory.mode = CycleMode.MANUAL_STOPPED
        self.memory.manual_stop_latched = True
        start_threshold = sample.setpoint_c - self.config.start_offset_c

        if not setpoint_changed:
            return ControlDecision(
                ControlAction.NONE,
                self.memory.mode,
                "heater is manually stopped; waiting for a setpoint adjustment into the start range",
            )
        if sample.room_c > start_threshold:
            return ControlDecision(
                ControlAction.NONE,
                self.memory.mode,
                f"setpoint changed, but room temperature {sample.room_c:.1f} C is above the {start_threshold:.1f} C start threshold",
            )

        self.memory.manual_stop_latched = False
        self.memory.auto_stopped = True
        # Stopped/Ready with a stopped fan proves the stock cooldown is already
        # complete.  A change during Cooling/Stopping still observes minimum-off.
        fully_cooled = sample.phase is RunPhase.OFF and (
            sample.fan_rpm is None or sample.fan_rpm < 100
        )
        self.memory.auto_stopped_at = (
            sample.timestamp - self.config.minimum_off_s
            if fully_cooled
            else sample.timestamp
        )
        self.memory.under_temperature_since = (
            sample.timestamp - self.config.temperature_hold_s
            if fully_cooled
            else sample.timestamp
        )
        return self._while_auto_stopped(sample, True)

    def _while_auto_stopped(self, sample: Telemetry, run_request_armed: bool) -> ControlDecision:
        now = sample.timestamp
        self.memory.mode = CycleMode.AUTO_STOPPED
        if not run_request_armed:
            self.manual_stop()
            return ControlDecision(ControlAction.NONE, self.memory.mode, "run request was disarmed; automatic restart cancelled")

        if self.memory.restart_commanded_at is not None:
            self.memory.mode = CycleMode.RESTART_PENDING
            return ControlDecision(
                ControlAction.NONE,
                self.memory.mode,
                "restart was already commanded; waiting for the heater to reach Running",
            )

        if sample.phase not in {RunPhase.OFF, RunPhase.COOLING, RunPhase.STOPPING}:
            return ControlDecision(ControlAction.NONE, self.memory.mode, "waiting for the stock ECU stop/cooldown sequence")
        if sample.phase is not RunPhase.OFF or (sample.fan_rpm is not None and sample.fan_rpm >= 100):
            return ControlDecision(ControlAction.NONE, self.memory.mode, "waiting for Stopped/Ready with the fan stopped")

        lower = sample.setpoint_c - self.config.start_offset_c
        if sample.room_c <= lower:
            if self.memory.under_temperature_since is None:
                self.memory.under_temperature_since = now
        else:
            self.memory.under_temperature_since = None

        auto_stopped_at = self.memory.auto_stopped_at if self.memory.auto_stopped_at is not None else now
        off_time = now - auto_stopped_at
        temperature_held = (
            self.memory.under_temperature_since is not None
            and now - self.memory.under_temperature_since >= self.config.temperature_hold_s
        )
        if len(self.memory.start_times) >= self.config.maximum_starts_per_hour:
            return self._lock_out("maximum automatic starts per hour reached")
        if off_time >= self.config.minimum_off_s and temperature_held:
            self.memory.mode = CycleMode.RESTART_PENDING
            self.memory.restart_commanded_at = now
            return ControlDecision(
                ControlAction.NORMAL_START,
                self.memory.mode,
                f"room temperature {sample.room_c:.1f} C remained below {lower:.1f} C after full cooldown",
            )
        return ControlDecision(ControlAction.NONE, self.memory.mode, "lower threshold hold or minimum off time has not been satisfied")

    def _lock_out(self, reason: str) -> ControlDecision:
        self.memory.lockout_reason = reason
        self.memory.mode = CycleMode.LOCKED_OUT
        return ControlDecision(ControlAction.NONE, self.memory.mode, reason)


@dataclass(frozen=True, slots=True)
class RecoveryConfig:
    enabled: bool = False
    boost_setpoint_c: float = 35.0
    response_timeout_s: float = 120.0
    required_temperature_rise_c: float = 5.0


@dataclass(slots=True)
class RecoveryMemory:
    active: bool = False
    attempted_this_run: bool = False
    started_at: float | None = None
    starting_body_c: float | None = None
    original_setpoint_c: float | None = None
    lockout_reason: str | None = None


@dataclass(frozen=True, slots=True)
class RecoveryDecision:
    action: RecoveryAction
    reason: str
    target_setpoint_c: float | None = None


class EarlyRecoveryController:
    """Bounded one-attempt recovery for the validated low-fire signature."""

    def __init__(self, config: RecoveryConfig, memory: RecoveryMemory | None = None) -> None:
        self.config = config
        self.memory = memory or RecoveryMemory()
        self._last_phase = RunPhase.UNKNOWN

    def manual_stop(self) -> None:
        """Cancel recovery immediately when a person takes control."""
        self.memory.active = False
        self.memory.started_at = None
        self.memory.starting_body_c = None
        self.memory.original_setpoint_c = None
        self.memory.lockout_reason = "manual stop cancelled automatic recovery"

    def update(
        self,
        sample: Telemetry,
        warnings: list[FlameoutWarning] | tuple[FlameoutWarning, ...],
    ) -> RecoveryDecision:
        phase = sample.phase
        if phase is RunPhase.RUNNING and self._last_phase is not RunPhase.RUNNING:
            self.memory.attempted_this_run = False
            self.memory.active = False
            self.memory.lockout_reason = None
        self._last_phase = phase

        if not self.config.enabled:
            return RecoveryDecision(RecoveryAction.NONE, "early recovery is disabled")
        if self.memory.lockout_reason:
            return RecoveryDecision(RecoveryAction.NONE, self.memory.lockout_reason)
        if not sample.error_ok:
            self.memory.lockout_reason = f"controller error is {sample.error}"
            return RecoveryDecision(RecoveryAction.NONE, self.memory.lockout_reason)

        codes = {warning.code for warning in warnings}
        if self.memory.active:
            if sample.phase is not RunPhase.RUNNING:
                self.memory.active = False
                self.memory.lockout_reason = "heater left Running during recovery"
                return RecoveryDecision(
                    RecoveryAction.RESTORE_AND_STOP,
                    self.memory.lockout_reason,
                    self.memory.original_setpoint_c,
                )
            if WarningCode.PROBABLE_FLAME_LOSS in codes:
                self.memory.active = False
                self.memory.lockout_reason = "probable flame loss detected during recovery"
                return RecoveryDecision(
                    RecoveryAction.RESTORE_AND_STOP,
                    self.memory.lockout_reason,
                    self.memory.original_setpoint_c,
                )
            started_at = (
                self.memory.started_at
                if self.memory.started_at is not None
                else sample.timestamp
            )
            elapsed = sample.timestamp - started_at
            if elapsed >= self.config.response_timeout_s:
                starting_body = self.memory.starting_body_c
                recovered = (
                    starting_body is not None
                    and sample.body_c is not None
                    and sample.body_c - starting_body >= self.config.required_temperature_rise_c
                )
                self.memory.active = False
                if recovered:
                    return RecoveryDecision(
                        RecoveryAction.RESTORE,
                        "body temperature recovered within the bounded response window",
                        self.memory.original_setpoint_c,
                    )
                self.memory.lockout_reason = "body temperature did not recover within the bounded response window"
                return RecoveryDecision(
                    RecoveryAction.RESTORE_AND_STOP,
                    self.memory.lockout_reason,
                    self.memory.original_setpoint_c,
                )
            return RecoveryDecision(RecoveryAction.NONE, "bounded recovery is in progress")

        if (
            WarningCode.LOW_FIRE_UNSTABLE in codes
            and not self.memory.attempted_this_run
            and sample.phase is RunPhase.RUNNING
            and sample.body_c is not None
            and sample.setpoint_c is not None
        ):
            self.memory.active = True
            self.memory.attempted_this_run = True
            self.memory.started_at = sample.timestamp
            self.memory.starting_body_c = sample.body_c
            self.memory.original_setpoint_c = sample.setpoint_c
            return RecoveryDecision(
                RecoveryAction.BOOST,
                "validated low-fire instability signature detected",
                self.config.boost_setpoint_c,
            )
        return RecoveryDecision(RecoveryAction.NONE, "no recovery action is required")
