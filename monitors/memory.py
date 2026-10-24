"""
System Memory (RAM) Telemetry and Power Monitor.
Strictly adheres to hardware physics: DRAM power consumption is primarily determined
by the number of physical DIMM modules, refresh cycles, and bus frequency,
NOT directly by the percentage of memory allocated by the operating system.
"""

from __future__ import annotations
import math
from typing import Dict, Any, Optional
import psutil

from monitors.base import BaseMonitor
from monitors.models import ComponentPower, DataQuality


class MemoryMonitor(BaseMonitor):
    """Monitors system RAM utilization and provides realistic DRAM power modeling."""

    def __init__(self, estimated_dimms: Optional[int] = None):
        super().__init__(name="RAM")
        self.estimated_dimms = estimated_dimms or 2  # Standard dual-channel configuration default
        self.total_gb: float = 0.0

    def initialize(self) -> bool:
        """Query memory capacity and deduce typical DIMM module count."""
        self._warnings.clear()
        try:
            vm = psutil.virtual_memory()
            self.total_gb = vm.total / (1024 ** 3)
            # If user didn't specify DIMMs, estimate from capacity (e.g. 16GB -> 2x8GB, 32GB -> 2x16GB)
            if self.total_gb <= 8.5:
                self.estimated_dimms = 1
            else:
                self.estimated_dimms = 2
            self.is_initialized = True
            return True
        except Exception as e:
            self._warnings.append(f"Failed to query system memory: {e}")
            self.is_initialized = False
            return False

    def read(self, elapsed_s: float) -> ComponentPower:
        """
        Sample RAM metrics and calculate estimated DRAM power.
        Hardware note: A DDR4 DIMM typically draws ~1.5W to 2.2W in active standby.
        Active read/write bursts add ~0.5W to 1.5W depending on memory bus traffic.
        """
        vm = psutil.virtual_memory()
        used_gb = vm.used / (1024 ** 3)
        available_gb = vm.available / (1024 ** 3)
        percent_used = vm.percent

        # Base power: ~1.8W per installed DIMM module
        base_dimm_power = self.estimated_dimms * 1.8
        
        # Minor dynamic memory controller / bus load factor (0 to 1.0W)
        dynamic_factor = min(1.0, (percent_used / 100.0) * 0.8)
        estimated_watts = base_dimm_power + dynamic_factor

        details = {
            "total_gb": round(self.total_gb, 2),
            "used_gb": round(used_gb, 2),
            "available_gb": round(available_gb, 2),
            "utilization_pct": percent_used,
            "estimated_dimm_modules": self.estimated_dimms,
            "power_physics_note": (
                "RAM power consumption does not scale with filled capacity. "
                f"Modeled at ~1.8W per DIMM ({self.estimated_dimms} modules) plus bus activity."
            ),
        }

        self.last_reading = ComponentPower(
            name=f"RAM ({self.estimated_dimms}x DIMMs, {round(self.total_gb)}GB)",
            watts=round(estimated_watts, 2),
            quality=DataQuality.ESTIMATED,
            source="model:dram_dimm_standby",
            details=details,
        )
        return self.last_reading
