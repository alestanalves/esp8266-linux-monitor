"""Exercise the serial loop through silence, malformed traffic and recovery."""

import importlib.util
import io
import json
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch


ROOT = Path(__file__).resolve().parents[1] / "firmware"


def load(name):
    spec = importlib.util.spec_from_file_location("loop_test_" + name, ROOT / (name + ".py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class StopLoop(BaseException):
    pass


class Clock:
    def __init__(self):
        self.now = 0

    def ticks_ms(self):
        return self.now

    @staticmethod
    def ticks_diff(new, old):
        return new - old

    def sleep_ms(self, duration):
        self.now += duration
        if self.now >= 7500:
            raise StopLoop()


class Stream:
    def __init__(self, clock, schedule):
        self.clock = clock
        self.schedule = list(schedule)
        self.pending = bytearray()
        self.bytes_read = 0

    def ready(self):
        while self.schedule and self.schedule[0][0] <= self.clock.now:
            self.pending.extend(self.schedule.pop(0)[1])
        return bool(self.pending)

    def read(self, size):
        assert size == 1 and self.ready(), "A blocking read would occur"
        self.bytes_read += 1
        return bytes((self.pending.pop(0),))


class Poller:
    def register(self, stream, flags):
        self.stream = stream
        assert flags == 1

    def poll(self, timeout):
        assert timeout == 0
        return [(self.stream, 1)] if self.stream.ready() else []


class LoopTests(unittest.TestCase):
    def load_main(self):
        config, protocol = load("config"), load("protocol")
        with patch.dict("sys.modules", {"config": config, "protocol": protocol}):
            return load("main")

    def test_board_preparation_disables_both_wifi_interfaces(self):
        main = self.load_main()
        stations = [Mock(), Mock()]
        network = SimpleNamespace(STA_IF=0, AP_IF=1,
                                  WLAN=Mock(side_effect=lambda interface: stations[interface]))
        esp = SimpleNamespace(osdebug=Mock())
        with patch.dict("sys.modules", {"network": network, "esp": esp}), \
                patch.object(main.sys, "platform", "esp8266"), \
                patch.object(main.gc, "collect") as collect:
            main.prepare_board()
        self.assertEqual(network.WLAN.call_count, 2)
        for station in stations:
            station.active.assert_called_once_with(False)
        esp.osdebug.assert_called_once_with(None)
        collect.assert_called_once_with()

    def test_esp8266_pin_config_and_hardware_spi_constructor(self):
        main = self.load_main()
        pin = Mock()
        pin.OUT = 1
        spi = Mock()
        display = Mock()
        with patch.dict("sys.modules", {"machine": SimpleNamespace(Pin=pin, SPI=spi),
                                        "st7735": SimpleNamespace(ST7735=display)}), \
                patch.object(main.sys, "platform", "esp8266"):
            main.make_display()
        spi.assert_called_once_with(1, baudrate=10_000_000, polarity=0, phase=0)
        self.assertEqual([call.args[0] for call in pin.call_args_list], [5, 4, 16])
        self.assertEqual((main.config.BOARD, main.config.SCK_PIN, main.config.MOSI_PIN),
                         ("esp8266", 14, 13))

    def test_other_boards_rejected_before_hardware_access(self):
        main = self.load_main()
        with patch.object(main.sys, "platform", "esp32"):
            with self.assertRaisesRegex(RuntimeError, "esp8266"):
                main.make_display()

    def test_stale_and_reconnect_are_not_blocked_by_silent_serial(self):
        config, protocol = load("config"), load("protocol")
        with patch.dict("sys.modules", {"config": config, "protocol": protocol}):
            main = load("main")
        clock = Clock()
        payload = dict(v=1, type="stats", host="test", cpu=2, ram=5, disk=12,
                       rx=0, tx=0, uptime=123, time="12:00")
        encoded = json.dumps(payload).encode() + b"\n"
        stream = Stream(clock, [(0, b'{"v":1,"type":"hello"}\n' + encoded),
                                (200, b"x" * 1300 + b"\n\xff\n{invalid}\n"),
                                (6100, encoded)])
        output = io.StringIO()
        draws = []
        ui = SimpleNamespace(draw=lambda stats=None, stale=False:
                             draws.append((clock.now, stats, stale)))
        with patch.dict("sys.modules", {"dashboard": SimpleNamespace(Dashboard=lambda _: ui)}), \
                patch.object(main, "prepare_board"), \
                patch.object(main, "make_display", return_value=None), \
                patch.object(main, "time", clock), \
                patch.object(main, "select", SimpleNamespace(poll=Poller, POLLIN=1)), \
                patch.object(main.sys, "stdin", stream), \
                patch.object(main.sys, "stdout", output):
            with self.assertRaises(StopLoop):
                main.run()
        self.assertEqual(output.getvalue(), protocol.READY)
        self.assertEqual(draws[0], (0, None, False))
        stale = [entry for entry in draws if entry[2]]
        self.assertEqual(len(stale), 1)
        self.assertGreater(stale[0][0], 5000)
        self.assertLess(stale[0][0], 5500)
        self.assertFalse(draws[-1][2])
        self.assertGreaterEqual(draws[-1][0], 6100)
        self.assertEqual(draws[-1][1]["cpu"], 2)
        self.assertLess(len(draws), 10)
        self.assertGreater(stream.bytes_read, 1500)


if __name__ == "__main__":
    unittest.main()
