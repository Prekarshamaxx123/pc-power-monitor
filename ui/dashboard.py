"""
Terminal Live Dashboard for PC Power Monitor.
Renders an auto-refreshing rich console interface with live telemetry,
power gauges, cost projections, and component power breakdown.
Includes robust ANSI fallback for systems without rich installed.
"""

from __future__ import annotations
import datetime
import os
import sys
from typing import Dict, Any, List, Optional

try:
    from rich.console import Console, Group
    from rich.layout import Layout
    from rich.live import Live
    from rich.panel import Panel
    from rich.table import Table
    from rich.text import Text
    from rich import box
    RICH_AVAILABLE = True
except ImportError:
    RICH_AVAILABLE = False

from monitors.models import SystemPowerSnapshot, DataQuality


class DashboardUI:
    """Renders interactive real-time terminal UI."""

    def __init__(self, tariff_rate_lkr: float, currency: str = "LKR"):
        self.tariff_rate_lkr = tariff_rate_lkr
        self.currency = currency
        self.console = Console() if RICH_AVAILABLE else None
        self.live = None

    def start(self) -> None:
        """Start the live rich console display."""
        if RICH_AVAILABLE and self.console:
            self.live = Live(console=self.console, refresh_per_second=4, screen=False)
            self.live.start()

    def stop(self) -> None:
        """Stop live display and restore terminal cursor."""
        if self.live:
            try:
                self.live.stop()
            except Exception:
                pass
            self.live = None

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
        """Update terminal dashboard with current snapshot and metrics."""
        if RICH_AVAILABLE and self.live:
            renderable = self._build_rich_layout(
                snapshot, total_wh, total_kwh, cost_lkr,
                avg_watts, peak_watts, min_watts,
                hourly_rate_lkr, monthly_proj_kwh, monthly_proj_lkr
            )
            self.live.update(renderable)
        else:
            self._render_ansi_fallback(
                snapshot, total_wh, total_kwh, cost_lkr,
                avg_watts, peak_watts, min_watts,
                hourly_rate_lkr, monthly_proj_kwh, monthly_proj_lkr
            )

    def _build_rich_layout(
        self,
        s: SystemPowerSnapshot,
        total_wh: float,
        total_kwh: float,
        cost_lkr: float,
        avg_watts: float,
        peak_watts: float,
        min_watts: float,
        hourly_rate_lkr: float,
        monthly_proj_kwh: float,
        monthly_proj_lkr: float,
    ) -> Any:
        """Construct structured Rich UI layout."""
        duration_str = str(datetime.timedelta(seconds=int(s.elapsed_s)))

        # Header Table: Current Status
        header_table = Table.grid(expand=True)
        header_table.add_column(justify="left", ratio=1)
        header_table.add_column(justify="right", ratio=1)

        # Quality styling
        quality_color = "green" if s.total_quality == DataQuality.MEASURED else "yellow"
        quality_text = f"[{quality_color} bold]{s.total_quality.value}[/{quality_color} bold]"

        header_table.add_row(
            Text.from_markup(f"[bold cyan]Linux PC Power Monitor & Cost Analyzer[/bold cyan]"),
            Text.from_markup(f"[dim]Time:[/dim] [white]{s.iso_time}[/white] | [dim]Elapsed:[/dim] [bold green]{duration_str}[/bold green]"),
        )

        # Power & Energy Metrics Grid
        metrics_table = Table(box=box.ROUNDED, expand=True, show_header=True, header_style="bold magenta")
        metrics_table.add_column("Current Power", justify="center", style="bold green")
        metrics_table.add_column("Average / Peak", justify="center")
        metrics_table.add_column("Units Consumed", justify="center", style="bold cyan")
        metrics_table.add_column(f"Electricity Cost ({self.currency})", justify="center", style="bold yellow")
        metrics_table.add_column("Projected Monthly", justify="center")

        cur_power_str = f"[bold white]{s.total_system_watts:.1f} W[/bold white]\n[dim]Quality: {quality_text}[/dim]"
        avg_peak_str = f"Avg: [cyan]{avg_watts:.1f} W[/cyan]\nPeak: [red]{peak_watts:.1f} W[/red]"
        energy_str = f"[bold cyan]{total_kwh:.4f} Units[/bold cyan]\n[dim]({total_kwh:.4f} kWh)[/dim]"
        cost_str = f"[bold yellow]{cost_lkr:.2f} {self.currency}[/bold yellow]\n[dim]({self.tariff_rate_lkr:.2f} {self.currency}/Unit)[/dim]"
        proj_str = f"[white]{monthly_proj_lkr:.2f} {self.currency}[/white]\n[dim]({monthly_proj_kwh:.1f} Units/mo)[/dim]"

        metrics_table.add_row(cur_power_str, avg_peak_str, energy_str, cost_str, proj_str)

        # Components Table
        comp_table = Table(box=box.SIMPLE_HEAVY, expand=True, show_header=True, header_style="bold blue")
        comp_table.add_column("Component / Subsystem", justify="left", ratio=3)
        comp_table.add_column("Power Draw", justify="right", ratio=1)
        comp_table.add_column("Data Quality", justify="center", ratio=1)
        comp_table.add_column("Key Telemetry", justify="left", ratio=3)

        for key, comp in s.components.items():
            if comp.is_whole_system:
                continue

            # Highlight highest consumer
            is_highest = (comp.name == s.highest_consumer_name)
            name_str = f"[bold red]★ {comp.name}[/bold red]" if is_highest else comp.name
            
            w_str = f"[bold]{comp.watts:.1f} W[/bold]" if is_highest else f"{comp.watts:.1f} W"
            
            q_style = "green" if comp.quality == DataQuality.MEASURED else "yellow"
            q_str = f"[{q_style}]{comp.quality.value}[/{q_style}]"

            # Telemetry snippet
            telem_parts = []
            if "utilization_pct" in comp.details:
                telem_parts.append(f"Load: {comp.details['utilization_pct']}%")
            if "temperature_c" in comp.details and comp.details["temperature_c"] is not None:
                telem_parts.append(f"Temp: {comp.details['temperature_c']}°C")
            if "frequency_mhz" in comp.details and comp.details["frequency_mhz"] > 0:
                telem_parts.append(f"Clock: {int(comp.details['frequency_mhz'])}MHz")
            if "clock_graphics_mhz" in comp.details and comp.details["clock_graphics_mhz"] > 0:
                telem_parts.append(f"GPU Clock: {int(comp.details['clock_graphics_mhz'])}MHz")
            if "vram_used_mb" in comp.details:
                telem_parts.append(f"VRAM: {int(comp.details['vram_used_mb'])}MB")

            telem_str = " | ".join(telem_parts) or f"[dim]{comp.source}[/dim]"
            comp_table.add_row(name_str, w_str, q_str, telem_str)

        # Bottom Information Box: Highest Consumer and Explanation
        high_str = f"[bold red]Highest Power Consumer:[/bold red] {s.highest_consumer_name} ({s.highest_consumer_watts:.1f}W)"
        expl_str = f"[dim]{s.explanation}[/dim]"
        footer_group = Group(
            Text.from_markup(high_str),
            Text.from_markup(expl_str),
        )

        return Panel(
            Group(
                header_table,
                metrics_table,
                comp_table,
                footer_group,
            ),
            title="[bold green]Live Power & Cost Monitor[/bold green]",
            subtitle="[dim]Press Ctrl+C to stop session and view summary report[/dim]",
            border_style="cyan",
        )

    def _render_ansi_fallback(
        self,
        s: SystemPowerSnapshot,
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
        """ANSI clear-screen fallback for standard terminals."""
        duration_str = str(datetime.timedelta(seconds=int(s.elapsed_s)))
        # ANSI clear screen and move cursor home
        sys.stdout.write("\033[H\033[J")
        lines = [
            "=" * 78,
            f" LINUX PC POWER MONITOR & ELECTRICITY COST ANALYZER",
            f" Time: {s.iso_time} | Elapsed: {duration_str} | Quality: {s.total_quality.value}",
            "=" * 78,
            f" Current Power : {s.total_system_watts:6.1f} W   | Average: {avg_watts:6.1f} W  | Peak: {peak_watts:6.1f} W",
            f" Energy (kWh)  : {total_kwh:9.4f} kWh | Energy : {total_wh:7.2f} Wh",
            f" Cost ({self.currency})    : {cost_lkr:9.2f} LKR | Tariff : {self.tariff_rate_lkr:5.2f} LKR/kWh",
            f" Run-Rate      : {hourly_rate_lkr:6.2f} LKR/hr| Monthly: {monthly_proj_lkr:7.2f} LKR ({monthly_proj_kwh:.1f} kWh)",
            "-" * 78,
            f" HIGHEST MONITORED CONSUMER: {s.highest_consumer_name} ({s.highest_consumer_watts:.1f} W - {s.highest_consumer_quality.value})",
            "-" * 78,
            f" {'COMPONENT':<35} {'POWER (W)':<12} {'QUALITY':<12} {'TELEMETRY'}",
            "-" * 78,
        ]

        for key, comp in s.components.items():
            if comp.is_whole_system:
                continue
            telem = []
            if "utilization_pct" in comp.details:
                telem.append(f"Load:{comp.details['utilization_pct']}%")
            if "temperature_c" in comp.details and comp.details["temperature_c"]:
                telem.append(f"{comp.details['temperature_c']}C")
            if "frequency_mhz" in comp.details and comp.details["frequency_mhz"]:
                telem.append(f"{int(comp.details['frequency_mhz'])}MHz")
            t_str = " ".join(telem) or comp.source
            lines.append(f" {comp.name[:34]:<35} {comp.watts:8.1f} W   {comp.quality.value:<12} {t_str}")

        lines.append("=" * 78)
        lines.append(f" Note: {s.explanation}")
        lines.append(f" [Press Ctrl+C to stop session and generate report]")
        sys.stdout.write("\n".join(lines) + "\n")
        sys.stdout.flush()
