"""Check display wire bytes and UI geometry; no claim of visual hardware testing."""

import importlib.util
from pathlib import Path
import struct
from types import SimpleNamespace
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1] / "firmware"


def load(name):
    spec = importlib.util.spec_from_file_location("test_fw_" + name, ROOT / (name + ".py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class FrameBuffer:
    """Small model of GS4_HMSB and native little-endian RGB565 framebuf."""
    def __init__(self, buffer, width, height, mode):
        self.storage = buffer
        self.width, self.height = width, height
        self.mode = mode
        self.texts = []

    def pixel(self, x, y, color=None):
        if not (0 <= x < self.width and 0 <= y < self.height):
            return None
        pixel = y * self.width + x
        if self.mode == 1:
            if color is None:
                return struct.unpack_from("<H", self.storage, pixel * 2)[0]
            struct.pack_into("<H", self.storage, pixel * 2, color)
        else:
            shift = 0 if x % 2 else 4
            if color is None:
                return (self.storage[pixel // 2] >> shift) & 15
            self.storage[pixel // 2] = ((self.storage[pixel // 2] & ~(15 << shift))
                                       | ((color & 15) << shift))

    def fill(self, color):
        if self.mode == 1:
            self.storage[:] = struct.pack("<H", color) * (self.width * self.height)
        else:
            self.storage[:] = bytes(((color << 4) | color,)) * len(self.storage)

    def fill_rect(self, x, y, width, height, color):
        for row in range(y, y + height):
            for column in range(x, x + width):
                self.pixel(column, row, color)

    def hline(self, x, y, width, color):
        self.fill_rect(x, y, width, 1, color)

    def vline(self, x, y, height, color):
        self.fill_rect(x, y, 1, height, color)

    def rect(self, x, y, width, height, color):
        self.hline(x, y, width, color)
        self.hline(x, y + height - 1, width, color)
        self.vline(x, y, height, color)
        self.vline(x + width - 1, y, height, color)

    def text(self, value, x, y, color):
        # Verify forwarding to the native font without inventing a test font.
        self.texts.append((value, x, y, color))

    def blit(self, source, x, y, key, palette):
        for row in range(self.height):
            for column in range(self.width):
                value = source.pixel(column - x, row - y)
                if value is not None:
                    color = palette.pixel(value, 0)
                    if color != key:
                        self.pixel(column, row, color)


with patch.dict("sys.modules", {"framebuf": SimpleNamespace(
        FrameBuffer=FrameBuffer, RGB565=1, GS4_HMSB=2)}):
    driver = load("st7735")
with patch.dict("sys.modules", {"st7735": driver}):
    dashboard = load("dashboard")


class Pin:
    def __init__(self):
        self.state = 0

    def value(self, state=None):
        if state is not None:
            self.state = state
        return self.state


class SPI:
    def __init__(self, cs, dc):
        self.cs, self.dc = cs, dc
        self.writes = []

    def write(self, data):
        assert self.cs.state == 0
        self.writes.append((self.dc.state, bytes(data)))


class Display:
    """Record draws and reject any off-screen primitive or text."""
    def __init__(self, width, height):
        self.width, self.height = width, height
        self.texts = []

    def fill(self, color):
        self.texts.clear()

    def rect(self, x, y, width, height, color):
        assert x >= 0 and y >= 0 and width > 0 and height > 0
        assert x + width <= self.width and y + height <= self.height

    fill_rect = rect

    def hline(self, x, y, width, color):
        self.rect(x, y, width, 1, color)

    def vline(self, x, y, height, color):
        self.rect(x, y, 1, height, color)

    def text(self, value, x, y, color):
        self.rect(x, y, len(value) * 8, 8, color)
        # At the same baseline, text should never overlap another field.
        for old, old_x, old_y in self.texts:
            if y == old_y:
                assert x >= old_x + len(old) * 8 or old_x >= x + len(value) * 8
        self.texts.append((value, x, y))

    def show(self):
        pass


class DriverTests(unittest.TestCase):
    def make_display(self, **kwargs):
        cs, dc, rst = Pin(), Pin(), Pin()
        spi = SPI(cs, dc)
        with patch.object(driver.time, "sleep_ms", create=True):
            display = driver.ST7735(spi, cs, dc, rst, **kwargs)
        return display, spi

    def test_rgb565_pixel_byte_order_matches_wire(self):
        display, spi = self.make_display()
        for rgb, wire in [((255, 0, 0), b"\xf8\x00"),
                          ((0, 255, 0), b"\x07\xe0"),
                          ((0, 0, 255), b"\x00\x1f")]:
            display.fill(driver.color565(*rgb))
            spi.writes.clear()
            display.show()
            self.assertEqual(len(spi.writes[5:]), 128)
            self.assertTrue(all(row == (1, wire * 160) for row in spi.writes[5:]))

    def test_distinct_pixels_and_rows_expand_without_reversing_nibbles(self):
        display, spi = self.make_display()
        red = driver.color565(255, 0, 0)
        green = driver.color565(0, 255, 0)
        blue = driver.color565(0, 0, 255)
        display.fill(0)
        display.pixel(0, 0, red)
        display.pixel(1, 0, green)
        display.pixel(159, 127, blue)
        self.assertEqual(display.pixel(0, 0), red)
        self.assertEqual(display.pixel(1, 0), green)
        self.assertEqual(display.pixel(159, 127), blue)
        spi.writes.clear()
        display.show()
        self.assertEqual(spi.writes[5][1], b"\xf8\x00\x07\xe0" + b"\0" * 316)
        self.assertEqual(spi.writes[6][1], b"\0" * 320)
        self.assertEqual(spi.writes[-1][1], b"\0" * 318 + b"\x00\x1f")

    def test_display_buffers_fit_esp8266_and_palette_resets_between_frames(self):
        display, _ = self.make_display()
        self.assertEqual(len(display.buffer), 10240)
        self.assertEqual(len(display._row), 320)
        self.assertEqual(len(display._palette), 32)
        display.fill(0)
        for color in range(1, 16):
            display.pixel(color, 0, color)
        with self.assertRaisesRegex(ValueError, "16 cores"):
            display.pixel(16, 0, 16)
        display.fill(100)
        display.pixel(0, 0, 200)
        self.assertEqual(display.pixel(0, 0), 200)
        self.assertEqual(display.pixel(1, 0), 100)

    def test_drawing_primitives_and_native_font_use_palette_indices(self):
        display, _ = self.make_display()
        color = driver.color565(12, 200, 34)
        display.fill(0)
        display.fill_rect(2, 2, 3, 4, color)
        display.hline(10, 10, 4, color)
        display.vline(20, 20, 3, color)
        display.rect(30, 30, 4, 4, color)
        display.text("CPU", 6, 40, color)
        for point in ((2, 2), (4, 5), (13, 10), (20, 22), (33, 33)):
            self.assertEqual(display.pixel(*point), color)
        self.assertEqual(display.pixel(31, 31), 0)
        self.assertEqual(display._fb.texts, [("CPU", 6, 40, 1)])

    def test_rotations_and_offsets_set_correct_windows(self):
        for rotation, dimensions in [(0, (128, 160)), (1, (160, 128)),
                                     (2, (128, 160)), (3, (160, 128))]:
            with self.subTest(rotation=rotation):
                display, spi = self.make_display(rotation=rotation, x_offset=1, y_offset=2)
                self.assertEqual((display.width, display.height), dimensions)
                spi.writes.clear()
                display.show()
                self.assertEqual(spi.writes[:4], [
                    (0, b"\x2a"), (1, bytes((0, 1, 0, dimensions[0]))),
                    (0, b"\x2b"), (1, bytes((0, 2, 0, dimensions[1] + 1)))])
                self.assertEqual(spi.cs.state, 1)

    def test_spi_exception_releases_chip_select(self):
        display, spi = self.make_display()
        with patch.object(spi, "write", side_effect=OSError("SPI failed")):
            with self.assertRaises(OSError):
                display.command(0x29)
        self.assertEqual(spi.cs.state, 1)
        with patch.object(spi, "write", side_effect=[None] * 5 + [OSError("SPI failed")]):
            with self.assertRaises(OSError):
                display.show()
        self.assertEqual(spi.cs.state, 1)


class DashboardTests(unittest.TestCase):
    def test_waiting_normal_stale_and_extreme_values_fit_screen(self):
        for width, height in [(160, 128), (128, 160)]:
            display = Display(width, height)
            ui = dashboard.Dashboard(display)
            ui.draw()
            for value in (0, 100):
                payload = dict(host="a" * 255, cpu=value, ram=value, disk=value,
                               temp=-100, gpu=value, gpu_temp=250, rx=1e15, tx=1023,
                               uptime=1e12, time="23:59")
                for stale in (False, True):
                    ui.draw(payload, stale)
                payload.update(temp=None, gpu=None, gpu_temp=None)
                ui.draw(payload)

    def test_unit_formatting_and_uptime(self):
        self.assertEqual(dashboard.rate_text(1024), "1.0K")
        self.assertEqual(dashboard.rate_text(1024 * 1024), "1.0M")
        self.assertEqual(dashboard.uptime_text(90000), "1d01h")
        for value in (0, 1023, 1024, 1024 ** 2 - 1, 1e15):
            self.assertLessEqual(len(dashboard.rate_text(value)), 5)


if __name__ == "__main__":
    unittest.main()
