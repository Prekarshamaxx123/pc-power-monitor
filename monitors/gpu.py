"""
GPU Telemetry and Power Monitor.
Supports NVIDIA GPUs via nvidia-smi with direct power draw reading,
automatic detection of non-metered cards (e.g. GTX 1650 PCIe slot-powered) with
transparent estimation fallback, AMD GPUs via Linux sysfs hwmon/drm, and Intel graphics.
"""

from __future__ import annotations
import glob
import os
import shutil
import subprocess
from typing import Dict, Any, List, Optional

from monitors.base import BaseMonitor
from monitors.models import ComponentPower, DataQuality


class GPUMonitor(BaseMonitor):
    """Monitors discrete and integrated GPU telemetry and power consumption."""

    def __init__(self):
        super().__init__(name="GPU")
        self.gpu_type: Optional[str] = None  # "nvidia", "amd", "intel", or None
        self.device_name: str = "Unknown GPU"
        self._nvidia_smi_path: Optional[str] = None
        self._amd_hwmon_path: Optional[str] = None
        self._power_limit_watts: float = 75.0

    def initialize(self) -> bool:
        """Discover GPU vendor interfaces and detect supported query capabilities."""
        self._warnings.clear()

        # Check NVIDIA
        nvidia_path = shutil.which("nvidia-smi")
        if nvidia_path:
            try:
                result = subprocess.run(
                    [nvidia_path, "--query-gpu=name,power.limit", "--format=csv,noheader,nounits"],
                    capture_output=True,
                    text=True,
                    timeout=2,
                    check=False,
                )
                if result.returncode == 0 and result.stdout.strip():
                    parts = [p.strip() for p in result.stdout.strip().split(",")]
                    self.device_name = parts[0]
                    if len(parts) > 1:
                        try:
                            self._power_limit_watts = float(parts[1])
                        except ValueError:
                            pass
                    self.gpu_type = "nvidia"
                    self._nvidia_smi_path = nvidia_path
                    self.is_initialized = True
                    return True
            except Exception as e:
                self._warnings.append(f"Error querying nvidia-smi: {e}")

        # Check AMD drm/hwmon
        for drm_dir in glob.glob("/sys/class/drm/card*/device/hwmon/hwmon*"):
            power_avg = os.path.join(drm_dir, "power1_average")
            power_input = os.path.join(drm_dir, "power1_input")
            if os.path.isfile(power_avg) or os.path.isfile(power_input):
                self._amd_hwmon_path = drm_dir
                self.gpu_type = "amd"
                self.device_name = "AMD Radeon Graphics"
                self.is_initialized = True
                return True

        # Check Intel iGPU (DRM / powercap)
        if os.path.isdir("/sys/class/drm/card0/device/driver") and "i915" in os.path.realpath("/sys/class/drm/card0/device/driver"):
            self.gpu_type = "intel"
            self.device_name = "Intel HD/Iris Graphics"
            self.is_initialized = True
            return True

        self._warnings.append("No supported GPU telemetry interface detected.")
        self.is_initialized = False
        return False

    def _read_nvidia(self) -> ComponentPower:
        """Query NVIDIA GPU metrics via nvidia-smi."""
        query_fields = [
            "index",
            "name",
            "power.draw",
            "power.limit",
            "utilization.gpu",
            "utilization.memory",
            "temperature.gpu",
            "memory.total",
            "memory.used",
            "clocks.current.graphics",
            "clocks.max.graphics",
        ]
        cmd = [
            self._nvidia_smi_path or "nvidia-smi",
            f"--query-gpu={','.join(query_fields)}",
            "--format=csv,noheader,nounits",
        ]

        try:
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=2, check=False)
            if res.returncode != 0:
                return ComponentPower(
                    name=self.device_name,
                    watts=0.0,
                    quality=DataQuality.UNAVAILABLE,
                    source="nvidia-smi (error)",
                    details={"error": res.stderr.strip()},
                )

            parts = [p.strip() for p in res.stdout.strip().split(",")]
            if len(parts) < len(query_fields):
                return ComponentPower(
                    name=self.device_name,
                    watts=0.0,
                    quality=DataQuality.UNAVAILABLE,
                    source="nvidia-smi (malformed)",
                )

            name = parts[1]
            raw_power = parts[2]
            raw_limit = parts[3]
            raw_gpu_util = parts[4]
            raw_mem_util = parts[5]
            raw_temp = parts[6]
            raw_mem_total = parts[7]
            raw_mem_used = parts[8]
            raw_clock_cur = parts[9]
            raw_clock_max = parts[10]

            gpu_util = float(raw_gpu_util) if raw_gpu_util.replace(".", "", 1).isdigit() else 0.0
            temp_c = float(raw_temp) if raw_temp.replace(".", "", 1).isdigit() else None
            mem_total = float(raw_mem_total) if raw_mem_total.replace(".", "", 1).isdigit() else 0.0
            mem_used = float(raw_mem_used) if raw_mem_used.replace(".", "", 1).isdigit() else 0.0
            clock_cur = float(raw_clock_cur) if raw_clock_cur.replace(".", "", 1).isdigit() else 0.0
            clock_max = float(raw_clock_max) if raw_clock_max.replace(".", "", 1).isdigit() else (clock_cur or 1800.0)

            # Determine whether hardware power draw is measured or requires estimation
            is_measured = False
            measured_watts = 0.0
            try:
                measured_watts = float(raw_power)
                is_measured = True
            except ValueError:
                is_measured = False

            if is_measured:
                watts = measured_watts
                quality = DataQuality.MEASURED
                source = "nvidia-smi (hw sensor)"
            else:
                # Slot-powered cards (e.g. GTX 1650) lack internal shunt power sensors.
                # Estimate power based on GPU limit, idle floor, utilization, and clock ratio.
                idle_power = 8.0  # ~8W idle for Pascal/Turing low-power desktop GPUs
                limit = self._power_limit_watts or 75.0
                clock_ratio = (clock_cur / clock_max) if clock_max > 0 else 0.5
                watts = idle_power + (gpu_util / 100.0) * (limit - idle_power) * max(clock_ratio, 0.4)
                quality = DataQuality.ESTIMATED
                source = f"model:nvidia_slot_limit (limit={int(limit)}W)"

            details = {
                "vendor": "NVIDIA",
                "name": name,
                "utilization_pct": gpu_util,
                "temperature_c": temp_c,
                "vram_total_mb": mem_total,
                "vram_used_mb": mem_used,
                "vram_used_pct": round((mem_used / mem_total * 100), 1) if mem_total > 0 else 0.0,
                "clock_graphics_mhz": clock_cur,
                "clock_graphics_max_mhz": clock_max,
                "power_limit_watts": self._power_limit_watts,
                "sensor_reported": is_measured,
            }

            return ComponentPower(
                name=f"GPU ({name})",
                watts=round(watts, 2),
                quality=quality,
                source=source,
                details=details,
            )

        except subprocess.TimeoutExpired:
            return ComponentPower(
                name=self.device_name,
                watts=0.0,
                quality=DataQuality.STALE,
                source="nvidia-smi (timeout)",
            )
        except Exception as e:
            return ComponentPower(
                name=self.device_name,
                watts=0.0,
                quality=DataQuality.UNAVAILABLE,
                source="nvidia-smi (failed)",
                details={"error": str(e)},
            )

    def _read_amd(self) -> ComponentPower:
        """Read AMD GPU power and telemetry from sysfs."""
        if not self._amd_hwmon_path:
            return ComponentPower(name=self.device_name, watts=0.0, quality=DataQuality.UNAVAILABLE, source="amd_sysfs")

        watts = 0.0
        quality = DataQuality.UNAVAILABLE
        source = "amd_sysfs"

        # Try power1_average or power1_input (microwatts)
        for attr in ["power1_average", "power1_input"]:
            p_file = os.path.join(self._amd_hwmon_path, attr)
            if os.path.isfile(p_file):
                try:
                    with open(p_file, "r", encoding="utf-8") as f:
                        watts = float(f.read().strip()) / 1e6
                        quality = DataQuality.MEASURED
                        source = f"sysfs:{attr}"
                        break
                except Exception:
                    continue

        temp_c = None
        t_file = os.path.join(self._amd_hwmon_path, "temp1_input")
        if os.path.isfile(t_file):
            try:
                with open(t_file, "r", encoding="utf-8") as f:
                    temp_c = float(f.read().strip()) / 1000.0
            except Exception:
                pass

        details = {
            "vendor": "AMD",
            "name": self.device_name,
            "temperature_c": temp_c,
        }

        return ComponentPower(
            name=f"GPU ({self.device_name})",
            watts=round(watts, 2),
            quality=quality,
            source=source,
            details=details,
        )

    def read(self, elapsed_s: float) -> Optional[ComponentPower]:
        """Sample GPU power and telemetry."""
        if not self.is_initialized:
            return None

        if self.gpu_type == "nvidia":
            self.last_reading = self._read_nvidia()
        elif self.gpu_type == "amd":
            self.last_reading = self._read_amd()
        else:
            self.last_reading = None

        return self.last_reading
