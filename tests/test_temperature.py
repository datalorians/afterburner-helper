import importlib.util
from pathlib import Path
import unittest


MODULE_PATH = Path(__file__).parents[1] / "custom_components" / "afterburner_helper" / "temperature.py"
SPEC = importlib.util.spec_from_file_location("temperature", MODULE_PATH)
temperature = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(temperature)


class TemperatureFusionTests(unittest.TestCase):
    def test_averages_all_valid_sources(self):
        self.assertEqual(temperature.fused_temperature([20.0, 22.0, 24.0]), 22.0)

    def test_ignores_invalid_and_non_finite_sources(self):
        self.assertEqual(
            temperature.fused_temperature([20.0, None, "unavailable", float("nan"), float("inf")]),
            20.0,
        )

    def test_returns_none_without_a_valid_source(self):
        self.assertIsNone(temperature.fused_temperature([None, "unknown"]))

    def test_rounds_virtual_sensor_value(self):
        self.assertEqual(temperature.fused_temperature([19.71, 20.02]), 19.87)
