"""Validate hostile/partial serial input without MicroPython or real hardware."""

import importlib.util
import json
from pathlib import Path
import unittest


def load_protocol():
    path = Path(__file__).resolve().parents[1] / "firmware" / "protocol.py"
    spec = importlib.util.spec_from_file_location("firmware_protocol", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


protocol = load_protocol()


def stats(**changes):
    payload = dict(v=1, type="stats", host="cachyos", cpu=32.5, ram=48.2,
                   disk=60, temp=54, gpu=None, gpu_temp=None, rx=2048,
                   tx=32, uptime=5432, time="14:30")
    payload.update(changes)
    return payload


class ProtocolTests(unittest.TestCase):
    def test_handshake_and_stats(self):
        self.assertEqual(protocol.parse_line(b'{"v":1,"type":"hello"}')["type"], "hello")
        self.assertEqual(json.loads(protocol.READY)["device"], "tft-monitor")
        self.assertEqual(protocol.parse_line(json.dumps(stats())), stats())

    def test_rejects_invalid_values_without_raising(self):
        invalid = [dict(v=True), dict(v=2), dict(cpu=True), dict(cpu=-1),
                   dict(ram=101), dict(disk="22"), dict(cpu=float("nan")),
                   dict(rx=float("inf")), dict(tx=-1), dict(uptime=None),
                   dict(temp="hot"), dict(gpu=101), dict(gpu_temp=[]),
                   dict(host=""), dict(host=7), dict(time="24:30"),
                   dict(time="23:60"), dict(time="12:ab"), dict(time="9:32")]
        for change in invalid:
            with self.subTest(change=change):
                self.assertIsNone(protocol.parse_line(json.dumps(stats(**change))))
        for payload in (b"\xff", b"garbage", b"[]", b"null", b"{}", b"1",
                        b"[" * 600 + b"]" * 600):
            with self.subTest(payload=payload[:25]):
                self.assertIsNone(protocol.parse_line(payload))

    def test_missing_sensors_and_host_font_sanitization(self):
        payload = stats(host="maquina\n\u00e7")
        for name in ("gpu", "gpu_temp", "temp"):
            del payload[name]
        clean = protocol.parse_line(json.dumps(payload))
        self.assertIsNone(clean["temp"])
        self.assertIsNone(clean["gpu"])
        self.assertEqual(clean["host"], "maquina??")

    def test_chunk_boundaries_crlf_and_multiple_frames(self):
        buffer = protocol.LineBuffer()
        self.assertEqual(buffer.feed(b'{"v":'), [])
        self.assertEqual(buffer.feed(b'1}\r\nnext\npartial'), [b'{"v":1}', b"next"])
        self.assertEqual(buffer.feed(b" done\n"), [b"partial done"])

    def test_overflow_is_bounded_and_recovers_next_line(self):
        buffer = protocol.LineBuffer(8)
        self.assertEqual(buffer.feed(b"01234567890123456789"), [])
        self.assertLessEqual(len(buffer.buffer), 8)
        self.assertEqual(buffer.feed(b"trailing\nvalid\n"), [b"valid"])
        self.assertEqual(buffer.feed(b"12345678\n"), [b"12345678"])

    def test_repl_controls_reset_partial_line(self):
        buffer = protocol.LineBuffer()
        self.assertEqual(buffer.feed(b"broken\x01\x02\x04valid\n"), [b"valid"])


if __name__ == "__main__":
    unittest.main()
