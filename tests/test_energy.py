"""
Unit tests for monotonic energy trapezoidal integration.
"""

import unittest
from core.energy import EnergyTracker


class TestEnergyTracker(unittest.TestCase):
    """Test suite for numerical energy integration."""

    def test_constant_power_integration(self):
        """100W power over 3600 seconds must equal exactly 100 Wh (0.1 kWh)."""
        tracker = EnergyTracker(start_mono=0.0)
        tracker.update(current_watts=100.0, current_mono=0.0)
        
        # Advance 1 hour (3600s)
        wh, kwh = tracker.update(current_watts=100.0, current_mono=3600.0)
        
        self.assertAlmostEqual(wh, 100.0, places=3)
        self.assertAlmostEqual(kwh, 0.10, places=4)
        self.assertAlmostEqual(tracker.average_watts, 100.0, places=3)
        self.assertEqual(tracker.peak_watts, 100.0)
        self.assertEqual(tracker.min_watts, 100.0)

    def test_trapezoidal_fluctuating_power(self):
        """Power stepping from 50W to 150W over 10 seconds: area = (50+150)/2 * 10 = 1000 Joules."""
        tracker = EnergyTracker(start_mono=10.0)
        tracker.update(current_watts=50.0, current_mono=10.0)
        
        wh, kwh = tracker.update(current_watts=150.0, current_mono=20.0)
        expected_joules = 1000.0
        expected_wh = expected_joules / 3600.0
        
        self.assertAlmostEqual(tracker.cumulative_joules, expected_joules, places=3)
        self.assertAlmostEqual(wh, expected_wh, places=4)
        self.assertAlmostEqual(tracker.average_watts, 100.0, places=3)
        self.assertEqual(tracker.peak_watts, 150.0)
        self.assertEqual(tracker.min_watts, 50.0)

    def test_zero_time_delta_does_not_corrupt_state(self):
        """Rapid duplicate calls with dt=0 must not produce division by zero or NaN."""
        tracker = EnergyTracker(start_mono=5.0)
        tracker.update(current_watts=60.0, current_mono=5.0)
        wh, kwh = tracker.update(current_watts=60.0, current_mono=5.0)
        
        self.assertEqual(wh, 0.0)
        self.assertEqual(kwh, 0.0)
        self.assertEqual(tracker.average_watts, 60.0)

    def test_per_component_energy_tracking(self):
        """Component power readings should be integrated independently."""
        tracker = EnergyTracker(start_mono=0.0)
        tracker.update(
            current_watts=100.0,
            current_mono=0.0,
            component_readings={"CPU": 40.0, "GPU": 60.0},
        )
        tracker.update(
            current_watts=100.0,
            current_mono=3600.0,
            component_readings={"CPU": 40.0, "GPU": 60.0},
        )
        comp_kwh = tracker.get_component_energy_kwh()
        
        self.assertAlmostEqual(comp_kwh["CPU"], 0.04, places=4)
        self.assertAlmostEqual(comp_kwh["GPU"], 0.06, places=4)


if __name__ == "__main__":
    unittest.main()
