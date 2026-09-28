import json
import threading
import unittest
from types import SimpleNamespace as Obj
from unittest.mock import Mock, patch

import serial

from tft_monitor.cli import parser, run_monitor
from tft_monitor.transport import DeviceUnavailable, MonitorConnection, candidate_ports, control_lines, encode_message, handshake


READY = b'{"v":1,"type":"ready","device":"tft-monitor"}\n'


class FakeSerial:
    def __init__(self, chunks=()):
        self.chunks = iter(chunks)
        self.messages = []
        self.opened = False
        self.closed = False

    def open(self):
        self.opened = True
        self.open_lines = self.dtr, self.rts

    def close(self):
        self.closed = True

    def reset_input_buffer(self):
        pass

    def read_until(self, delimiter, size):
        return next(self.chunks, b"")

    def write(self, data):
        self.messages.append(json.loads(data))
        return len(data)


class TransportTests(unittest.TestCase):
    def test_autodetection_only_supported_usb_ids(self):
        ports = [Obj(device="/dev/ttyUSB0", vid=0x1234, pid=0x5678),
                 Obj(device="/dev/ttyUSB1", vid=0x10C4, pid=0xEA60),
                 Obj(device="/dev/ttyUSB2", vid=0x1A86, pid=0x7523),
                 Obj(device="/dev/ttyUSB3", vid=0x1A86, pid=0x55D4),
                 Obj(device="/dev/ttyUSB4", vid=0x1A86, pid=0x0000),
                 Obj(device="/dev/ttyACM0", vid=None, pid=None),
                 Obj(device="/dev/ttyACM1", vid=0x2E8A, pid=0x0005),
                 Obj(device="/dev/ttyACM2", vid=0x303A, pid=0x1001)]
        self.assertEqual(candidate_ports(ports=ports), ["/dev/ttyACM1", "/dev/ttyACM2", "/dev/ttyUSB1", "/dev/ttyUSB2", "/dev/ttyUSB3"])
        self.assertEqual(candidate_ports("/dev/custom", ports), ["/dev/custom"])

    def test_bridge_control_lines_stay_deasserted_and_native_usb_uses_dtr(self):
        for vid, expected in ((0x10C4, (False, False)), (0x1A86, (False, False)),
                              (0x303A, (True, False)), (0x2E8A, (True, True))):
            with self.subTest(vid=vid):
                ports = [Obj(device="/dev/serial-test", vid=vid)]
                self.assertEqual(control_lines("/dev/serial-test", ports), expected)
        self.assertEqual(control_lines("/dev/unknown", []), (False, False))

    def test_handshake_ignores_noise_and_handles_fragmented_ready(self):
        connection = FakeSerial([b"MicroPython ready\n", b'>>> {"v":1,"type":"hello"}\n', READY[:20], READY[20:]])
        handshake(connection, threading.Event())
        self.assertEqual(connection.messages, [{"v": 1, "type": "hello"}])

    def test_handshake_rejects_other_devices_and_protocol_versions(self):
        connection = FakeSerial([b'{"v":1,"type":"ready","device":"other"}\n',
                                 b'{"v":2,"type":"ready","device":"tft-monitor"}\n'])
        clock = Mock(side_effect=range(100))
        with self.assertRaises(DeviceUnavailable):
            handshake(connection, threading.Event(), clock=clock)
        self.assertTrue(all(item["type"] == "hello" for item in connection.messages))

    def test_oversized_line_is_dropped_then_ready_accepted(self):
        connection = FakeSerial([b"x" * 1024, b"x" * 50, b"garbage\n", READY])
        handshake(connection, threading.Event())

    def test_connection_requires_ready_and_opens_exclusive_with_control_lines(self):
        serial_port = FakeSerial([READY])
        factory = Mock(return_value=serial_port)
        connection = MonitorConnection(serial_factory=factory, discover=lambda _: ["/dev/ttyUSB0"],
                                       line_settings=lambda _: (False, False))
        connection.connect(threading.Event())
        self.assertTrue(factory.call_args.kwargs["exclusive"])
        self.assertEqual(serial_port.open_lines, (False, False))
        self.assertEqual(serial_port.port, "/dev/ttyUSB0")
        self.assertEqual(serial_port.messages[0]["type"], "hello")
        connection.send({"v": 1, "type": "stats", "cpu": 1})
        self.assertEqual(serial_port.messages[1]["type"], "stats")
        connection.close()
        self.assertTrue(serial_port.closed)
        self.assertIsNone(connection.connection)

    @patch("tft_monitor.transport.handshake", side_effect=DeviceUnavailable("wrong firmware"))
    def test_failed_handshake_closes_port_and_never_sends_stats(self, mock_handshake):
        serial_port = FakeSerial()
        connection = MonitorConnection(serial_factory=lambda **_: serial_port,
                                    discover=lambda _: ["/dev/ttyACM0"])
        with self.assertRaises(DeviceUnavailable):
            connection.connect(threading.Event())
        with self.assertRaises(DeviceUnavailable):
            connection.send({"type": "stats"})
        self.assertTrue(serial_port.closed)
        self.assertEqual(serial_port.messages, [])

    def test_partial_write_is_an_error(self):
        connection = MonitorConnection()
        connection.connection = Mock()
        connection.connection.write.return_value = 1
        with self.assertRaises(DeviceUnavailable):
            connection.send({"type": "stats"})

    def test_encoding_is_single_ascii_line_and_rejects_nan(self):
        message = {"host": "máquina\nfoo", "temp": None}
        encoded = encode_message(message)
        self.assertEqual(encoded.count(b"\n"), 1)
        self.assertEqual(json.loads(encoded), message)
        with self.assertRaises(ValueError):
            encode_message({"cpu": float("nan")})

    def test_reconnect_after_disconnect_and_close_on_signal(self):
        stop = Mock()
        stop.is_set.side_effect = [False, False, False, False, True]
        link = Mock()
        link.connection = None

        def connect(_):
            link.connection = object()

        def close():
            link.connection = None

        link.connect.side_effect = connect
        link.close.side_effect = close
        link.send.side_effect = [serial.SerialException("unplugged"), None]
        collector = Mock()
        collector.sample.return_value = {"v": 1, "type": "stats"}
        run_monitor(collector, link, stop)
        self.assertEqual(link.connect.call_count, 2)
        self.assertEqual(link.send.call_count, 2)
        self.assertIsNone(link.connection)
        stop.wait.assert_any_call(2.0)

    def test_invalid_intervals_rejected(self):
        for value in ("0", "-1", "nan", "inf"):
            with self.subTest(value=value), patch("sys.stderr"), self.assertRaises(SystemExit):
                parser().parse_args(["--interval", value])

    def test_start_without_usb_waits_and_sends_when_device_is_connected(self):
        stop = Mock(wraps=threading.Event())
        stop.wait.return_value = False
        link = Mock()
        link.connection = None
        attempts = []

        def connect(_):
            attempts.append(True)
            if len(attempts) == 1:
                raise DeviceUnavailable("ESP8266 USB ausente durante o boot")
            link.connection = object()

        def close():
            link.connection = None

        link.connect.side_effect = connect
        link.close.side_effect = close
        link.send.side_effect = lambda sample: stop.set()
        collector = Mock()
        collector.sample.return_value = {"v": 1, "type": "stats", "cpu": 25}

        run_monitor(collector, link, stop)

        self.assertEqual(link.connect.call_count, 2)
        collector.sample.assert_called_once_with()
        link.send.assert_called_once_with(collector.sample.return_value)
        stop.wait.assert_any_call(2.0)
        self.assertIsNone(link.connection)


if __name__ == "__main__":
    unittest.main()
