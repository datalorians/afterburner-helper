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

    def test_manual_heat_operates_with_master_off(self):
        values = self.defaults()
        values["master_enabled"] = False
        values["member_modes"]["electric_1"] = "heat"
        self.assertEqual(
            heat_logic.requested_sources(**values),
            ("electric_1",),
        )

    def test_manual_off_overrides_group_demand(self):
        values = self.defaults()
        values["member_modes"]["electric_1"] = "off"
        self.assertEqual(
            heat_logic.requested_sources(**values),
            ("electric_2", "diesel"),
        )
