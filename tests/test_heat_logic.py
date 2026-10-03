import importlib.util
from pathlib import Path
import unittest


MODULE_PATH = Path(__file__).parents[1] / "custom_components" / "afterburner_helper" / "heat_logic.py"
SPEC = importlib.util.spec_from_file_location("heat_logic", MODULE_PATH)
heat_logic = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(heat_logic)


class HeatGroupTests(unittest.TestCase):
    def defaults(self):
        return {
            "room": 20.0,
            "master_target": 22.0,
            "master_enabled": True,
            "priority": "Electric 1 → Electric 2 → Diesel",
            "lockouts": {"diesel": False, "electric_1": False, "electric_2": False},
            "member_modes": {"diesel": "auto", "electric_1": "auto", "electric_2": "auto"},
            "member_targets": {"diesel": 22.0, "electric_1": 22.0, "electric_2": 22.0},
        }

    def test_two_degree_deficit_stages_both_electric_heaters(self):
        self.assertEqual(
            heat_logic.requested_sources(**self.defaults()),
            ("electric_1", "electric_2"),
        )

    def test_one_degree_deficit_uses_only_first_automatic_source(self):
        values = self.defaults()
        values["room"] = 21.0
        self.assertEqual(
            heat_logic.requested_sources(**values),
            ("electric_1",),
        )

    def test_three_degree_deficit_adds_diesel_last(self):
        values = self.defaults()
        values["room"] = 18.5
        self.assertEqual(
            heat_logic.requested_sources(**values),
            ("electric_1", "electric_2", "diesel"),
        )

    def test_lockout_removes_source_from_automatic_staging(self):
        values = self.defaults()
        values["lockouts"]["electric_1"] = True
        self.assertEqual(
            heat_logic.requested_sources(**values),
            ("electric_2", "diesel"),
        )

    def test_master_off_overrides_manual_member_heat(self):
        values = self.defaults()
        values["master_enabled"] = False
        values["member_modes"]["electric_1"] = "heat"
        self.assertEqual(heat_logic.requested_sources(**values), ())

    def test_global_automatic_gate_stops_all_group_actuation(self):
        values = self.defaults()
        values["master_enabled"] = False
        self.assertEqual(heat_logic.requested_sources(**values), ())
        values["member_modes"]["diesel"] = "heat"
        self.assertEqual(heat_logic.requested_sources(**values), ())

    def test_minimum_off_time_blocks_automatic_start(self):
        command, delay = heat_logic.minimum_cycle_decision(
            desired_on=True,
            actual_on=False,
            elapsed_seconds=120,
            minimum_on_seconds=1200,
            minimum_off_seconds=600,
        )
        self.assertIsNone(command)
        self.assertEqual(delay, 480)

    def test_minimum_on_time_blocks_automatic_stop(self):
        command, delay = heat_logic.minimum_cycle_decision(
            desired_on=False,
            actual_on=True,
            elapsed_seconds=300,
            minimum_on_seconds=1200,
            minimum_off_seconds=600,
        )
        self.assertIsNone(command)
        self.assertEqual(delay, 900)

    def test_explicit_off_bypasses_minimum_on_time(self):
        command, delay = heat_logic.minimum_cycle_decision(
            desired_on=False,
            actual_on=True,
            elapsed_seconds=10,
            minimum_on_seconds=1200,
            minimum_off_seconds=600,
            force_off=True,
        )
        self.assertFalse(command)
        self.assertIsNone(delay)

    def test_failed_start_can_use_shorter_retry_delay(self):
        command, delay = heat_logic.minimum_cycle_decision(
            desired_on=True,
            actual_on=False,
            elapsed_seconds=15,
            minimum_on_seconds=1200,
            minimum_off_seconds=60,
        )
        self.assertIsNone(command)
        self.assertEqual(delay, 45)

    def test_manual_off_overrides_group_demand(self):
        values = self.defaults()
        values["member_modes"]["electric_1"] = "off"
        self.assertEqual(
            heat_logic.requested_sources(**values),
            ("electric_2", "diesel"),
        )

    def test_stage_two_stays_on_through_sensor_noise(self):
        self.assertEqual(heat_logic.hysteretic_stage_count(20.49, 22.0, 1), 2)
        self.assertEqual(heat_logic.hysteretic_stage_count(20.55, 22.0, 2), 2)
        self.assertEqual(heat_logic.hysteretic_stage_count(20.80, 22.0, 2), 2)

    def test_stage_two_releases_only_below_its_off_threshold(self):
        self.assertEqual(heat_logic.hysteretic_stage_count(21.24, 22.0, 2), 2)
        self.assertEqual(heat_logic.hysteretic_stage_count(21.25, 22.0, 2), 1)

    def test_hysteresis_can_add_multiple_stages_after_restart(self):
        self.assertEqual(heat_logic.hysteretic_stage_count(18.5, 22.0, 0), 3)
