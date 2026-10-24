"""
Monotonic Energy Integration Engine.
Uses trapezoidal numerical integration over monotonic time delta measurements
to accurately integrate dynamic power fluctuations into Watt-hours and kiloWatt-hours.
"""

from __future__ import annotations
import time
from typing import Dict, Tuple, Optional


class EnergyTracker:
    """Accurately integrates power over time using monotonic time and trapezoidal integration."""

    def __init__(self, start_mono: Optional[float] = None):
        self.start_mono = start_mono if start_mono is not None else time.monotonic()
        self.last_mono: float = self.start_mono
        self.last_watts: float = 0.0
        
        # Cumulative energy in Joules (Watt-seconds)
        self.cumulative_joules: float = 0.0
        
        # Power extrema
        self.peak_watts: float = 0.0
        self.min_watts: float = float("inf")
        self.sample_count: int = 0
        
        # Per-component energy tracking (Joules)
        self.component_joules: Dict[str, float] = {}
        self._last_component_watts: Dict[str, float] = {}

    def update(
        self,
        current_watts: float,
        current_mono: Optional[float] = None,
        component_readings: Optional[Dict[str, float]] = None,
    ) -> Tuple[float, float]:
        """
        Integrate power reading using trapezoidal rule:
        dE = ((P_prev + P_cur) / 2.0) * dt (Watt-seconds / Joules).
        Returns:
            Tuple[total_wh, total_kwh]
        """
        now = current_mono if current_mono is not None else time.monotonic()
        dt = max(now - self.last_mono, 0.0)

        current_watts = max(current_watts, 0.0)

        # Update extrema
        if current_watts > self.peak_watts:
            self.peak_watts = current_watts
        if current_watts < self.min_watts:
            self.min_watts = current_watts

        # Trapezoidal integration for total system power
        if self.sample_count > 0 and dt > 0:
            delta_joules = ((self.last_watts + current_watts) / 2.0) * dt
            self.cumulative_joules += delta_joules

            # Integrate per-component energy when available
            if component_readings:
                for comp_name, comp_watts in component_readings.items():
                    prev_w = self._last_component_watts.get(comp_name, comp_watts)
                    comp_delta_j = ((prev_w + comp_watts) / 2.0) * dt
                    self.component_joules[comp_name] = self.component_joules.get(comp_name, 0.0) + comp_delta_j
                    self._last_component_watts[comp_name] = comp_watts
        else:
            if component_readings:
                for comp_name, comp_watts in component_readings.items():
                    self._last_component_watts[comp_name] = comp_watts

        self.last_mono = now
        self.last_watts = current_watts
        self.sample_count += 1

        total_wh = self.cumulative_joules / 3600.0
        total_kwh = self.cumulative_joules / 3600000.0
        return total_wh, total_kwh

    @property
    def total_wh(self) -> float:
        """Total integrated energy in Watt-hours."""
        return self.cumulative_joules / 3600.0

    @property
    def total_kwh(self) -> float:
        """Total integrated energy in kiloWatt-hours."""
        return self.cumulative_joules / 3600000.0

    @property
    def elapsed_seconds(self) -> float:
        """Total elapsed seconds since tracking initiated."""
        return max(self.last_mono - self.start_mono, 0.0)

    @property
    def average_watts(self) -> float:
        """
        Mathematically exact time-weighted average power:
        P_avg = Total Joules / Elapsed Seconds.
        """
        if self.elapsed_seconds > 0.01:
            return self.cumulative_joules / self.elapsed_seconds
        return self.last_watts

    def get_component_energy_kwh(self) -> Dict[str, float]:
        """Return integrated energy breakdown per component in kWh."""
        return {
            name: round(j / 3600000.0, 5)
            for name, j in self.component_joules.items()
        }
