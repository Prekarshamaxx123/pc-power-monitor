"""
Session Summary Report and Historical Audit View.
Formats comprehensive termination reports with component energy distributions,
tariff calculations, sensor warnings, and historical session tables.
"""

from __future__ import annotations
import datetime
import os
import sys
from typing import Dict, Any, List, Optional

try:
    from rich.console import Console
    from rich.panel import Panel
    from rich.table import Table
    from rich.text import Text
    from rich import box
    RICH_AVAILABLE = True
except ImportError:
    RICH_AVAILABLE = False

from monitors.models import SessionSummary


class ReportUI:
    """Renders comprehensive terminal session reports and historical logs."""

    @classmethod
    def print_session_summary(cls, summary: SessionSummary, currency: str = "LKR") -> None:
        """Render final session summary report."""
        duration_str = str(datetime.timedelta(seconds=int(summary.duration_s)))
        console = Console() if RICH_AVAILABLE else None

        if console:
            # 1. Main Metrics Table
            m_table = Table(box=box.ROUNDED, expand=True, show_header=True, header_style="bold cyan")
            m_table.add_column("Metric", style="bold")
            m_table.add_column("Value", style="green")
            m_table.add_column("Notes", style="dim")

            m_table.add_row("Session ID", summary.session_id, "Unique identifier")
            m_table.add_row("Start Time", summary.start_time_iso, "Local timestamp")
            m_table.add_row("End Time", summary.end_time_iso, "Local timestamp")
            m_table.add_row("Total Duration", duration_str, f"{summary.duration_s:.1f} seconds")
            m_table.add_row("Average System Power", f"{summary.avg_power_watts:.2f} W", "Time-weighted mathematical mean")
            m_table.add_row("Peak System Power", f"{summary.peak_power_watts:.2f} W", "Maximum observed instantaneous power")
            m_table.add_row("Minimum System Power", f"{summary.min_power_watts:.2f} W", "Lowest observed instantaneous power")
            m_table.add_row("Total Units Consumed", f"{summary.total_energy_kwh:.6f} Units", f"{summary.total_energy_kwh:.6f} kWh ({summary.total_energy_wh:.2f} Wh)")
            m_table.add_row("Estimated Electricity Cost", f"{summary.total_cost_lkr:.2f} {currency}", "Based on configured tariff rate")
            m_table.add_row("Highest Power Consumer", summary.highest_consumer_name, f"Peak observed: {summary.highest_consumer_peak_watts:.1f} W")
            m_table.add_row("Primary Data Quality", summary.dominant_data_quality.value, "Sensor vs Model fidelity")

            # 2. Component Power Breakdown
            c_table = Table(box=box.SIMPLE_HEAVY, expand=True, show_header=True, header_style="bold blue")
            c_table.add_column("Component / Subsystem", justify="left")
            c_table.add_column("Average Power (W)", justify="right")
            c_table.add_column("Percentage of System", justify="right")

            tot_comp_w = sum(summary.component_averages.values()) or 1.0
            for comp_name, comp_avg in sorted(summary.component_averages.items(), key=lambda x: x[1], reverse=True):
                pct = (comp_avg / tot_comp_w) * 100.0
                c_table.add_row(comp_name, f"{comp_avg:.1f} W", f"{pct:.1f}%")

            # 3. File Destinations
            f_table = Table.grid(expand=True)
            f_table.add_column(style="bold")
            f_table.add_column(style="white")
            if summary.csv_file_path:
                f_table.add_row("CSV Spreadsheet: ", summary.csv_file_path)
            if summary.db_file_path:
                f_table.add_row("SQLite Database: ", summary.db_file_path)

            # 4. Warnings and Recommendations
            warn_content = ""
            if summary.warnings:
                warn_lines = [f"[yellow]• {w}[/yellow]" for w in summary.warnings]
                warn_content = "\n" + "\n".join(warn_lines)
            else:
                warn_content = "\n[green]• All supported sensors operated cleanly without errors.[/green]"

            console.print()
            console.print(Panel(m_table, title="[bold green]═══ Session Power & Cost Summary ═══[/bold green]", border_style="green"))
            console.print(Panel(c_table, title="[bold blue]Subsystem Power Breakdown (Average Draw)[/bold blue]", border_style="blue"))
            console.print(Panel(f_table, title="[bold cyan]Saved Output Files[/bold cyan]", border_style="cyan"))
            console.print(Panel(Text.from_markup(warn_content), title="[bold yellow]Hardware Diagnostics & Warnings[/bold yellow]", border_style="yellow"))
            console.print()

        else:
            # Clean plain text summary
            print("\n" + "=" * 78)
            print(" SESSION POWER & COST SUMMARY REPORT")
            print("=" * 78)
            print(f" Session ID        : {summary.session_id}")
            print(f" Start Time        : {summary.start_time_iso}")
            print(f" End Time          : {summary.end_time_iso}")
            print(f" Duration          : {duration_str} ({summary.duration_s:.1f}s)")
            print(f" Average Power     : {summary.avg_power_watts:.2f} W")
            print(f" Peak Power        : {summary.peak_power_watts:.2f} W")
            print(f" Minimum Power     : {summary.min_power_watts:.2f} W")
            print(f" Total Energy      : {summary.total_energy_kwh:.6f} kWh ({summary.total_energy_wh:.2f} Wh)")
            print(f" Estimated Cost    : {summary.total_cost_lkr:.2f} {currency}")
            print(f" Highest Consumer  : {summary.highest_consumer_name} ({summary.highest_consumer_peak_watts:.1f} W)")
            print(f" Data Quality      : {summary.dominant_data_quality.value}")
            print("-" * 78)
            print(" SUBSYSTEM POWER AVERAGES:")
            for comp_name, comp_avg in sorted(summary.component_averages.items(), key=lambda x: x[1], reverse=True):
                print(f"   - {comp_name:<40}: {comp_avg:6.1f} W")
            print("-" * 78)
            print(" SAVED OUTPUT FILES:")
            if summary.csv_file_path:
                print(f"   CSV File       : {summary.csv_file_path}")
            if summary.db_file_path:
                print(f"   SQLite DB      : {summary.db_file_path}")
            if summary.warnings:
                print("-" * 78)
                print(" HARDWARE DIAGNOSTICS & WARNINGS:")
                for w in summary.warnings:
                    print(f"   [!] {w}")
            print("=" * 78 + "\n")

    @classmethod
    def print_historical_sessions(cls, sessions: List[Dict[str, Any]], currency: str = "LKR") -> None:
        """Render historical sessions retrieved from SQLite."""
        console = Console() if RICH_AVAILABLE else None

        if not sessions:
            msg = "No historical sessions found in database."
            if console:
                console.print(f"[yellow]{msg}[/yellow]")
            else:
                print(msg)
            return

        if console:
            table = Table(box=box.ROUNDED, expand=True, title="[bold green]Historical Power Monitoring Sessions[/bold green]")
            table.add_column("Session ID", style="cyan")
            table.add_column("Start Time", style="white")
            table.add_column("Duration", justify="right")
            table.add_column("Avg Power", justify="right", style="green")
            table.add_column("Peak Power", justify="right", style="red")
            table.add_column("Units (kWh)", justify="right", style="cyan")
            table.add_column(f"Cost ({currency})", justify="right", style="yellow")
            table.add_column("Top Consumer", style="white")

            for s in sessions:
                dur = str(datetime.timedelta(seconds=int(s.get("duration_seconds") or 0)))
                table.add_row(
                    s["session_id"],
                    s["start_time"],
                    dur,
                    f"{s.get('avg_power_watts', 0.0):.1f} W",
                    f"{s.get('peak_power_watts', 0.0):.1f} W",
                    f"{s.get('total_energy_kwh', 0.0):.4f}",
                    f"{s.get('total_cost_lkr', 0.0):.2f}",
                    str(s.get("highest_consumer") or "N/A"),
                )
            console.print(table)
        else:
            print("\n" + "=" * 95)
            print(f" {'SESSION ID':<22} {'START TIME':<20} {'DURATION':<10} {'AVG (W)':<9} {'ENERGY(kWh)':<12} {'COST (LKR)':<10}")
            print("=" * 95)
            for s in sessions:
                dur = str(datetime.timedelta(seconds=int(s.get("duration_seconds") or 0)))
                print(
                    f" {s['session_id']:<22} {s['start_time']:<20} {dur:<10} "
                    f"{s.get('avg_power_watts', 0.0):7.1f} W "
                    f"{s.get('total_energy_kwh', 0.0):10.4f} "
                    f"{s.get('total_cost_lkr', 0.0):8.2f}"
                )
            print("=" * 95 + "\n")
