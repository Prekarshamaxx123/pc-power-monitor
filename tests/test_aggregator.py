"""
Unit tests for power aggregation and strict double-counting prevention.
"""

import unittest
from unittest.mock import MagicMock
from monitors.aggregator import PowerAggregator
from monitors.models import ComponentPower, DataQuality


class TestPowerAggregator(unittest.TestCase):
    """Test suite for power aggregation and isolation of whole-system sensors."""

    def test_double_counting_prevention_with_whole_system_meter(self):
        """
        When a whole-system meter (e.g. wall meter at 85W) is present,
        total system power MUST equal 85W, NOT 85W + CPU + GPU!
        """
        aggregator = PowerAggregator(baseline_watts=40.0, psu_efficiency=0.85)

        # Mock monitors to return CPU (30W), GPU (40W), and Wall Meter (85W)
        mock_cpu = MagicMock()
        mock_cpu.read.return_value = ComponentPower("CPU", 30.0, DataQuality.MEASURED, "rapl")
        mock_cpu.get_warnings.return_value = []

        mock_gpu = MagicMock()
        mock_gpu.read.return_value = ComponentPower("GPU", 40.0, DataQuality.MEASURED, "nvml")
        mock_gpu.get_warnings.return_value = []

        mock_wall = MagicMock()
        mock_wall.read.return_value = ComponentPower("Wall", 85.0, DataQuality.MEASURED, "smart_plug", is_whole_system=True)
        mock_wall.get_warnings.return_value = []

        aggregator.monitors = {
            "cpu": mock_cpu,
            "gpu": mock_gpu,
            "wall_meter": mock_wall,
        }

        snapshot = aggregator.sample(elapsed_s=1.0)
        
        # System power must be the wall reading ONLY
        self.assertEqual(snapshot.total_system_watts, 85.0)
        self.assertEqual(snapshot.total_quality, DataQuality.MEASURED)
        self.assertIn("directly measured via", snapshot.explanation)

    def test_desktop_modeled_estimate_with_psu_efficiency(self):
        """
        On a desktop without whole-system meter, AC wall draw = Internal DC / PSU efficiency.
        Example: 51W internal DC / 0.85 efficiency = 60W estimated AC wall draw.
        """
        aggregator = PowerAggregator(baseline_watts=30.0, psu_efficiency=0.85)

        mock_cpu = MagicMock()
        mock_cpu.read.return_value = ComponentPower("CPU", 20.0, DataQuality.ESTIMATED, "model")
        mock_cpu.get_warnings.return_value = []

        mock_gpu = MagicMock()
        mock_gpu.read.return_value = ComponentPower("GPU", 19.0, DataQuality.ESTIMATED, "model")
        mock_gpu.get_warnings.return_value = []

        # Remove default monitors to isolate test components
        aggregator.monitors = {
            "cpu": mock_cpu,
            "gpu": mock_gpu,
        }

        # Internal DC = 20 + 19 + 12 (motherboard) = 51W
        # Expected AC = 51 / 0.85 = 60.0W
        snapshot = aggregator.sample(elapsed_s=1.0)
        self.assertAlmostEqual(snapshot.total_system_watts, 60.0, places=1)
        self.assertEqual(snapshot.total_quality, DataQuality.ESTIMATED)

    def test_baseline_floor_enforcement(self):
        """If calculated AC power is lower than configured baseline, baseline is used as floor."""
        aggregator = PowerAggregator(baseline_watts=50.0, psu_efficiency=0.85)
        
        mock_cpu = MagicMock()
        mock_cpu.read.return_value = ComponentPower("CPU", 5.0, DataQuality.ESTIMATED, "model")
        mock_cpu.get_warnings.return_value = []

        aggregator.monitors = {"cpu": mock_cpu}
        # DC = 5 + 12 (motherboard) = 17W -> AC = 20W < 50W baseline
        snapshot = aggregator.sample(elapsed_s=1.0)
        self.assertEqual(snapshot.total_system_watts, 50.0)
        self.assertIn("Configured baseline floor (50.0W) applied", snapshot.explanation)

    def test_highest_consumer_identification(self):
        """Aggregator must correctly identify which component is consuming the most power."""
        aggregator = PowerAggregator(baseline_watts=40.0)

        mock_cpu = MagicMock()
        mock_cpu.read.return_value = ComponentPower("CPU", 25.0, DataQuality.ESTIMATED, "model")
        mock_cpu.get_warnings.return_value = []

        mock_gpu = MagicMock()
        mock_gpu.read.return_value = ComponentPower("GPU (RTX 4090)", 280.0, DataQuality.MEASURED, "nvml")
        mock_gpu.get_warnings.return_value = []

        aggregator.monitors = {"cpu": mock_cpu, "gpu": mock_gpu}
        snapshot = aggregator.sample(elapsed_s=1.0)

        self.assertEqual(snapshot.highest_consumer_name, "GPU (RTX 4090)")
        self.assertEqual(snapshot.highest_consumer_watts, 280.0)
        self.assertEqual(snapshot.highest_consumer_quality, DataQuality.MEASURED)


if __name__ == "__main__":
    unittest.main()
