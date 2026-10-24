"""
Unit tests for electricity cost and Sri Lankan CEB tariff calculations.
"""

import unittest
from core.cost import CostCalculator
from monitors.models import TariffConfig, TariffSlab


class TestCostCalculator(unittest.TestCase):
    """Test suite for tariff calculations and projections."""

    def test_flat_tariff_cost(self):
        """10 kWh at 32.50 LKR/kWh should equal 325.00 LKR."""
        config = TariffConfig(rate_per_kwh=32.50, currency="LKR")
        calc = CostCalculator(config)
        
        cost = calc.calculate_session_cost(energy_kwh=10.0)
        self.assertAlmostEqual(cost, 325.0, places=2)

    def test_run_rate_projections(self):
        """100W at 32.50 LKR/kWh = 0.1 kW * 32.50 = 3.25 LKR/hour."""
        calc = CostCalculator(TariffConfig(rate_per_kwh=32.50))
        
        hourly = calc.calculate_run_rate_hourly(watts=100.0)
        self.assertAlmostEqual(hourly, 3.25, places=2)

        daily = calc.project_daily_cost(avg_watts=100.0, hours_per_day=24.0)
        self.assertAlmostEqual(daily, 78.00, places=2)

    def test_ceb_lifeline_slab_cost(self):
        """
        CEB Lifeline tier: <= 60 units
        Example: 40 kWh total:
          First 30 @ 8.00 = 240 LKR
          Next 10 @ 20.00 = 200 LKR
          Fixed charge = 300 LKR
          Total = 240 + 200 + 300 = 740 LKR.
        """
        config = TariffConfig(use_slabs=True)
        calc = CostCalculator(config)
        
        slab_cost = calc._calculate_slab_cost(40.0)
        self.assertAlmostEqual(slab_cost, 740.0, places=2)

    def test_ceb_higher_tier_slab_cost(self):
        """
        CEB Higher tier: > 60 units
        Example: 100 kWh total:
          First 60 @ 25.00 = 1500 LKR
          Next 30 (61-90) @ 30.00 = 900 LKR
          Next 10 (91-120) @ 50.00 = 500 LKR
          Fixed charge = 1000 LKR
          Total = 1500 + 900 + 500 + 1000 = 3900 LKR.
        """
        config = TariffConfig(use_slabs=True)
        calc = CostCalculator(config)
        
        slab_cost = calc._calculate_slab_cost(100.0)
        self.assertAlmostEqual(slab_cost, 3900.0, places=2)


if __name__ == "__main__":
    unittest.main()
