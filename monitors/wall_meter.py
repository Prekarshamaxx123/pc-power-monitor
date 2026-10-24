"""
External Wall Power Meter / Smart Plug Interface.
Supports external AC power measurement devices (e.g. local Tasmota/Shelly smart plug API,
local telemetry socket/file). When connected, wall power provides true whole-system AC measurement,
incorporating all internal components and Power Supply Unit (PSU) conversion efficiency losses.
"""

from __future__ import annotations
import json
import os
import urllib.request
from typing import Dict, Any, Optional

from monitors.base import BaseMonitor
from monitors.models import ComponentPower, DataQuality


class WallMeterMonitor(BaseMonitor):
    """Monitors whole-system AC wall power from external smart meters or local telemetry endpoints."""

    def __init__(self, endpoint_url_or_file: Optional[str] = None):
        super().__init__(name="Wall Power Meter")
        self.endpoint = endpoint_url_or_file

    def initialize(self) -> bool:
        """Verify access to smart meter endpoint or local telemetry file."""
        self._warnings.clear()
        if not self.endpoint:
            self._warnings.append(
                "No external wall power meter configured. Desktop AC wall draw will be calculated "
                "as a modeled estimate including estimated PSU efficiency losses."
            )
            self.is_initialized = False
            return False

        if os.path.isfile(self.endpoint):
            self.is_initialized = True
            return True

        if self.endpoint.startswith(("http://", "https://")):
            # Test connection
            try:
                req = urllib.request.Request(self.endpoint, headers={"User-Agent": "pc-power-monitor"})
                with urllib.request.urlopen(req, timeout=1.5) as resp:
                    if resp.status == 200:
                        self.is_initialized = True
                        return True
            except Exception as e:
                self._warnings.append(f"Failed to reach smart meter at {self.endpoint}: {e}")
                self.is_initialized = False
                return False

        self.is_initialized = False
        return False

    def read(self, elapsed_s: float) -> Optional[ComponentPower]:
        """Fetch current AC power reading in Watts."""
        if not self.is_initialized or not self.endpoint:
            return None

        watts = None
        source = "external_meter"
        details: Dict[str, Any] = {}

        # Local JSON file endpoint
        if os.path.isfile(self.endpoint):
            try:
                with open(self.endpoint, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    watts = float(data.get("power_watts") or data.get("Power") or data.get("watts", 0.0))
                    details = data
            except Exception as e:
                self._warnings.append(f"Error reading smart meter file: {e}")
                return None

        # HTTP/JSON endpoint (e.g. Shelly / Tasmota Status 8)
        elif self.endpoint.startswith(("http://", "https://")):
            try:
                req = urllib.request.Request(self.endpoint, headers={"User-Agent": "pc-power-monitor"})
                with urllib.request.urlopen(req, timeout=1.5) as resp:
                    data = json.loads(resp.read().decode("utf-8"))
                    # Support Tasmota StatusSNS.ENERGY.Power, Shelly emeters[0].power, or simple {"watts": ...}
                    if "StatusSNS" in data and "ENERGY" in data["StatusSNS"]:
                        watts = float(data["StatusSNS"]["ENERGY"].get("Power", 0.0))
                    elif "emeters" in data and len(data["emeters"]) > 0:
                        watts = float(data["emeters"][0].get("power", 0.0))
                    elif "power" in data:
                        watts = float(data["power"])
                    elif "watts" in data:
                        watts = float(data["watts"])
                    details = data
            except Exception as e:
                return ComponentPower(
                    name="Wall Power Meter",
                    watts=0.0,
                    quality=DataQuality.STALE,
                    source="http_meter (error)",
                    is_whole_system=True,
                    details={"error": str(e)},
                )

        if watts is not None:
            self.last_reading = ComponentPower(
                name="Wall Power Meter (Whole-System AC)",
                watts=round(watts, 2),
                quality=DataQuality.MEASURED,
                source=source,
                is_whole_system=True,
                details=details,
            )
            return self.last_reading

        return None
