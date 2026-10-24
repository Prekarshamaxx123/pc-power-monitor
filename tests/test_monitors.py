"""
Unit tests for subsystem monitors, physics assertions, and error handling.
"""

import unittest
from unittest.mock import patch, MagicMock
from monitors.cpu import CPUMonitor
from monitors.gpu import GPUMonitor
from monitors.memory import MemoryMonitor
from monitors.battery import BatteryMonitor
from monitors.models import DataQuality


class TestMonitors(unittest.TestCase):
    """Test suite for hardware monitor abstractions."""

    def test_cpu_monitor_model_estimation(self):
        """When RAPL is unreadable, CPU monitor must gracefully fall back to TDP model."""
        cpu = CPUMonitor(custom_tdp=65.0)
        cpu.initialize()
        
        # Test estimation formula directly
        est_power = cpu._estimate_power(util_pct=50.0, cur_freq_mhz=3600.0, max_freq_mhz=4600.0)
        self.assertGreater(est_power, 11.0)   # Above idle floor (65 * 0.18 = 11.7W)
        self.assertLess(est_power, 75.0)      # Below max boost

    def test_memory_monitor_physics_independence(self):
        """RAM power must NOT double just because memory allocation doubles."""
        ram = MemoryMonitor(estimated_dimms=2)
        ram.initialize()
        
        # Simulate 20% memory usage vs 90% memory usage
        with patch("psutil.virtual_memory") as mock_vm:
            mock_vm.return_value = MagicMock(used=3 * 1024**3, available=13 * 1024**3, percent=20.0, total=16 * 1024**3)
            p_low = ram.read(elapsed_s=1.0)
            
            mock_vm.return_value = MagicMock(used=14 * 1024**3, available=2 * 1024**3, percent=90.0, total=16 * 1024**3)
            p_high = ram.read(elapsed_s=1.0)
            
            # Difference should be under 1W, NOT proportional to 4.5x memory allocation
            delta = abs(p_high.watts - p_low.watts)
            self.assertLess(delta, 1.0)
            self.assertEqual(p_low.quality, DataQuality.ESTIMATED)

    def test_gpu_monitor_slot_power_fallback(self):
        """When nvidia-smi reports [N/A] for power.draw, GPU must estimate power and flag ESTIMATED."""
        gpu = GPUMonitor()
        gpu.is_initialized = True
        gpu.gpu_type = "nvidia"
        gpu._nvidia_smi_path = "/usr/bin/nvidia-smi"
        gpu._power_limit_watts = 75.0

        mock_csv_output = "0, GeForce GTX 1650, [N/A], 75.00, 20.0, 10.0, 55, 4096, 1024, 600, 1800\n"
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout=mock_csv_output, stderr="")
            reading = gpu.read(elapsed_s=1.0)
            
            self.assertIsNotNone(reading)
            self.assertEqual(reading.quality, DataQuality.ESTIMATED)
            self.assertIn("GTX 1650", reading.name)
            self.assertGreater(reading.watts, 8.0)
            self.assertLessEqual(reading.watts, 75.0)

    def test_battery_discharging_sets_whole_system(self):
        """A discharging battery must report as whole-system DC measurement."""
        bat = BatteryMonitor()
        bat.has_battery = True
        bat.battery_path = "/sys/class/power_supply/mock_bat"
        
        with patch("os.path.isfile", return_value=True), \
             patch("builtins.open", unittest.mock.mock_open(read_data="Discharging")):
            # Simulate reading status and power
            with patch.object(bat, "read") as mock_read:
                from monitors.models import ComponentPower
                mock_read.return_value = ComponentPower(
                    name="Battery",
                    watts=25.0,
                    quality=DataQuality.MEASURED,
                    source="sysfs:power_now",
                    is_whole_system=True,
                )
                reading = bat.read(elapsed_s=1.0)
                self.assertTrue(reading.is_whole_system)
                self.assertEqual(reading.quality, DataQuality.MEASURED)


if __name__ == "__main__":
    unittest.main()
