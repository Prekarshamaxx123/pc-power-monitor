"""
Laptop Battery Telemetry and Whole-System DC Power Monitor.
Interfaces with Linux /sys/class/power_supply to read real-time battery discharge rates.
When running on battery power, battery discharge rate represents genuine MEASURED
whole-system DC power consumption.
"""

from __future__ import annotations
import glob
import os
from typing import Dict, Any, Optional

from monitors.base import BaseMonitor
from monitors.models import ComponentPower, DataQuality


class BatteryMonitor(BaseMonitor):
    """Monitors battery charge/discharge rates on portable Linux systems."""

    def __init__(self):
        super().__init__(name="Battery")
        self.battery_path: Optional[str] = None
        self.has_battery: bool = False

    def initialize(self) -> bool:
        """Scan /sys/class/power_supply for active battery interfaces."""
        self._warnings.clear()
        batteries = glob.glob("/sys/class/power_supply/BAT*")
        if batteries:
            self.battery_path = batteries[0]
            self.has_battery = True
            self.is_initialized = True
            return True

        self.has_battery = False
        self.is_initialized = False
        return False

    def read(self, elapsed_s: float) -> Optional[ComponentPower]:
        """Read instantaneous battery power draw."""
        if not self.has_battery or not self.battery_path:
            return None

        status = "Unknown"
        status_file = os.path.join(self.battery_path, "status")
        if os.path.isfile(status_file):
            try:
                with open(status_file, "r", encoding="utf-8") as f:
                    status = f.read().strip()
            except Exception:
                pass

        watts = 0.0
        is_measured = False
        source = "sysfs:power_supply"

        # Check power_now (microwatts)
        p_now = os.path.join(self.battery_path, "power_now")
        if os.path.isfile(p_now):
            try:
                with open(p_now, "r", encoding="utf-8") as f:
                    watts = float(f.read().strip()) / 1e6
                    is_measured = True
                    source = "sysfs:power_now"
            except Exception:
                pass

        # If power_now not present, try voltage_now (uV) * current_now (uA)
        if not is_measured:
            v_now = os.path.join(self.battery_path, "voltage_now")
            c_now = os.path.join(self.battery_path, "current_now")
            if os.path.isfile(v_now) and os.path.isfile(c_now):
                try:
                    with open(v_now, "r", encoding="utf-8") as vf, open(c_now, "r", encoding="utf-8") as cf:
                        u_volts = float(vf.read().strip())
                        u_amps = float(cf.read().strip())
                        watts = (u_volts * u_amps) / 1e12
                        is_measured = True
                        source = "sysfs:voltage_x_current"
                except Exception:
                    pass

        # Capacity percentage
        capacity_pct = None
        cap_file = os.path.join(self.battery_path, "capacity")
        if os.path.isfile(cap_file):
            try:
                with open(cap_file, "r", encoding="utf-8") as f:
                    capacity_pct = float(f.read().strip())
            except Exception:
                pass

        is_discharging = (status.lower() == "discharging")
        quality = DataQuality.MEASURED if is_measured else DataQuality.UNAVAILABLE

        details = {
            "status": status,
            "capacity_pct": capacity_pct,
            "is_discharging": is_discharging,
        }

        self.last_reading = ComponentPower(
            name="Battery (Whole-System DC)",
            watts=round(watts, 2),
            quality=quality,
            source=source,
            is_whole_system=is_discharging,  # Battery discharge IS whole-system DC power
            details=details,
        )
        return self.last_reading
