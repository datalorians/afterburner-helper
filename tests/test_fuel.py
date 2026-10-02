from __future__ import annotations

from pathlib import Path
import sys
import unittest

sys.path.insert(
    0,
    str(Path(__file__).resolve().parents[1] / "custom_components" / "afterburner_helper"),
)

from fuel import (
    FuelConfig,
    FuelCostLedger,
    calculate_fuel,
    calculate_fuel_costs,
    calculate_refill_calibration,
    rate_lph,
)


class FuelTests(unittest.TestCase):
    def test_rate_matches_afterburner_at_low_fire(self) -> None:
        self.assertAlmostEqual(rate_lph(1.2, 0.022), 0.09504)

    def test_overnight_run_matches_integrated_usage(self) -> None:
        snapshot = calculate_fuel(
            FuelConfig(tank_capacity_l=20, pump_ml_per_stroke=0.022, maximum_pump_hz=3.9),
            controller_used_l=0.870,
            pump_hz=1.2,
        )
        self.assertAlmostEqual(snapshot.remaining_l, 19.13)
        self.assertAlmostEqual(snapshot.remaining_percent, 95.65)
        self.assertAlmostEqual(snapshot.current_rate_lph, 0.09504)
        self.assertIsNotNone(snapshot.runtime_at_current_rate_h)

    def test_off_state_runtime_is_unavailable_not_zero(self) -> None:
        snapshot = calculate_fuel(FuelConfig(), controller_used_l=1, pump_hz=0)
        self.assertIsNone(snapshot.runtime_at_current_rate_h)

    def test_refill_proposes_corrected_pump_calibration(self) -> None:
        calibration = calculate_refill_calibration(
            actual_refill_l=10.5,
            controller_used_l=10.0,
            current_ml_per_stroke=0.022,
        )
        self.assertAlmostEqual(calibration.actual_to_controller_ratio, 1.05)
        self.assertAlmostEqual(calibration.error_percent, 5.0)
        self.assertAlmostEqual(calibration.proposed_ml_per_stroke, 0.0231)

    def test_cost_projections_follow_current_and_maximum_rates(self) -> None:
        config = FuelConfig(
            tank_capacity_l=20,
            pump_ml_per_stroke=0.022,
            maximum_pump_hz=3.9,
        )
        fuel = calculate_fuel(config, controller_used_l=1, pump_hz=1.2)
        costs = calculate_fuel_costs(
            config,
            fuel,
            price_per_litre=1.50,
            cost_used_since_reset=1.25,
            recorded_total_cost=7.50,
        )
        self.assertAlmostEqual(costs.current_per_hour, 0.14256)
        self.assertAlmostEqual(costs.current_per_24h, 3.42144)
        self.assertAlmostEqual(costs.current_per_30d, 102.6432)
        self.assertAlmostEqual(costs.maximum_per_hour, 0.46332)
        self.assertAlmostEqual(costs.used_since_reset, 1.25)
        self.assertAlmostEqual(costs.recorded_total, 7.50)
        self.assertAlmostEqual(costs.remaining_value, 28.50)
        self.assertAlmostEqual(costs.full_tank_cost, 30.0)

    def test_cost_ledger_does_not_reprice_old_fuel(self) -> None:
        ledger = FuelCostLedger()
        self.assertTrue(ledger.update(1.0, 1.50))
        self.assertTrue(ledger.update(2.0, 1.50))
        self.assertAlmostEqual(ledger.recorded_total, 1.50)
        self.assertFalse(ledger.update(2.0, 2.00))
        self.assertAlmostEqual(ledger.recorded_total, 1.50)
        self.assertTrue(ledger.update(3.0, 2.00))
        self.assertAlmostEqual(ledger.recorded_total, 3.50)

    def test_cost_ledger_resets_interval_but_not_total(self) -> None:
        ledger = FuelCostLedger()
        ledger.update(0.0, 1.50)
        ledger.update(2.0, 1.50)
        ledger.update(0.0, 1.75)
        self.assertEqual(ledger.used_since_reset, 0.0)
        self.assertAlmostEqual(ledger.recorded_total, 3.0)


if __name__ == "__main__":
    unittest.main()
