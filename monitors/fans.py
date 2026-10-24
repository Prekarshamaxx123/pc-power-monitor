"""
Cooling Fan Telemetry and Power Monitor.
Discovers RPM sensors across Linux hwmon interfaces and models cooling subsystem power draw.
"""

from __future__ import annotations
import glob
import os
from typing import Dict, Any, List, Optional

from monitors.base import BaseMonitor
from monitors.models import ComponentPower, DataQuality


class FanMonitor(BaseMonitor):
    """Monitors cooling fan RPMs and estimates fan power draw."""

    def __init__(self):
        super().__init__(name="Fans")
        self.fan_sensor_paths: List[str] = []

    def initialize(self) -> bool:
        """Scan /sys/class/hwmon for fan RPM inputs."""
        self._warnings.clear()
        self.fan_sensor_paths.clear()

        for hwmon_dir in glob.glob("/sys/class/hwmon/hwmon*"):
            for fan_input in glob.glob(os.path.join(hwmon_dir, "fan*_input")):
                self.fan_sensor_paths.append(fan_input)

        if not self.fan_sensor_paths:
            self._warnings.append(
                "No motherboard fan RPM sensors exposed via hwmon. "
                "Motherboard Super I/O driver (e.g. nct6775/nct6687) may not be loaded."
            )
            # Still initialize so we can estimate baseline fan consumption
            self.is_initialized = True
            return True

        self.is_initialized = True
        return True

    def read(self, elapsed_s: float) -> ComponentPower:
        """Read active fan RPMs and estimate 12V fan power consumption."""
        active_rpms: Dict[str, int] = {}
        total_rpm = 0

        for path in self.fan_sensor_paths:
            label = os.path.basename(path).replace("_input", "")
            try:
                with open(path, "r", encoding="utf-8") as f:
                    rpm = int(f.read().strip())
                    active_rpms[label] = rpm
                    total_rpm += rpm
            except Exception:
                pass

        fan_count = max(len(self.fan_sensor_paths), 1)
        if self.fan_sensor_paths and active_rpms:
            # Typical 12V case/CPU fan draws ~1.2W at low RPM (800 RPM) up to ~3.6W at 2000+ RPM
            avg_rpm = total_rpm / len(active_rpms) if active_rpms else 1000
            per_fan_watts = 1.0 + (avg_rpm / 2000.0) * 2.2
            estimated_watts = round(per_fan_watts * len(active_rpms), 2)
        else:
            # Baseline estimation for typical system fans (CPU cooler + 1-2 case fans)
            estimated_watts = 2.50

        details = {
            "sensors_found": len(self.fan_sensor_paths),
            "fan_rpms": active_rpms,
        }

        self.last_reading = ComponentPower(
            name=f"Cooling Fans ({len(active_rpms) if active_rpms else fan_count} fans)",
            watts=estimated_watts,
            quality=DataQuality.ESTIMATED,
            source="model:12v_pwm_fans" if not active_rpms else "model:hwmon_rpm_curve",
            details=details,
        )
        return self.last_reading
