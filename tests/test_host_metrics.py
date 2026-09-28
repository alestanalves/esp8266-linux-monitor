import subprocess
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace as Obj
from unittest.mock import Mock, patch

from tft_monitor.metrics import GPUReader, MetricsCollector, cpu_temperature, selected_interfaces


def counter(rx, tx):
    return Obj(bytes_recv=rx, bytes_sent=tx)


class FakePsutil:
    def __init__(self):
        self.counters = {"eth0": counter(1000, 2000), "lo": counter(5000, 5000)}
        self.cpu_calls = 0

    def cpu_percent(self, interval=None):
        self.cpu_calls += 1
        return 99 if self.cpu_calls == 1 else 25

    def net_io_counters(self, pernic):
        return dict(self.counters)

    def net_if_stats(self):
        return {name: Obj(isup=True) for name in self.counters}

    def sensors_temperatures(self):
        return {"coretemp": [Obj(label="Package id 0", current=61)]}

    def virtual_memory(self):
        return Obj(percent=42)

    def disk_usage(self, path):
        return Obj(percent=73)

    def boot_time(self):
        return 100


class MetricsTests(unittest.TestCase):
    def collector(self):
        ps = FakePsutil()
        clock = Mock(return_value=10)
        gpu = Mock()
        gpu.read.return_value = (None, None)
        collector = MetricsCollector(psutil_module=ps, monotonic=clock,
                                     wall_clock=lambda: 1100, gpu=gpu,
                                     net_root=Path("/nonexistent/test-net"))
        return collector, ps, clock

    def test_rates_use_elapsed_interval_and_prime_cpu(self):
        collector, ps, clock = self.collector()
        ps.counters = {"eth0": counter(1400, 2100), "lo": counter(900000, 900000)}
        clock.return_value = 12
        packet = collector.sample()
        self.assertEqual((packet["rx"], packet["tx"]), (200, 50))
        self.assertEqual(packet["cpu"], 25)
        self.assertEqual(packet["uptime"], 1000)
        self.assertEqual(packet["temp"], 61)
        self.assertIsNone(packet["gpu"])
        self.assertEqual(packet["v"], 1)

    def test_reset_and_new_interface_do_not_create_spikes(self):
        collector, ps, clock = self.collector()
        ps.counters = {"eth0": counter(1, 1), "wlan0": counter(9999999, 9999999)}
        clock.return_value = 12
        packet = collector.sample()
        self.assertEqual((packet["rx"], packet["tx"]), (0, 0))
        ps.counters["wlan0"] = counter(10000099, 10000199)
        clock.return_value = 14
        packet = collector.sample()
        self.assertEqual((packet["rx"], packet["tx"]), (50, 100))

    def test_missing_temperature_is_null(self):
        collector, ps, clock = self.collector()
        ps.sensors_temperatures = Mock(side_effect=OSError("not supported"))
        self.assertIsNone(collector.sample()["temp"])

    def test_temperature_prefers_die_then_package_over_acpi_gpu_disk(self):
        self.assertEqual(cpu_temperature({
            "amdgpu": [Obj(label="edge", current=90)],
            "nvme": [Obj(label="Composite", current=80)],
            "acpitz": [Obj(label="", current=99)],
            "k10temp": [Obj(label="Tctl", current=83), Obj(label="Tdie", current=63)],
        }), 63)
        self.assertEqual(cpu_temperature({
            "coretemp": [Obj(label="Package id 0", current=68), Obj(label="Core 0", current=60)],
        }), 68)
        self.assertIsNone(cpu_temperature({"acpitz": [Obj(label="", current=55)]}))

    def test_invalid_temperature_is_ignored(self):
        self.assertIsNone(cpu_temperature({"coretemp": [Obj(label="Package", current=float("nan"))]}))

    def test_auto_excludes_virtual_and_down_interfaces(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            virtual = root / "devices/virtual/net/customvpn"
            virtual.mkdir(parents=True)
            (root / "customvpn").symlink_to(virtual)
            names = ["eth0", "wlan0", "lo", "docker0", "veth123", "wg0", "customvpn"]
            counters = {name: counter(0, 0) for name in names}
            stats = {name: Obj(isup=name != "wlan0") for name in names}
            self.assertEqual(selected_interfaces(counters, stats, net_root=root), ["eth0"])
            self.assertEqual(selected_interfaces(counters, stats, "wg0", root), ["wg0"])
            self.assertEqual(selected_interfaces(counters, stats, "missing", root), [])


class GPUReaderTests(unittest.TestCase):
    @patch("tft_monitor.metrics.shutil.which", return_value="/usr/bin/nvidia-smi")
    @patch("tft_monitor.metrics.subprocess.run")
    def test_nvidia_is_bounded_and_cached(self, run, which):
        run.return_value = Obj(stdout="42, 57\n99, 80\n")
        clock = Mock(return_value=10)
        reader = GPUReader(clock=clock)
        self.assertEqual(reader.read(), (42, 57))
        clock.return_value = 11
        self.assertEqual(reader.read(), (42, 57))
        self.assertEqual(run.call_count, 1)
        self.assertEqual(run.call_args.kwargs["timeout"], 1)

    @patch("tft_monitor.metrics.shutil.which", return_value="/usr/bin/nvidia-smi")
    @patch("tft_monitor.metrics.subprocess.run", side_effect=subprocess.TimeoutExpired("nvidia-smi", 1))
    def test_timeout_falls_back_to_amd(self, run, which):
        with tempfile.TemporaryDirectory() as tmp:
            drm = Path(tmp)
            hwmon = drm / "card0/device/hwmon/hwmon3"
            hwmon.mkdir(parents=True)
            (drm / "card0/device/gpu_busy_percent").write_text("35\n")
            (hwmon / "temp1_input").write_text("56500\n")
            self.assertEqual(GPUReader(drm_root=drm).read(), (35, 56.5))


if __name__ == "__main__":
    unittest.main()
