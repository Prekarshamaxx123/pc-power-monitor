"""
CPU Hardware and Telemetry Monitor.
Supports direct measurement via Linux RAPL (Running Average Power Limit) sysfs interface,
with automatic rollover handling, permission detection, and transparent model-based
estimation fallback when hardware counters require root privileges.
"""

from __future__ import annotations
import glob
import os
import re
import time
from typing import Dict, Any, List, Optional, Tuple

import psutil
from monitors.base import BaseMonitor
from monitors.models import ComponentPower, DataQuality


class CPUMonitor(BaseMonitor):
    """Monitors CPU power, utilization, frequencies, and temperatures."""

    # Standard TDP heuristics for common desktop/server/laptop processor classes (Watts)
    DEFAULT_TDP = 65.0

    def __init__(self, custom_tdp: Optional[float] = None):
        super().__init__(name="CPU")
        self.custom_tdp = custom_tdp
        self.cpu_model: str = "Unknown CPU"
        self.tdp: float = self.DEFAULT_TDP
        self.core_count: int = psutil.cpu_count(logical=False) or 1
        self.thread_count: int = psutil.cpu_count(logical=True) or 1

        # RAPL state
        self._rapl_energy_path: Optional[str] = None
        self._rapl_max_range_uj: float = 65532610987.0
        self._last_rapl_energy_uj: Optional[int] = None
        self._last_rapl_timestamp: Optional[float] = None
        self._rapl_accessible: bool = False

        # hwmon temperature state
        self._temp_sensor_path: Optional[str] = None

    def initialize(self) -> bool:
        """Detect CPU details, discover RAPL and temperature interfaces."""
        self._warnings.clear()
        self._detect_cpu_model()
        self._discover_rapl()
        self._discover_temperature_sensor()
        self.is_initialized = True
        return True

    def _detect_cpu_model(self) -> None:
        """Inspect /proc/cpuinfo to identify processor model and estimate TDP."""
        try:
            with open("/proc/cpuinfo", "r", encoding="utf-8") as f:
                for line in f:
                    if line.startswith("model name"):
                        self.cpu_model = line.split(":", 1)[1].strip()
                        break
        except Exception:
            self.cpu_model = "Generic x86_64 Processor"

        if self.custom_tdp and self.custom_tdp > 0:
            self.tdp = self.custom_tdp
        else:
            self.tdp = self._lookup_tdp(self.cpu_model)

    def _lookup_tdp(self, model_name: str) -> float:
        """Estimate TDP from processor family identifier."""
        name = model_name.upper()
        # High-power desktop chips (Ryzen 9, Core i9, Threadripper)
        if any(k in name for k in ["5900X", "5950X", "7900X", "7950X", "13900K", "14900K", "12900K"]):
            return 125.0
        # Standard 65W desktop APUs and CPUs (e.g. 5600G, 5600GT, 5700G, 3600, 12400)
        if any(k in name for k in ["5600G", "5600GT", "5700G", "5600X", "3600", "5600", "12400", "13400"]):
            return 65.0
        # Ultra-low power / laptop processors
        if any(name.endswith(suffix) for suffix in ["U", "Y", "G1", "G4", "G7"]):
            return 15.0
        if any(name.endswith(suffix) for suffix in ["H", "HS", "HX"]):
            return 45.0
        return self.DEFAULT_TDP

    def _discover_rapl(self) -> None:
        """Locate Linux RAPL package energy file and check read access."""
        candidates = [
            "/sys/class/powercap/intel-rapl/intel-rapl:0/energy_uj",
            "/sys/devices/virtual/powercap/intel-rapl/intel-rapl:0/energy_uj",
        ]
        for path in candidates:
            if os.path.isfile(path):
                self._rapl_energy_path = path
                max_path = os.path.join(os.path.dirname(path), "max_energy_range_uj")
                if os.path.isfile(max_path):
                    try:
                        with open(max_path, "r", encoding="utf-8") as f:
                            self._rapl_max_range_uj = float(f.read().strip())
                    except Exception:
                        pass
                
                # Test read permissions
                try:
                    with open(path, "r", encoding="utf-8") as f:
                        f.read()
                    self._rapl_accessible = True
                except PermissionError:
                    self._rapl_accessible = False
                    self._warnings.append(
                        f"Hardware RAPL energy counter found at '{path}' but requires elevated read permissions. "
                        "Falling back to model-based power estimation. "
                        "(Tip: Run with sudo or configure a udev rule to enable direct hardware measurement)."
                    )
                except Exception as e:
                    self._rapl_accessible = False
                    self._warnings.append(f"Failed to access RAPL interface: {e}")
                break

        if not self._rapl_energy_path:
            self._warnings.append(
                "Linux RAPL powercap interface not found on this system. Falling back to TDP model estimation."
            )

    def _discover_temperature_sensor(self) -> None:
        """Find the primary CPU temperature sensor in /sys/class/hwmon."""
        for hwmon_dir in glob.glob("/sys/class/hwmon/hwmon*"):
            name_file = os.path.join(hwmon_dir, "name")
            if os.path.isfile(name_file):
                try:
                    with open(name_file, "r", encoding="utf-8") as f:
                        drv_name = f.read().strip().lower()
                    if drv_name in ["k10temp", "coretemp", "zenpower", "cpu_thermal"]:
                        temp_file = os.path.join(hwmon_dir, "temp1_input")
                        if os.path.isfile(temp_file):
                            self._temp_sensor_path = temp_file
                            break
                except Exception:
                    continue

    def _read_temperature(self) -> Optional[float]:
        """Read current CPU temperature in Celsius."""
        if self._temp_sensor_path:
            try:
                with open(self._temp_sensor_path, "r", encoding="utf-8") as f:
                    val_mc = float(f.read().strip())
                    return round(val_mc / 1000.0, 1)
            except Exception:
                pass
        return None

    def _read_rapl_power(self, now: float) -> Optional[float]:
        """Compute watts from RAPL energy_uj delta."""
        if not self._rapl_accessible or not self._rapl_energy_path:
            return None

        try:
            with open(self._rapl_energy_path, "r", encoding="utf-8") as f:
                current_uj = int(f.read().strip())
        except Exception as e:
            self._rapl_accessible = False
            self._warnings.append(f"RAPL read error: {e}")
            return None

        watts = None
        if self._last_rapl_energy_uj is not None and self._last_rapl_timestamp is not None:
            dt = now - self._last_rapl_timestamp
            if dt > 0.05:  # Require at least 50ms interval
                delta_uj = current_uj - self._last_rapl_energy_uj
                # Handle counter overflow / wraparound
                if delta_uj < 0:
                    delta_uj += self._rapl_max_range_uj
                # Convert microjoules to Joules (Watt-seconds) then divide by dt seconds
                watts = (delta_uj * 1e-6) / dt

        self._last_rapl_energy_uj = current_uj
        self._last_rapl_timestamp = now
        return watts

    def _estimate_power(self, util_pct: float, cur_freq_mhz: float, max_freq_mhz: float) -> float:
        """
        Estimate CPU power consumption from TDP, utilization, and frequency scaling.
        Formula:
          Idle floor: ~18% of TDP (SoC, I/O memory controller, uncore baseline)
          Active load: dynamic scaling proportional to utilization and frequency ratio
        """
        idle_power = self.tdp * 0.18
        max_active_power = self.tdp * 1.15  # Up to 115% of TDP during boost (e.g. AMD PPT)
        
        freq_ratio = 1.0
        if max_freq_mhz > 0:
            freq_ratio = min(max(cur_freq_mhz / max_freq_mhz, 0.4), 1.2)

        dynamic_range = max_active_power - idle_power
        # Non-linear dynamic power scaling: (util/100) * (freq_ratio)^1.2
        dynamic_power = dynamic_range * (util_pct / 100.0) * (freq_ratio ** 1.2)
        return round(idle_power + dynamic_power, 2)

    def read(self, elapsed_s: float) -> ComponentPower:
        """Sample CPU metrics and return power reading."""
        now = time.monotonic()
        
        # Telemetry metrics
        overall_util = psutil.cpu_percent(interval=None)
        per_cpu_util = psutil.cpu_percent(interval=None, percpu=True)
        freq_info = psutil.cpu_freq()
        cur_freq_mhz = freq_info.current if freq_info else 0.0
        max_freq_mhz = freq_info.max if (freq_info and freq_info.max > 0) else (cur_freq_mhz or 4000.0)
        temp_c = self._read_temperature()

        # Try direct hardware RAPL reading
        rapl_watts = self._read_rapl_power(now)

        if rapl_watts is not None and rapl_watts >= 0:
            power_watts = rapl_watts
            quality = DataQuality.MEASURED
            source = f"sysfs:rapl ({os.path.basename(os.path.dirname(self._rapl_energy_path or ''))})"
        else:
            power_watts = self._estimate_power(overall_util, cur_freq_mhz, max_freq_mhz)
            quality = DataQuality.ESTIMATED
            source = f"model:tdp_utilization (TDP={int(self.tdp)}W)"

        details = {
            "model": self.cpu_model,
            "cores": self.core_count,
            "threads": self.thread_count,
            "utilization_pct": overall_util,
            "per_core_utilization": per_cpu_util,
            "frequency_mhz": round(cur_freq_mhz, 1),
            "max_frequency_mhz": round(max_freq_mhz, 1),
            "temperature_c": temp_c,
            "tdp_watts": self.tdp,
            "rapl_supported": (self._rapl_energy_path is not None),
            "rapl_readable": self._rapl_accessible,
        }

        self.last_reading = ComponentPower(
            name=f"CPU ({self.cpu_model})",
            watts=round(power_watts, 2),
            quality=quality,
            source=source,
            is_whole_system=False,
            details=details,
        )
        return self.last_reading
