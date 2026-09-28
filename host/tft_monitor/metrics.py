"""Read Linux counters without root, with optional GPU support."""

from __future__ import annotations

import math
import re
import shutil
import socket
import subprocess
import time
from pathlib import Path

import psutil


def finite_number(value):
    try:
        result = float(value)
        return result if math.isfinite(result) else None
    except (TypeError, ValueError):
        return None


def percent(value):
    number = finite_number(value)
    return round(max(0.0, min(100.0, number or 0.0)), 1)


def cpu_temperature(sensors):
    """Prefer CPU die/package sensors; do not mislabel disk/GPU/ACPI readings."""
    candidates = []
    for group, entries in sensors.items():
        name = group.lower()
        known_cpu = any(part in name for part in (
            "coretemp", "k10temp", "zenpower", "cpu_thermal", "cpu-thermal",
        ))
        for entry in entries:
            label = entry.label.lower()
            if not known_cpu and "cpu" not in label:
                continue
            value = finite_number(entry.current)
            if value is None or not -30 <= value <= 150:
                continue
            priority = 0 if "tdie" in label else 1 if (
                "package" in label or "physical id" in label
            ) else 2 if "tctl" in label else 3
            candidates.append((priority, value))
    if not candidates:
        return None
    best_priority = min(priority for priority, _ in candidates)
    return round(max(value for priority, value in candidates if priority == best_priority), 1)


def selected_interfaces(counters, stats, interface="auto", net_root=Path("/sys/class/net")):
    if interface != "auto":
        return [interface] if interface in counters else []
    excluded = ("lo", "veth", "docker", "br-", "virbr", "tun", "tap", "wg", "tailscale", "zt", "dummy", "ifb", "vnet")
    result = []
    for name in counters:
        if name.startswith(excluded) or name not in stats or not stats[name].isup:
            continue
        # sysfs also catches bridges/VPNs with custom names, avoiding double counting.
        if "/devices/virtual/net/" in str((net_root / name).resolve()):
            continue
        result.append(name)
    return sorted(result)


class GPUReader:
    """A five-second cache limits the overhead of invoking nvidia-smi."""

    def __init__(self, drm_root=Path("/sys/class/drm"), clock=time.monotonic):
        self.drm_root = drm_root
        self.clock = clock
        self.nvidia_smi = shutil.which("nvidia-smi")
        self.next_read = 0.0
        self.cached = (None, None)

    def read(self):
        now = self.clock()
        if now < self.next_read:
            return self.cached
        self.next_read = now + 5.0
        self.cached = self._read_nvidia() if self.nvidia_smi else (None, None)
        if self.cached == (None, None):
            self.cached = self._read_amd()
        return self.cached

    def _read_nvidia(self):
        try:
            result = subprocess.run(
                [self.nvidia_smi, "--query-gpu=utilization.gpu,temperature.gpu", "--format=csv,noheader,nounits"],
                capture_output=True, text=True, timeout=1.0, check=True,
            )
            first = result.stdout.splitlines()[0].split(",")
            busy, temperature = (finite_number(value.strip()) for value in first[:2])
            return (percent(busy) if busy is not None else None, temperature)
        except (OSError, subprocess.SubprocessError, ValueError, IndexError):
            return None, None

    def _read_amd(self):
        try:
            cards = sorted(path for path in self.drm_root.glob("card*") if re.fullmatch(r"card\d+", path.name))
            for card in cards:
                busy_path = card / "device/gpu_busy_percent"
                if not busy_path.exists():
                    continue
                busy = finite_number(busy_path.read_text().strip())
                temperature = None
                for sensor in sorted((card / "device/hwmon").glob("hwmon*/temp1_input")):
                    value = finite_number(sensor.read_text().strip())
                    if value is not None:
                        temperature = round(value / 1000.0, 1)
                        break
                return percent(busy) if busy is not None else None, temperature
        except (OSError, ValueError):
            pass
        return None, None


class MetricsCollector:
    def __init__(self, disk="/", interface="auto", *, psutil_module=psutil,
                 monotonic=time.monotonic, wall_clock=time.time, gpu=None,
                 net_root=Path("/sys/class/net")):
        self.psutil = psutil_module
        self.disk = disk
        self.interface = interface
        self.monotonic = monotonic
        self.wall_clock = wall_clock
        self.gpu = gpu if gpu is not None else GPUReader(clock=monotonic)
        self.net_root = net_root
        self.hostname = socket.gethostname().split(".")[0][:24]
        # Prime both rate measurements before the first interval.
        self.psutil.cpu_percent(interval=None)
        self.previous_net = self.psutil.net_io_counters(pernic=True) or {}
        self.previous_time = self.monotonic()

    def sample(self):
        now = self.monotonic()
        current_net = self.psutil.net_io_counters(pernic=True) or {}
        names = selected_interfaces(current_net, self.psutil.net_if_stats(), self.interface, self.net_root)
        elapsed = now - self.previous_time
        rx = tx = 0.0
        if elapsed > 0:
            for name in names:
                old = self.previous_net.get(name)
                if old is None:
                    continue  # A newly attached interface has no baseline yet.
                rx += max(0, current_net[name].bytes_recv - old.bytes_recv) / elapsed
                tx += max(0, current_net[name].bytes_sent - old.bytes_sent) / elapsed
        self.previous_net = current_net
        self.previous_time = now
        try:
            temperature = cpu_temperature(self.psutil.sensors_temperatures())
        except (AttributeError, OSError, RuntimeError):
            temperature = None
        gpu, gpu_temp = self.gpu.read()
        wall_now = self.wall_clock()
        return {
            "v": 1,
            "type": "stats",
            "host": self.hostname,
            "cpu": percent(self.psutil.cpu_percent(interval=None)),
            "ram": percent(self.psutil.virtual_memory().percent),
            "disk": percent(self.psutil.disk_usage(self.disk).percent),
            "temp": temperature,
            "gpu": gpu,
            "gpu_temp": gpu_temp,
            "rx": round(rx, 1),
            "tx": round(tx, 1),
            "uptime": max(0, int(wall_now - self.psutil.boot_time())),
            "time": time.strftime("%H:%M", time.localtime(wall_now)),
        }
