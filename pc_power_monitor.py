#!/usr/bin/env python3
"""
Linux PC Power Monitor & Electricity Cost Analyzer.

Continuously monitors hardware telemetry, integrates dynamic energy consumption,
calculates electricity expenditure in Sri Lankan Rupees (LKR), identifies peak
consuming components, and saves audit-ready logs to CSV and SQLite.
"""

from __future__ import annotations
import argparse
import datetime
import json
import os
import signal
import sys
import time
from typing import Dict, Any, List, Optional

from monitors.models import (
    DataQuality,
    TariffConfig,
    SessionSummary,
    SystemPowerSnapshot,
)
from monitors.aggregator import PowerAggregator
from core.energy import EnergyTracker
from core.cost import CostCalculator
from core.storage import DataLogger
from ui.dashboard import DashboardUI
from ui.plain import PlainTextUI
from ui.report import ReportUI


class PowerMonitorApp:
    """Main application orchestrator."""

    def __init__(self, args: argparse.Namespace):
        self.args = args
        self.running = False
        self._interrupted = False

        # Load optional config file if specified or present
        self.config_data = self._load_config(args.config)

        # Resolve parameters with CLI precedence over config file
        self.interval = max(float(self._get_param("interval", args.interval, 1.0)), 0.2)
        self.rate_per_kwh = float(self._get_param("rate", args.rate, 32.50))
        self.baseline_watts = float(self._get_param("baseline_watts", args.baseline_watts, 40.0))
        self.psu_efficiency = float(self._get_param("psu_efficiency", args.psu_efficiency, 85.0)) / 100.0
        self.output_dir = str(self._get_param("output", args.output, "./power_logs"))
        self.plain_mode = bool(self._get_param("plain", args.plain, False))
        self.use_slabs = bool(self._get_param("slab", args.slab, False))
        self.custom_tdp = self._get_param("custom_tdp", args.custom_tdp, None)
        if self.custom_tdp is not None:
            self.custom_tdp = float(self.custom_tdp)
        self.wall_meter_endpoint = self._get_param("wall_meter", args.wall_meter, None)
        self.currency = str(self._get_param("currency", args.currency, "LKR"))

        # Setup Core Subsystems
        self.tariff_config = TariffConfig(
            rate_per_kwh=self.rate_per_kwh,
            currency=self.currency,
            use_slabs=self.use_slabs,
        )
        self.cost_calculator = CostCalculator(self.tariff_config)
        self.energy_tracker = EnergyTracker()
        self.aggregator = PowerAggregator(
            baseline_watts=self.baseline_watts,
            psu_efficiency=self.psu_efficiency,
            custom_tdp=self.custom_tdp,
            wall_meter_endpoint=self.wall_meter_endpoint,
        )
        self.logger = DataLogger(output_dir=self.output_dir)

        # Setup UI
        if self.plain_mode:
            self.ui = PlainTextUI(tariff_rate_lkr=self.rate_per_kwh, currency=self.currency)
        else:
            self.ui = DashboardUI(tariff_rate_lkr=self.rate_per_kwh, currency=self.currency)

        # Tracking metrics for terminal session report
        self.start_iso = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.component_power_sums: Dict[str, float] = {}
        self.component_sample_counts: Dict[str, int] = {}
        self.dominant_quality: DataQuality = DataQuality.ESTIMATED
        self.highest_consumer_peak_name: str = "None"
        self.highest_consumer_peak_watts: float = 0.0

        # Register termination signal handlers
        signal.signal(signal.SIGINT, self._handle_signal)
        signal.signal(signal.SIGTERM, self._handle_signal)

    def _load_config(self, config_path: Optional[str]) -> Dict[str, Any]:
        """Load JSON configuration file if specified."""
        search_paths = []
        if config_path:
            search_paths.append(config_path)
        else:
            search_paths.extend(["config.json", os.path.expanduser("~/.config/pc-power-monitor/config.json")])

        for path in search_paths:
            if os.path.isfile(path):
                try:
                    with open(path, "r", encoding="utf-8") as f:
                        return json.load(f)
                except Exception as e:
                    sys.stderr.write(f"Warning: Failed to parse configuration file '{path}': {e}\n")
        return {}

    def _get_param(self, key: str, cli_val: Any, default_val: Any) -> Any:
        """Resolve parameter value: CLI flag -> Config File -> Default."""
        if cli_val is not None and cli_val is not False:
            return cli_val
        if key in self.config_data:
            return self.config_data[key]
        return default_val

    def _handle_signal(self, signum: int, frame: Any) -> None:
        """Gracefully handle Ctrl+C or termination signal."""
        self.running = False
        self._interrupted = True

    def run(self) -> None:
        """Execute the continuous monitoring loop."""
        self.running = True
        self.logger.start_session_record(tariff_rate_lkr=self.rate_per_kwh)
        self.ui.start()

        session_start_mono = time.monotonic()

        try:
            while self.running:
                loop_start = time.monotonic()
                elapsed_s = loop_start - session_start_mono

                # 1. Sample all hardware telemetry and calculate total power
                snapshot = self.aggregator.sample(elapsed_s)

                # 2. Extract internal component readings for individual energy tracking
                comp_readings = {
                    comp.name: comp.watts
                    for comp in snapshot.components.values()
                    if not comp.is_whole_system
                }

                # 3. Integrate energy using monotonic trapezoidal rule
                total_wh, total_kwh = self.energy_tracker.update(
                    current_watts=snapshot.total_system_watts,
                    current_mono=loop_start,
                    component_readings=comp_readings,
                )

                # 4. Calculate cost metrics
                cost_lkr = self.cost_calculator.calculate_session_cost(total_kwh)
                hourly_lkr = self.cost_calculator.calculate_run_rate_hourly(snapshot.total_system_watts)
                monthly_kwh, monthly_lkr, _ = self.cost_calculator.project_monthly_cost(
                    self.energy_tracker.average_watts
                )

                # 5. Track statistics for exit summary
                if snapshot.total_quality == DataQuality.MEASURED:
                    self.dominant_quality = DataQuality.MEASURED
                if snapshot.highest_consumer_watts > self.highest_consumer_peak_watts:
                    self.highest_consumer_peak_watts = snapshot.highest_consumer_watts
                    self.highest_consumer_peak_name = snapshot.highest_consumer_name

                for c_name, c_watts in comp_readings.items():
                    self.component_power_sums[c_name] = self.component_power_sums.get(c_name, 0.0) + c_watts
                    self.component_sample_counts[c_name] = self.component_sample_counts.get(c_name, 0) + 1

                # 6. Stream record to CSV and SQLite
                self.logger.log(snapshot, total_wh, total_kwh, cost_lkr)

                # 7. Render UI
                self.ui.render(
                    snapshot=snapshot,
                    total_wh=total_wh,
                    total_kwh=total_kwh,
                    cost_lkr=cost_lkr,
                    avg_watts=self.energy_tracker.average_watts,
                    peak_watts=self.energy_tracker.peak_watts,
                    min_watts=self.energy_tracker.min_watts if self.energy_tracker.min_watts != float("inf") else snapshot.total_system_watts,
                    hourly_rate_lkr=hourly_lkr,
                    monthly_proj_kwh=monthly_kwh,
                    monthly_proj_lkr=monthly_lkr,
                )

                # 8. Precise sleep interval avoiding drift
                elapsed_tick = time.monotonic() - loop_start
                sleep_time = max(self.interval - elapsed_tick, 0.05)
                time.sleep(sleep_time)

        finally:
            self._shutdown()

    def _shutdown(self) -> None:
        """Perform orderly shutdown, finalize logs, and print summary."""
        self.ui.stop()
        self.aggregator.cleanup()

        end_iso = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        duration_s = self.energy_tracker.elapsed_seconds

        # Compute component averages
        comp_averages = {
            name: round(self.component_power_sums[name] / max(self.component_sample_counts[name], 1), 2)
            for name in self.component_power_sums
        }

        min_w = self.energy_tracker.min_watts if self.energy_tracker.min_watts != float("inf") else 0.0

        summary = SessionSummary(
            session_id=self.logger.session_id,
            start_time_iso=self.start_iso,
            end_time_iso=end_iso,
            duration_s=duration_s,
            total_energy_wh=self.energy_tracker.total_wh,
            total_energy_kwh=self.energy_tracker.total_kwh,
            total_cost_lkr=self.cost_calculator.calculate_session_cost(self.energy_tracker.total_kwh),
            avg_power_watts=self.energy_tracker.average_watts,
            peak_power_watts=self.energy_tracker.peak_watts,
            min_power_watts=min_w,
            highest_consumer_name=self.highest_consumer_peak_name,
            highest_consumer_peak_watts=self.highest_consumer_peak_watts,
            dominant_data_quality=self.dominant_quality,
            component_averages=comp_averages,
            warnings=self.aggregator.get_all_warnings(),
            csv_file_path=self.logger.csv_path,
            db_file_path=self.logger.db_path,
        )

        # Finalize SQLite & CSV handles
        self.logger.finalize_session(summary)

        # Print final session report
        ReportUI.print_session_summary(summary, currency=self.currency)


def show_historical_report(output_dir: str, currency: str = "LKR") -> None:
    """Display past monitoring sessions stored in SQLite."""
    db_path = os.path.join(os.path.abspath(output_dir), "power_monitor.db")
    sessions = DataLogger.get_historical_sessions(db_path)
    ReportUI.print_historical_sessions(sessions, currency=currency)


def parse_arguments() -> argparse.Namespace:
    """Parse and validate command line arguments."""
    parser = argparse.ArgumentParser(
        prog="pc-power-monitor",
        description="Linux PC Power Consumption Monitor & Electricity Cost Analyzer (LKR/kWh).",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )

    parser.add_argument(
        "--interval",
        type=float,
        default=None,
        help="Telemetry sampling and dashboard refresh interval in seconds (default: 1.0).",
    )
    parser.add_argument(
        "--rate",
        type=float,
        default=None,
        help="Electricity tariff rate in LKR per kWh (default: 32.50 LKR/kWh).",
    )
    parser.add_argument(
        "--baseline-watts",
        type=float,
        default=None,
        help="Baseline idle system power floor in Watts (default: 40.0W). Never treated as measured.",
    )
    parser.add_argument(
        "--output",
        type=str,
        default=None,
        help="Directory path to save CSV telemetry logs and SQLite database (default: ./power_logs).",
    )
    parser.add_argument(
        "--plain",
        action="store_true",
        default=None,
        help="Enable plain-text stream mode without ANSI escapes (ideal for dumb terminals, ssh, pipes).",
    )
    parser.add_argument(
        "--report",
        action="store_true",
        help="Display historical monitoring sessions from the SQLite database and exit.",
    )
    parser.add_argument(
        "--slab",
        action="store_true",
        default=None,
        help="Enable Sri Lankan CEB/LECO tiered domestic slab model for monthly cost projections.",
    )
    parser.add_argument(
        "--psu-efficiency",
        type=float,
        default=None,
        help="Estimated Power Supply Unit (PSU) conversion efficiency percentage (default: 85%%).",
    )
    parser.add_argument(
        "--custom-tdp",
        type=float,
        default=None,
        help="Manually override CPU Thermal Design Power (TDP) in Watts.",
    )
    parser.add_argument(
        "--wall-meter",
        type=str,
        default=None,
        help="HTTP URL or JSON file path for external AC smart power meter telemetry.",
    )
    parser.add_argument(
        "--currency",
        type=str,
        default="LKR",
        help="Currency code for cost reporting (default: LKR).",
    )
    parser.add_argument(
        "--config",
        type=str,
        default=None,
        help="Path to custom JSON configuration file.",
    )

    args = parser.parse_args()

    # Validations
    if args.interval is not None and args.interval <= 0:
        parser.error("--interval must be a positive number greater than 0.")
    if args.rate is not None and args.rate < 0:
        parser.error("--rate must be a non-negative number.")
    if args.baseline_watts is not None and args.baseline_watts < 0:
        parser.error("--baseline-watts must be a non-negative number.")
    if args.psu_efficiency is not None and not (50.0 <= args.psu_efficiency <= 99.0):
        parser.error("--psu-efficiency must be between 50%% and 99%%.")

    return args


def main() -> None:
    """Entry point."""
    args = parse_arguments()

    if args.report:
        out_dir = args.output or "./power_logs"
        show_historical_report(out_dir, currency=args.currency)
        sys.exit(0)

    app = PowerMonitorApp(args)
    app.run()


if __name__ == "__main__":
    main()
