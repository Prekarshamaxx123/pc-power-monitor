"""
Electricity Cost Engine and Sri Lankan Tariff Calculations.
Supports configurable flat-rate pricing in Sri Lankan Rupees (LKR/kWh),
run-rate hourly/daily/monthly projections, and optional CEB/LECO tiered slab models.
"""

from __future__ import annotations
from typing import Dict, Any, List, Tuple, Optional

from monitors.models import TariffConfig, TariffSlab


class CostCalculator:
    """Computes electricity expenditure and projections based on energy telemetry."""

    def __init__(self, config: Optional[TariffConfig] = None):
        self.config = config or TariffConfig(rate_per_kwh=32.50, currency="LKR")
        if not self.config.slabs:
            self.config.slabs = self.get_default_ceb_slabs()

    @staticmethod
    def get_default_ceb_slabs() -> List[TariffSlab]:
        """
        Reference Sri Lankan Domestic CEB/LECO tariff tiers:
        Tier 1: <= 60 units/month (Low consumer lifeline):
          0-30 kWh: 8.00 LKR/unit + 150 LKR fixed
          31-60 kWh: 20.00 LKR/unit + 300 LKR fixed
        Tier 2: > 60 units/month:
          0-60 kWh: 25.00 LKR/unit + 400 LKR fixed
          61-90 kWh: 30.00 LKR/unit + 400 LKR fixed
          91-120 kWh: 50.00 LKR/unit + 1000 LKR fixed
          121-180 kWh: 50.00 LKR/unit + 1500 LKR fixed
          >180 kWh: 75.00 LKR/unit + 2000 LKR fixed
        """
        return [
            TariffSlab(min_kwh=0, max_kwh=30, rate_per_kwh=8.00, fixed_charge_lkr=150.0),
            TariffSlab(min_kwh=30, max_kwh=60, rate_per_kwh=20.00, fixed_charge_lkr=300.0),
            TariffSlab(min_kwh=60, max_kwh=90, rate_per_kwh=30.00, fixed_charge_lkr=400.0),
            TariffSlab(min_kwh=90, max_kwh=120, rate_per_kwh=50.00, fixed_charge_lkr=1000.0),
            TariffSlab(min_kwh=120, max_kwh=180, rate_per_kwh=50.00, fixed_charge_lkr=1500.0),
            TariffSlab(min_kwh=180, max_kwh=None, rate_per_kwh=75.00, fixed_charge_lkr=2000.0),
        ]

    def calculate_session_cost(self, energy_kwh: float) -> float:
        """
        Calculate total cost for the current session in LKR.
        Uses flat rate: Cost = kWh * rate_per_kwh.
        """
        base_cost = energy_kwh * self.config.rate_per_kwh
        surcharge = base_cost * (self.config.fuel_adjustment_pct / 100.0)
        vat = (base_cost + surcharge) * (self.config.vat_pct / 100.0)
        return round(base_cost + surcharge + vat, 4)

    def calculate_run_rate_hourly(self, watts: float) -> float:
        """Calculate real-time cost rate in LKR per operating hour."""
        kwh_per_hour = max(watts, 0.0) / 1000.0
        return round(kwh_per_hour * self.config.rate_per_kwh, 2)

    def project_daily_cost(self, avg_watts: float, hours_per_day: float = 24.0) -> float:
        """Project daily operating cost in LKR based on average wattage."""
        daily_kwh = (max(avg_watts, 0.0) / 1000.0) * min(hours_per_day, 24.0)
        return round(daily_kwh * self.config.rate_per_kwh, 2)

    def project_monthly_cost(
        self,
        avg_watts: float,
        hours_per_day: float = 24.0,
        days_per_month: int = 30,
    ) -> Tuple[float, float, str]:
        """
        Project monthly consumption (kWh) and cost (LKR).
        Returns:
            Tuple[monthly_kwh, monthly_cost_lkr, explanation_note]
        """
        monthly_kwh = (max(avg_watts, 0.0) / 1000.0) * hours_per_day * days_per_month
        
        if self.config.use_slabs and self.config.slabs:
            # Tiered slab calculation
            cost = self._calculate_slab_cost(monthly_kwh)
            mode = "CEB Tiered Slabs"
        else:
            # Flat tariff
            cost = monthly_kwh * self.config.rate_per_kwh
            mode = f"Flat Tariff ({self.config.rate_per_kwh:.2f} LKR/kWh)"

        explanation = (
            f"Projected at {hours_per_day}h/day for {days_per_month} days ({monthly_kwh:.1f} kWh/mo) "
            f"using {mode}. Actual domestic bills include monthly household cumulative slabs and fixed charges."
        )
        return round(monthly_kwh, 2), round(cost, 2), explanation

    def _calculate_slab_cost(self, total_kwh: float) -> float:
        """Compute domestic electricity cost across tiered progressive tariff slabs."""
        if total_kwh <= 0:
            return 0.0

        energy_charge = 0.0
        fixed_charge = 0.0

        # Lifeline domestic category (<= 60 units total)
        if total_kwh <= 60:
            tier1 = min(total_kwh, 30)
            energy_charge += tier1 * 8.00
            if total_kwh > 30:
                tier2 = total_kwh - 30
                energy_charge += tier2 * 20.00
                fixed_charge = 300.0
            else:
                fixed_charge = 150.0
        else:
            # Higher consumer category (> 60 units total)
            remaining = total_kwh
            # First 60 units @ 25.00
            b1 = min(remaining, 60)
            energy_charge += b1 * 25.00
            remaining -= b1
            fixed_charge = 400.0

            if remaining > 0:
                # 61-90 (30 units) @ 30.00
                b2 = min(remaining, 30)
                energy_charge += b2 * 30.00
                remaining -= b2

            if remaining > 0:
                # 91-120 (30 units) @ 50.00
                b3 = min(remaining, 30)
                energy_charge += b3 * 50.00
                remaining -= b3
                fixed_charge = 1000.0

            if remaining > 0:
                # 121-180 (60 units) @ 50.00
                b4 = min(remaining, 60)
                energy_charge += b4 * 50.00
                remaining -= b4
                fixed_charge = 1500.0

            if remaining > 0:
                # >180 units @ 75.00
                energy_charge += remaining * 75.00
                fixed_charge = 2000.0

        return energy_charge + fixed_charge
