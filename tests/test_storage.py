"""
Unit tests for CSV and SQLite data persistence.
"""

import os
import shutil
import tempfile
import unittest

from core.storage import DataLogger
from monitors.models import SystemPowerSnapshot, ComponentPower, DataQuality, SessionSummary


class TestDataPersistence(unittest.TestCase):
    """Test suite for continuous logging and historical database storage."""

    def setUp(self):
        self.test_dir = tempfile.mkdtemp(prefix="power_test_")

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_csv_and_sqlite_logging_and_finalization(self):
        """Verify that records are appended to CSV and SQLite and can be retrieved."""
        logger = DataLogger(output_dir=self.test_dir, session_id="test_sess_01")
        logger.start_session_record(tariff_rate_lkr=32.50)

        snapshot = SystemPowerSnapshot(
            timestamp=100.0,
            epoch_time=1600000000.0,
            iso_time="2026-10-24 12:00:00",
            elapsed_s=1.0,
            components={
                "cpu": ComponentPower("CPU", 25.0, DataQuality.MEASURED, "rapl"),
                "gpu": ComponentPower("GPU", 35.0, DataQuality.ESTIMATED, "model"),
            },
            measured_component_watts=25.0,
            estimated_component_watts=35.0,
            total_system_watts=70.0,
            total_quality=DataQuality.ESTIMATED,
            highest_consumer_name="GPU",
            highest_consumer_watts=35.0,
            highest_consumer_quality=DataQuality.ESTIMATED,
            baseline_watts=40.0,
            psu_efficiency=0.85,
            explanation="Modeled AC estimate",
        )

        logger.log(snapshot, total_wh=0.0194, total_kwh=0.000019, cost_lkr=0.0006)

        # Finalize
        summary = SessionSummary(
            session_id="test_sess_01",
            start_time_iso="2026-10-24 12:00:00",
            end_time_iso="2026-10-24 12:00:01",
            duration_s=1.0,
            total_energy_wh=0.0194,
            total_energy_kwh=0.000019,
            total_cost_lkr=0.0006,
            avg_power_watts=70.0,
            peak_power_watts=70.0,
            min_power_watts=70.0,
            highest_consumer_name="GPU",
            highest_consumer_peak_watts=35.0,
            dominant_data_quality=DataQuality.ESTIMATED,
            component_averages={"CPU": 25.0, "GPU": 35.0},
            warnings=[],
            csv_file_path=logger.csv_path,
            db_file_path=logger.db_path,
        )
        logger.finalize_session(summary)

        # Verify CSV contents
        self.assertTrue(os.path.isfile(logger.csv_path))
        with open(logger.csv_path, "r", encoding="utf-8") as f:
            lines = f.readlines()
            self.assertEqual(len(lines), 2)  # Header + 1 data line
            self.assertIn("timestamp_iso", lines[0])
            self.assertIn("70.0", lines[1])

        # Verify SQLite contents
        sessions = DataLogger.get_historical_sessions(logger.db_path)
        self.assertEqual(len(sessions), 1)
        self.assertEqual(sessions[0]["session_id"], "test_sess_01")
        self.assertEqual(sessions[0]["avg_power_watts"], 70.0)


if __name__ == "__main__":
    unittest.main()
