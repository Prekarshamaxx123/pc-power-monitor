"""
Data models and enumerations for hardware power monitoring and energy telemetry.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, Any, List, Optional


class DataQuality(str, Enum):
    """Quality and fidelity classification for power telemetry."""
    MEASURED = "MEASURED"       # Direct reading from verified hardware sensor
    ESTIMATED = "ESTIMATED"     # Derived from telemetry model (e.g. TDP, utilization, clocks)
    UNAVAILABLE = "UNAVAILABLE" # Sensor not present or driver unsupported
    STALE = "STALE"             # Value has not refreshed within expected time window


@dataclass
class ComponentPower:
    """Represents the power and operating metrics of a single subsystem."""
    name: str
    watts: float
    quality: DataQuality
    source: str
    is_whole_system: bool = False
    details: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "watts": round(self.watts, 2),
            "quality": self.quality.value,
            "source": self.source,
            "is_whole_system": self.is_whole_system,
            "details": self.details,
        }


@dataclass
class SystemPowerSnapshot:
    """Consolidated power state of the system at a discrete point in time."""
    timestamp: float                    # Monotonic timestamp
    epoch_time: float                  # Wall clock epoch seconds
    iso_time: str                      # ISO 8601 formatted local time
    elapsed_s: float                   # Seconds elapsed since monitoring start
    components: Dict[str, ComponentPower]
    
    # Aggregated power metrics
    measured_component_watts: float    # Sum of measured component sensors
    estimated_component_watts: float   # Sum of estimated component models
    total_system_watts: float          # Final system AC/DC power rate
    total_quality: DataQuality         # Overall data quality flag
    
    # Identification of highest consumer
    highest_consumer_name: str
    highest_consumer_watts: float
    highest_consumer_quality: DataQuality
    
    # System baseline & losses
    baseline_watts: float
    psu_efficiency: float
    explanation: str
    warnings: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "timestamp": self.timestamp,
            "iso_time": self.iso_time,
            "elapsed_s": round(self.elapsed_s, 2),
            "total_system_watts": round(self.total_system_watts, 2),
            "measured_component_watts": round(self.measured_component_watts, 2),
            "estimated_component_watts": round(self.estimated_component_watts, 2),
            "total_quality": self.total_quality.value,
            "highest_consumer": f"{self.highest_consumer_name} ({round(self.highest_consumer_watts, 1)}W - {self.highest_consumer_quality.value})",
            "components": {k: v.to_dict() for k, v in self.components.items()},
            "warnings": self.warnings,
        }


@dataclass
class TariffSlab:
    """Definition for tiered electricity pricing slab."""
    min_kwh: float
    max_kwh: Optional[float]
    rate_per_kwh: float
    fixed_charge_lkr: float


@dataclass
class TariffConfig:
    """Electricity cost parameters and optional slab configuration."""
    rate_per_kwh: float = 32.50         # Default flat rate in LKR / kWh
    currency: str = "LKR"
    use_slabs: bool = False
    fuel_adjustment_pct: float = 0.0     # Fuel adjustment or surcharge percentage
    vat_pct: float = 0.0                 # Value Added Tax percentage if applicable
    slabs: List[TariffSlab] = field(default_factory=list)


@dataclass
class SessionSummary:
    """Summary metrics of a completed or queried power monitoring session."""
    session_id: str
    start_time_iso: str
    end_time_iso: str
    duration_s: float
    
    total_energy_wh: float
    total_energy_kwh: float
    total_cost_lkr: float
    
    avg_power_watts: float
    peak_power_watts: float
    min_power_watts: float
    
    highest_consumer_name: str
    highest_consumer_peak_watts: float
    
    dominant_data_quality: DataQuality
    component_averages: Dict[str, float]
    
    warnings: List[str]
    csv_file_path: Optional[str] = None
    db_file_path: Optional[str] = None
