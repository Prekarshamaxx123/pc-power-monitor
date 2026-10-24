"""
Storage Telemetry and Power Monitor.
Tracks disk I/O activity (read/write rates), discovered physical drives (NVMe, SATA SSD, HDD),
storage hardware temperatures from hwmon, and models dynamic storage power draw.
"""

from __future__ import annotations
import glob
import os
import time
from typing import Dict, Any, List, Optional
import psutil

from monitors.base import BaseMonitor
from monitors.models import ComponentPower, DataQuality


class StorageMonitor(BaseMonitor):
    """Monitors storage device I/O traffic, temperatures, and estimated power draw."""

    def __init__(self):
        super().__init__(name="Storage")
        self.devices: List[str] = []
        self._last_io: Optional[Any] = None
        self._last_time: Optional[float] = None
        self._nvme_temp_path: Optional[str] = None

    def initialize(self) -> bool:
        """Discover active storage drives and NVMe temperature sensors."""
        self._warnings.clear()
        try:
            # Discover block devices in /sys/block excluding virtual loop/zram devices
            for dev in os.listdir("/sys/block"):
                if dev.startswith(("nvme", "sd", "hd")):
                    self.devices.append(dev)

            # Discover NVMe temperature sensor
            for hwmon in glob.glob("/sys/class/hwmon/hwmon*"):
                name_file = os.path.join(hwmon, "name")
                if os.path.isfile(name_file):
                    try:
                        with open(name_file, "r", encoding="utf-8") as f:
                            if "nvme" in f.read().strip():
                                temp_file = os.path.join(hwmon, "temp1_input")
                                if os.path.isfile(temp_file):
                                    self._nvme_temp_path = temp_file
                                    break
                    except Exception:
                        pass

            self._last_io = psutil.disk_io_counters()
            self._last_time = time.monotonic()
            self.is_initialized = True
            return True
        except Exception as e:
            self._warnings.append(f"Failed to inspect storage devices: {e}")
            self.is_initialized = False
            return False

    def _read_nvme_temperature(self) -> Optional[float]:
        """Read primary NVMe drive temperature in Celsius."""
        if self._nvme_temp_path:
            try:
                with open(self._nvme_temp_path, "r", encoding="utf-8") as f:
                    return round(float(f.read().strip()) / 1000.0, 1)
            except Exception:
                pass
        return None

    def read(self, elapsed_s: float) -> ComponentPower:
        """Sample I/O traffic rates and compute estimated storage power."""
        now = time.monotonic()
        cur_io = psutil.disk_io_counters()
        dt = (now - self._last_time) if self._last_time else 1.0

        read_mb_s = 0.0
        write_mb_s = 0.0
        if cur_io and self._last_io and dt > 0.1:
            read_bytes_delta = cur_io.read_bytes - self._last_io.read_bytes
            write_bytes_delta = cur_io.write_bytes - self._last_io.write_bytes
            read_mb_s = (read_bytes_delta / (1024 * 1024)) / dt
            write_mb_s = (write_bytes_delta / (1024 * 1024)) / dt

        self._last_io = cur_io
        self._last_time = now

        # Power model:
        # Base standby: ~0.8W per active drive
        # Dynamic I/O power: scales with active throughput (up to +3.5W under full saturated bus traffic)
        drive_count = max(len(self.devices), 1)
        base_power = drive_count * 0.8
        total_throughput_mb_s = read_mb_s + write_mb_s
        dynamic_power = min(3.5, (total_throughput_mb_s / 500.0) * 2.5)
        estimated_watts = round(base_power + dynamic_power, 2)

        nvme_temp = self._read_nvme_temperature()

        details = {
            "drives_detected": self.devices,
            "drive_count": len(self.devices),
            "read_rate_mb_s": round(read_mb_s, 2),
            "write_rate_mb_s": round(write_mb_s, 2),
            "nvme_temperature_c": nvme_temp,
        }

        self.last_reading = ComponentPower(
            name=f"Storage ({len(self.devices)} drive{'s' if len(self.devices) != 1 else ''})",
            watts=estimated_watts,
            quality=DataQuality.ESTIMATED,
            source="model:nvme_sata_io",
            details=details,
        )
        return self.last_reading
