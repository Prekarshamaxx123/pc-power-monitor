"""
Power Aggregator and Double-Counting Prevention Engine.
Coordinates subsystem monitors, enforces rigorous separation between measured hardware
telemetry and modeled estimates, prevents double counting, identifies the peak component consumer,
and models power supply unit (PSU) conversion efficiency losses.
"""

from __future__ import annotations
import datetime
import time
from typing import Dict, Any, List, Optional

from monitors.base import BaseMonitor
from monitors.cpu import CPUMonitor
from monitors.gpu import GPUMonitor
from monitors.memory import MemoryMonitor
from monitors.storage import StorageMonitor
from monitors.fans import FanMonitor
from monitors.battery import BatteryMonitor
from monitors.wall_meter import WallMeterMonitor
from monitors.models import (
    ComponentPower,
    DataQuality,
    SystemPowerSnapshot,
)


class PowerAggregator:
    """Aggregates all hardware power telemetry into a unified, non-double-counted system state."""

    # Default Motherboard Chipset (A520/B550/X570 PCIe lane muxing, audio, LAN, USB logic)
    DEFAULT_MOTHERBOARD_WATTS = 12.0
    DEFAULT_PSU_EFFICIENCY = 0.85  # 85% typical 80 PLUS Bronze/Gold efficiency

    def __init__(
        self,
        baseline_watts: float = 40.0,
        psu_efficiency: float = 0.85,
        custom_tdp: Optional[float] = None,
        wall_meter_endpoint: Optional[str] = None,
    ):
        self.baseline_watts = max(baseline_watts, 0.0)
        self.psu_efficiency = min(max(psu_efficiency, 0.50), 0.98)
        self.custom_tdp = custom_tdp
        self.wall_meter_endpoint = wall_meter_endpoint

        # Subsystem monitors
        self.monitors: Dict[str, BaseMonitor] = {}
        self._init_monitors()

    def _init_monitors(self) -> None:
        """Instantiate and initialize all available subsystem monitors."""
        self.monitors["cpu"] = CPUMonitor(custom_tdp=self.custom_tdp)
        self.monitors["gpu"] = GPUMonitor()
        self.monitors["ram"] = MemoryMonitor()
        self.monitors["storage"] = StorageMonitor()
        self.monitors["fans"] = FanMonitor()
        self.monitors["battery"] = BatteryMonitor()
        self.monitors["wall_meter"] = WallMeterMonitor(self.wall_meter_endpoint)

        for name, mon in self.monitors.items():
            mon.initialize()

    def get_all_warnings(self) -> List[str]:
        """Collect all active warnings and recommendations across monitors."""
        all_warns = []
        for mon in self.monitors.values():
            all_warns.extend(mon.get_warnings())
        return all_warns

    def sample(self, elapsed_s: float) -> SystemPowerSnapshot:
        """
        Poll all monitors, prevent double counting, and construct a system snapshot.
        """
        now_mono = time.monotonic()
        now_epoch = time.time()
        iso_time = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        raw_readings: Dict[str, ComponentPower] = {}
        all_warnings: List[str] = []

        # 1. Collect readings from each active monitor
        for key, mon in self.monitors.items():
            reading = mon.read(elapsed_s)
            if reading is not None:
                raw_readings[key] = reading
            all_warnings.extend(mon.get_warnings())

        # 2. Add Motherboard Chipset baseline (logic, audio codec, NIC)
        raw_readings["motherboard"] = ComponentPower(
            name="Motherboard Chipset & Logic",
            watts=self.DEFAULT_MOTHERBOARD_WATTS,
            quality=DataQuality.ESTIMATED,
            source="model:chipset_baseline",
            is_whole_system=False,
            details={"notes": "Covers A520/B550 VRM controller, PCIe bus logic, audio, and NIC PHY"},
        )

        # 3. Check for Whole-System Physical Sensors (Wall Meter or Laptop Battery)
        whole_system_reading: Optional[ComponentPower] = None
        if "wall_meter" in raw_readings and raw_readings["wall_meter"].quality == DataQuality.MEASURED:
            whole_system_reading = raw_readings["wall_meter"]
        elif "battery" in raw_readings and raw_readings["battery"].is_whole_system:
            whole_system_reading = raw_readings["battery"]

        # 4. Calculate Component Breakdown and Avoid Double-Counting
        measured_component_watts = 0.0
        estimated_component_watts = 0.0
        highest_consumer_name = "None"
        highest_consumer_watts = 0.0
        highest_consumer_quality = DataQuality.UNAVAILABLE

        for key, comp in raw_readings.items():
            # Skip whole-system sensors when computing internal component hierarchy
            if comp.is_whole_system:
                continue

            if comp.quality == DataQuality.MEASURED:
                measured_component_watts += comp.watts
            elif comp.quality == DataQuality.ESTIMATED:
                estimated_component_watts += comp.watts

            # Track highest power consumer
            if comp.watts > highest_consumer_watts:
                highest_consumer_watts = comp.watts
                highest_consumer_name = comp.name
                highest_consumer_quality = comp.quality

        # 5. Determine Total System Power and Overall Data Quality
        if whole_system_reading is not None:
            # Whole-system sensor is active: TRUE MEASURED whole-system power
            total_system_watts = whole_system_reading.watts
            total_quality = DataQuality.MEASURED
            explanation = (
                f"Whole-system AC/DC power directly measured via {whole_system_reading.name} "
                f"({whole_system_reading.source}). Internal component breakdown shown for analysis."
            )
        else:
            # Desktop without physical AC meter:
            # Modeled sum of internal components plus PSU AC-to-DC conversion losses
            internal_dc_watts = measured_component_watts + estimated_component_watts
            estimated_ac_wall_watts = internal_dc_watts / self.psu_efficiency

            # Enforce user baseline floor if component sum is lower
            if estimated_ac_wall_watts < self.baseline_watts:
                total_system_watts = self.baseline_watts
                explanation = (
                    f"Configured baseline floor ({self.baseline_watts}W) applied. "
                    f"Calculated component sum ({round(internal_dc_watts, 1)}W DC / "
                    f"{round(estimated_ac_wall_watts, 1)}W AC at {int(self.psu_efficiency * 100)}% PSU efficiency)."
                )
            else:
                total_system_watts = round(estimated_ac_wall_watts, 2)
                explanation = (
                    f"Calculated AC wall estimate ({round(total_system_watts, 1)}W) = "
                    f"[Internal DC ({round(internal_dc_watts, 1)}W: {round(measured_component_watts, 1)}W measured + "
                    f"{round(estimated_component_watts, 1)}W estimated)] / {int(self.psu_efficiency * 100)}% PSU efficiency. "
                    "A physical wall power meter (e.g. smart plug) is required for exact AC wall measurements."
                )

            # If any primary component is measured, overall quality reflects hybrid estimation
            if measured_component_watts > 0:
                total_quality = DataQuality.ESTIMATED
            else:
                total_quality = DataQuality.ESTIMATED

        return SystemPowerSnapshot(
            timestamp=now_mono,
            epoch_time=now_epoch,
            iso_time=iso_time,
            elapsed_s=elapsed_s,
            components=raw_readings,
            measured_component_watts=round(measured_component_watts, 2),
            estimated_component_watts=round(estimated_component_watts, 2),
            total_system_watts=round(total_system_watts, 2),
            total_quality=total_quality,
            highest_consumer_name=highest_consumer_name,
            highest_consumer_watts=round(highest_consumer_watts, 2),
            highest_consumer_quality=highest_consumer_quality,
            baseline_watts=self.baseline_watts,
            psu_efficiency=self.psu_efficiency,
            explanation=explanation,
            warnings=list(dict.fromkeys(all_warnings)),  # Deduplicate warnings
        )

    def cleanup(self) -> None:
        """Cleanly terminate all monitors."""
        for mon in self.monitors.values():
            mon.cleanup()
