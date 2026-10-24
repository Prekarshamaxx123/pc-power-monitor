"""
Data Persistence and Historical Logging Engine.
Manages continuous synchronous logging to CSV for spreadsheet analysis
and persistent SQLite for historical session querying, auditability, and reporting.
"""

from __future__ import annotations
import csv
import datetime
import os
import sqlite3
from typing import Dict, Any, List, Optional

from monitors.models import SystemPowerSnapshot, SessionSummary, DataQuality


class DataLogger:
    """Manages simultaneous CSV streaming and SQLite database persistence."""

    def __init__(self, output_dir: str = "./power_logs", session_id: Optional[str] = None):
        self.output_dir = os.path.abspath(output_dir)
        os.makedirs(self.output_dir, exist_ok=True)

        now_str = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        self.session_id = session_id or f"session_{now_str}"

        self.csv_path = os.path.join(self.output_dir, f"power_{self.session_id}.csv")
        self.db_path = os.path.join(self.output_dir, "power_monitor.db")

        self._csv_file = None
        self._csv_writer = None
        self._db_conn = None

        self._init_sqlite()
        self._init_csv()

    def _init_sqlite(self) -> None:
        """Create database tables and indexes if they do not exist."""
        self._db_conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._db_conn.execute("PRAGMA journal_mode=WAL;")
        with self._db_conn:
            self._db_conn.execute(
                """
                CREATE TABLE IF NOT EXISTS sessions (
                    session_id TEXT PRIMARY KEY,
                    start_time TEXT NOT NULL,
                    end_time TEXT,
                    duration_seconds REAL DEFAULT 0,
                    total_energy_wh REAL DEFAULT 0,
                    total_energy_kwh REAL DEFAULT 0,
                    total_cost_lkr REAL DEFAULT 0,
                    avg_power_watts REAL DEFAULT 0,
                    peak_power_watts REAL DEFAULT 0,
                    min_power_watts REAL DEFAULT 0,
                    tariff_rate_lkr REAL NOT NULL,
                    highest_consumer TEXT,
                    data_quality TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
                """
            )
            self._db_conn.execute(
                """
                CREATE TABLE IF NOT EXISTS measurements (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL,
                    timestamp_iso TEXT NOT NULL,
                    elapsed_seconds REAL NOT NULL,
                    total_system_watts REAL NOT NULL,
                    measured_watts REAL NOT NULL,
                    estimated_watts REAL NOT NULL,
                    data_quality TEXT NOT NULL,
                    highest_consumer TEXT,
                    cpu_watts REAL,
                    gpu_watts REAL,
                    ram_watts REAL,
                    storage_watts REAL,
                    fans_watts REAL,
                    motherboard_watts REAL,
                    cumulative_wh REAL NOT NULL,
                    cumulative_kwh REAL NOT NULL,
                    cost_lkr REAL NOT NULL,
                    FOREIGN KEY (session_id) REFERENCES sessions(session_id) ON DELETE CASCADE
                );
                """
            )
            self._db_conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_meas_session ON measurements(session_id);"
            )
            self._db_conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_meas_time ON measurements(timestamp_iso);"
            )

    def start_session_record(self, tariff_rate_lkr: float) -> None:
        """Insert initial session record into SQLite."""
        start_time_iso = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with self._db_conn:
            self._db_conn.execute(
                """
                INSERT OR REPLACE INTO sessions (
                    session_id, start_time, tariff_rate_lkr, data_quality
                ) VALUES (?, ?, ?, ?);
                """,
                (self.session_id, start_time_iso, tariff_rate_lkr, "INITIALIZING"),
            )

    def _init_csv(self) -> None:
        """Create CSV file and write standardized column header."""
        file_exists = os.path.isfile(self.csv_path) and os.path.getsize(self.csv_path) > 0
        self._csv_file = open(self.csv_path, mode="a", newline="", encoding="utf-8")
        self._csv_writer = csv.writer(self._csv_file)

        if not file_exists:
            header = [
                "timestamp_iso",
                "elapsed_seconds",
                "total_system_watts",
                "measured_component_watts",
                "estimated_component_watts",
                "data_quality",
                "highest_consumer",
                "cpu_watts",
                "gpu_watts",
                "ram_watts",
                "storage_watts",
                "fans_watts",
                "motherboard_watts",
                "cumulative_wh",
                "cumulative_kwh",
                "cost_lkr",
            ]
            self._csv_writer.writerow(header)
            self._csv_file.flush()

    def log(
        self,
        snapshot: SystemPowerSnapshot,
        total_wh: float,
        total_kwh: float,
        cost_lkr: float,
    ) -> None:
        """Write single measurement tick to both CSV and SQLite."""
        cpu_w = snapshot.components.get("cpu").watts if "cpu" in snapshot.components else 0.0
        gpu_w = snapshot.components.get("gpu").watts if "gpu" in snapshot.components else 0.0
        ram_w = snapshot.components.get("ram").watts if "ram" in snapshot.components else 0.0
        stor_w = snapshot.components.get("storage").watts if "storage" in snapshot.components else 0.0
        fan_w = snapshot.components.get("fans").watts if "fans" in snapshot.components else 0.0
        mb_w = snapshot.components.get("motherboard").watts if "motherboard" in snapshot.components else 0.0

        # 1. Write CSV row and flush
        if self._csv_writer and self._csv_file:
            row = [
                snapshot.iso_time,
                round(snapshot.elapsed_s, 2),
                round(snapshot.total_system_watts, 2),
                round(snapshot.measured_component_watts, 2),
                round(snapshot.estimated_component_watts, 2),
                snapshot.total_quality.value,
                f"{snapshot.highest_consumer_name} ({round(snapshot.highest_consumer_watts, 1)}W)",
                round(cpu_w, 2),
                round(gpu_w, 2),
                round(ram_w, 2),
                round(stor_w, 2),
                round(fan_w, 2),
                round(mb_w, 2),
                round(total_wh, 4),
                round(total_kwh, 6),
                round(cost_lkr, 4),
            ]
            self._csv_writer.writerow(row)
            self._csv_file.flush()

        # 2. Write SQLite record
        if self._db_conn:
            with self._db_conn:
                self._db_conn.execute(
                    """
                    INSERT INTO measurements (
                        session_id, timestamp_iso, elapsed_seconds,
                        total_system_watts, measured_watts, estimated_watts,
                        data_quality, highest_consumer, cpu_watts, gpu_watts,
                        ram_watts, storage_watts, fans_watts, motherboard_watts,
                        cumulative_wh, cumulative_kwh, cost_lkr
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                    """,
                    (
                        self.session_id,
                        snapshot.iso_time,
                        round(snapshot.elapsed_s, 2),
                        round(snapshot.total_system_watts, 2),
                        round(snapshot.measured_component_watts, 2),
                        round(snapshot.estimated_component_watts, 2),
                        snapshot.total_quality.value,
                        snapshot.highest_consumer_name,
                        round(cpu_w, 2),
                        round(gpu_w, 2),
                        round(ram_w, 2),
                        round(stor_w, 2),
                        round(fan_w, 2),
                        round(mb_w, 2),
                        round(total_wh, 4),
                        round(total_kwh, 6),
                        round(cost_lkr, 4),
                    ),
                )

    def finalize_session(self, summary: SessionSummary) -> None:
        """Update session record with terminal aggregates and close handles."""
        if self._db_conn:
            try:
                with self._db_conn:
                    self._db_conn.execute(
                        """
                        UPDATE sessions SET
                            end_time = ?,
                            duration_seconds = ?,
                            total_energy_wh = ?,
                            total_energy_kwh = ?,
                            total_cost_lkr = ?,
                            avg_power_watts = ?,
                            peak_power_watts = ?,
                            min_power_watts = ?,
                            highest_consumer = ?,
                            data_quality = ?
                        WHERE session_id = ?;
                        """,
                        (
                            summary.end_time_iso,
                            round(summary.duration_s, 2),
                            round(summary.total_energy_wh, 4),
                            round(summary.total_energy_kwh, 6),
                            round(summary.total_cost_lkr, 4),
                            round(summary.avg_power_watts, 2),
                            round(summary.peak_power_watts, 2),
                            round(summary.min_power_watts, 2),
                            f"{summary.highest_consumer_name} ({round(summary.highest_consumer_peak_watts, 1)}W)",
                            summary.dominant_data_quality.value,
                            self.session_id,
                        ),
                    )
            except Exception:
                pass
            finally:
                self._db_conn.close()
                self._db_conn = None

        if self._csv_file:
            try:
                self._csv_file.flush()
                self._csv_file.close()
            except Exception:
                pass
            finally:
                self._csv_file = None

    @classmethod
    def get_historical_sessions(cls, db_path: str) -> List[Dict[str, Any]]:
        """Retrieve past monitoring sessions from SQLite database."""
        if not os.path.isfile(db_path):
            return []

        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        try:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT session_id, start_time, end_time, duration_seconds,
                       total_energy_wh, total_energy_kwh, total_cost_lkr,
                       avg_power_watts, peak_power_watts, tariff_rate_lkr,
                       highest_consumer, data_quality
                FROM sessions
                ORDER BY created_at DESC;
                """
            )
            rows = cursor.fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()
