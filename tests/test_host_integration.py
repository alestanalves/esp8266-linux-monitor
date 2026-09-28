"""Exercise real pyserial framing against the firmware protocol over a PTY."""

import importlib.util
import os
import queue
import select
import threading
import unittest
from pathlib import Path
from unittest.mock import Mock

import serial

from tft_monitor.metrics import MetricsCollector
from tft_monitor.transport import MonitorConnection


@unittest.skipUnless(os.name == "posix" and Path("/dev/ptmx").exists(), "requires a POSIX PTY")
class SerialIntegrationTests(unittest.TestCase):
    def test_real_serial_handshake_stats_and_exclusive_access(self):
        firmware_path = Path(__file__).resolve().parents[1] / "firmware/protocol.py"
        spec = importlib.util.spec_from_file_location("monitor_firmware_protocol", firmware_path)
        firmware = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(firmware)
        master, slave = os.openpty()
        port = os.ttyname(slave)
        stop = threading.Event()
        received = queue.Queue()
        observed_types = []

        def device():
            lines = firmware.LineBuffer()
            try:
                while not stop.is_set():
                    readable, _, _ = select.select([master], [], [], 0.1)
                    if not readable:
                        continue
                    for line in lines.feed(os.read(master, 1024)):
                        message = firmware.parse_line(line)
                        if message is None:
                            raise AssertionError(f"Firmware rejected host frame: {line!r}")
                        observed_types.append(message["type"])
                        if message["type"] == "hello":
                            os.write(master, firmware.READY.encode())
                        else:
                            received.put(message)
            except Exception as exc:
                received.put(exc)

        worker = threading.Thread(target=device, daemon=True)
        worker.start()
        connection = MonitorConnection(port, line_settings=lambda _: (False, False))
        try:
            connection.connect(stop)
            # A second monitor must fail instead of interleaving its JSON.
            with self.assertRaises(serial.SerialException):
                serial.Serial(port, exclusive=True)
            gpu = Mock()
            gpu.read.return_value = (None, None)
            packet = MetricsCollector(gpu=gpu).sample()
            connection.send(packet)
            reply = received.get(timeout=2.0)
            if isinstance(reply, Exception):
                raise reply
            self.assertEqual(observed_types[0], "hello")
            self.assertEqual(reply["type"], "stats")
            for key in ("cpu", "ram", "disk", "temp", "gpu", "rx", "tx", "uptime", "time"):
                self.assertEqual(reply[key], packet[key], key)
        finally:
            stop.set()
            worker.join(timeout=2.0)
            connection.close()
            os.close(slave)
            os.close(master)
        self.assertFalse(worker.is_alive())


if __name__ == "__main__":
    unittest.main()
