"""
Plain-text Stream Mode for Dumb Terminals and Headless Logging.
Outputs clean, unformatted, single-line telemetry records without ANSI escapes.
"""

from __future__ import annotations
import datetime
import sys
from monitors.models import SystemPowerSnapshot


class PlainTextUI:
    """Renders single-line streaming records for headless / piped execution."""

    def __init__(self, tariff_rate_lkr: float, currency: str = "LKR"):
        self.tariff_rate_lkr = tariff_rate_lkr
        self.currency = currency

    def start(self) -> None:
        """Print startup announcement banner."""
        sys.stdout.write(
            f"# PC Power Monitor Stream Started (Rate: {self.tariff_rate_lkr:.2f} {self.currency}/kWh)\n"
            "# Format: [Time | Elapsed] Power (Quality) | Avg | Peak | Energy (kWh) | Cost | Top Consumer\n"
        )
        sys.stdout.flush()

    def stop(self) -> None:
        """Stream termination notice."""
        sys.stdout.write("# PC Power Monitor Stream Stopped\n")
        sys.stdout.flush()

    def render(
        self,
        snapshot: SystemPowerSnapshot,
        total_wh: float,
        total_kwh: float,
        cost_lkr: float,
        avg_watts: float,
        peak_watts: float,
        min_watts: float,
        hourly_rate_lkr: float,
        monthly_proj_kwh: float,
        monthly_proj_lkr: float,
    ) -> None:
        """Print single telemetry line to stdout."""
        duration_str = str(datetime.timedelta(seconds=int(snapshot.elapsed_s)))
        line = (
            f"[{snapshot.iso_time} | {duration_str}] "
            f"Power: {snapshot.total_system_watts:5.1f}W ({snapshot.total_quality.value[:4]}) | "
            f"Avg: {avg_watts:5.1f}W | "
            f"Peak: {peak_watts:5.1f}W | "
            f"Energy: {total_kwh:.5f} kWh ({total_wh:.2f} Wh) | "
            f"Cost: {cost_lkr:.2f} {self.currency} | "
            f"Top: {snapshot.highest_consumer_name} ({snapshot.highest_consumer_watts:.1f}W)\n"
        )
        sys.stdout.write(line)
        sys.stdout.flush()
