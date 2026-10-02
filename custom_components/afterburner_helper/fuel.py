"""Canonical fuel calculations for the Afterburner helper.

This module deliberately has no Home Assistant dependencies so the arithmetic
can be tested independently from entities, MQTT, and the recorder.
"""

from __future__ import annotations

from dataclasses import dataclass


SECONDS_PER_HOUR = 3600.0
MILLILITRES_PER_LITRE = 1000.0


@dataclass(frozen=True, slots=True)
class FuelConfig:
    """Inputs that define the single supported fuel model."""

    tank_capacity_l: float = 20.0
    pump_ml_per_stroke: float = 0.022
    usage_correction_factor: float = 1.0
    maximum_pump_hz: float = 3.9

    def validate(self) -> None:
        if self.tank_capacity_l <= 0:
            raise ValueError("tank capacity must be positive")
        if self.pump_ml_per_stroke <= 0:
            raise ValueError("pump calibration must be positive")
        if self.usage_correction_factor <= 0:
            raise ValueError("usage correction factor must be positive")
        if self.maximum_pump_hz <= 0:
            raise ValueError("maximum pump frequency must be positive")


@dataclass(frozen=True, slots=True)
class FuelSnapshot:
    """All derived values exposed by the canonical model."""

    controller_used_l: float
    corrected_used_l: float
    remaining_l: float
    raw_remaining_l: float
    remaining_percent: float
    current_rate_lph: float
    runtime_at_current_rate_h: float | None
    runtime_at_maximum_rate_h: float
    out_of_range: bool


@dataclass(frozen=True, slots=True)
class RefillCalibration:
    """Result of comparing one controller interval with an actual refill."""

    actual_refill_l: float
    controller_used_l: float
    actual_to_controller_ratio: float
    error_percent: float
    proposed_ml_per_stroke: float


@dataclass(frozen=True, slots=True)
class FuelCostSnapshot:
    """Fuel costs derived from the canonical fuel snapshot."""

    price_per_litre: float
    current_per_hour: float
    current_per_24h: float
    current_per_30d: float
    maximum_per_hour: float
    maximum_per_24h: float
    maximum_per_30d: float
    used_since_reset: float
    recorded_total: float
    remaining_value: float
    full_tank_cost: float


@dataclass(slots=True)
class FuelCostLedger:
    """Persistent cost accumulator that never reprices earlier consumption."""

    used_since_reset: float = 0.0
    recorded_total: float = 0.0
    last_corrected_fuel_used_l: float | None = None

    def update(self, corrected_fuel_used_l: float, price_per_litre: float) -> bool:
        if corrected_fuel_used_l < 0 or price_per_litre < 0:
            raise ValueError("fuel usage and price cannot be negative")
        previous = self.last_corrected_fuel_used_l
        if previous is None:
            self.last_corrected_fuel_used_l = corrected_fuel_used_l
            return True
        if corrected_fuel_used_l < previous:
            self.used_since_reset = 0.0
            self.last_corrected_fuel_used_l = corrected_fuel_used_l
            return True
        delta_l = corrected_fuel_used_l - previous
        if delta_l <= 0:
            return False
        incremental_cost = delta_l * price_per_litre
        self.used_since_reset += incremental_cost
        self.recorded_total += incremental_cost
        self.last_corrected_fuel_used_l = corrected_fuel_used_l
        return True


def rate_lph(pump_hz: float, pump_ml_per_stroke: float) -> float:
    """Return litres/hour for a pump frequency and per-stroke calibration."""
    if pump_hz <= 0:
        return 0.0
    if pump_ml_per_stroke <= 0:
        raise ValueError("pump calibration must be positive")
    return pump_hz * pump_ml_per_stroke * SECONDS_PER_HOUR / MILLILITRES_PER_LITRE


def calculate_fuel(
    config: FuelConfig,
    *,
    controller_used_l: float,
    pump_hz: float,
) -> FuelSnapshot:
    """Calculate all fuel entities from one authoritative input set."""
    config.validate()
    if controller_used_l < 0:
        raise ValueError("controller fuel used cannot be negative")

    corrected_used = controller_used_l * config.usage_correction_factor
    raw_remaining = config.tank_capacity_l - corrected_used
    remaining = min(config.tank_capacity_l, max(0.0, raw_remaining))
    percent = remaining / config.tank_capacity_l * 100.0
    current_rate = rate_lph(pump_hz, config.pump_ml_per_stroke)
    maximum_rate = rate_lph(config.maximum_pump_hz, config.pump_ml_per_stroke)

    return FuelSnapshot(
        controller_used_l=controller_used_l,
        corrected_used_l=corrected_used,
        remaining_l=remaining,
        raw_remaining_l=raw_remaining,
        remaining_percent=percent,
        current_rate_lph=current_rate,
        runtime_at_current_rate_h=(remaining / current_rate if current_rate > 0 else None),
        runtime_at_maximum_rate_h=remaining / maximum_rate,
        out_of_range=raw_remaining < 0 or raw_remaining > config.tank_capacity_l,
    )


def calculate_refill_calibration(
    *,
    actual_refill_l: float,
    controller_used_l: float,
    current_ml_per_stroke: float,
) -> RefillCalibration:
    """Return the correction implied by refilling to the same physical mark."""
    if actual_refill_l <= 0:
        raise ValueError("actual refill must be positive")
    if controller_used_l <= 0:
        raise ValueError("controller interval usage must be positive")
    if current_ml_per_stroke <= 0:
        raise ValueError("pump calibration must be positive")

    ratio = actual_refill_l / controller_used_l
    return RefillCalibration(
        actual_refill_l=actual_refill_l,
        controller_used_l=controller_used_l,
        actual_to_controller_ratio=ratio,
        error_percent=(ratio - 1.0) * 100.0,
        proposed_ml_per_stroke=current_ml_per_stroke * ratio,
    )


def calculate_fuel_costs(
    config: FuelConfig,
    fuel: FuelSnapshot,
    *,
    price_per_litre: float,
    cost_used_since_reset: float = 0.0,
    recorded_total_cost: float = 0.0,
) -> FuelCostSnapshot:
    """Calculate current projections and inventory values in local currency."""
    if price_per_litre < 0:
        raise ValueError("diesel price cannot be negative")
    if cost_used_since_reset < 0 or recorded_total_cost < 0:
        raise ValueError("recorded fuel cost cannot be negative")

    current_hour = fuel.current_rate_lph * price_per_litre
    maximum_hour = (
        rate_lph(config.maximum_pump_hz, config.pump_ml_per_stroke)
        * price_per_litre
    )
    return FuelCostSnapshot(
        price_per_litre=price_per_litre,
        current_per_hour=current_hour,
        current_per_24h=current_hour * 24,
        current_per_30d=current_hour * 24 * 30,
        maximum_per_hour=maximum_hour,
        maximum_per_24h=maximum_hour * 24,
        maximum_per_30d=maximum_hour * 24 * 30,
        used_since_reset=cost_used_since_reset,
        recorded_total=recorded_total_cost,
        remaining_value=fuel.remaining_l * price_per_litre,
        full_tank_cost=config.tank_capacity_l * price_per_litre,
    )
