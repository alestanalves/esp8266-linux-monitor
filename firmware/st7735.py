"""ST7735S driver with a 10 KiB indexed framebuffer for the ESP8266.

Commands follow the Sitronix ST7735S v1.3 datasheet. No third-party driver.
Use color565() for all drawing colors (up to 16 distinct colors per frame).
fill() begins a new palette. Drawing uses native framebuf primitives/font;
show() expands one scanline at a time into RGB565 in SPI wire byte order.
"""

import framebuf
import time
import gc


def color565(red, green, blue):
    value = ((red & 0xF8) << 8) | ((green & 0xFC) << 3) | (blue >> 3)
    return ((value & 0xFF) << 8) | (value >> 8)


class ST7735:
    def __init__(self, spi, cs, dc, rst, rotation=1, x_offset=0, y_offset=0,
                 bgr=True, invert=False):
        if rotation not in (0, 1, 2, 3):
            raise ValueError("ROTATION precisa estar entre 0 e 3")
        if not (0 <= x_offset <= 4 and 0 <= y_offset <= 4):
            raise ValueError("Offsets precisam estar entre 0 e 4")
        self.spi = spi
        self.cs = cs
        self.dc = dc
        self.rst = rst
        self.width, self.height = ((160, 128) if rotation & 1 else (128, 160))
        self.x_offset = x_offset
        self.y_offset = y_offset
        gc.collect()
        self.buffer = bytearray(self.width * self.height // 2)
        self._fb = framebuf.FrameBuffer(self.buffer, self.width, self.height,
                                       framebuf.GS4_HMSB)
        self._row = bytearray(self.width * 2)
        self._row_fb = framebuf.FrameBuffer(self._row, self.width, 1,
                                           framebuf.RGB565)
        self._palette = bytearray(32)
        self._palette_fb = framebuf.FrameBuffer(self._palette, 16, 1,
                                               framebuf.RGB565)
        self._colors = {}
        self.cs.value(1)
        self.dc.value(0)
        self.rst.value(1)
        time.sleep_ms(10)
        self.rst.value(0)
        time.sleep_ms(20)
        self.rst.value(1)
        time.sleep_ms(120)
        self.command(0x01)  # SWRESET
        time.sleep_ms(150)
        self.command(0x11)  # SLPOUT
        time.sleep_ms(120)
        self.command(0xB1, b"\x01\x2c\x2d")  # frame rate, normal mode
        self.command(0xB2, b"\x01\x2c\x2d")
        self.command(0xB3, b"\x01\x2c\x2d\x01\x2c\x2d")
        self.command(0xB4, b"\x07")  # inversion control
        self.command(0xC0, b"\xa2\x02\x84")
        self.command(0xC1, b"\xc5")
        self.command(0xC2, b"\x0a\x00")
        self.command(0xC3, b"\x8a\x2a")
        self.command(0xC4, b"\x8a\xee")
        self.command(0xC5, b"\x0e")  # VCOM
        self.command(0x3A, b"\x05")  # COLMOD: 16-bit RGB565
        madctl = (0xC0, 0xA0, 0x00, 0x60)[rotation]
        self.command(0x36, bytes((madctl | (0x08 if bgr else 0),)))
        self.command(0xE0, b"\x02\x1c\x07\x12\x37\x32\x29\x2d\x29\x25\x2b\x39\x00\x01\x03\x10")
        self.command(0xE1, b"\x03\x1d\x07\x06\x2e\x2c\x29\x2d\x2e\x2e\x37\x3f\x00\x00\x02\x10")
        self.command(0x21 if invert else 0x20)
        self.command(0x13)  # NORON
        time.sleep_ms(10)
        self.fill(0)
        self.show()
        self.command(0x29)  # DISPON
        time.sleep_ms(100)

    def _color_index(self, color):
        index = self._colors.get(color)
        if index is None:
            index = len(self._colors)
            if index == 16:
                raise ValueError("Maximo de 16 cores por quadro; use fill()")
            self._colors[color] = index
            self._palette_fb.pixel(index, 0, color)
        return index

    def fill(self, color):
        # No pixels from the previous frame remain, so its palette can go.
        self._colors.clear()
        self._fb.fill(self._color_index(color))

    def pixel(self, x, y, color=None):
        if color is None:
            index = self._fb.pixel(x, y)
            return None if index is None else self._palette_fb.pixel(index, 0)
        self._fb.pixel(x, y, self._color_index(color))

    def fill_rect(self, x, y, width, height, color):
        self._fb.fill_rect(x, y, width, height, self._color_index(color))

    def rect(self, x, y, width, height, color):
        self._fb.rect(x, y, width, height, self._color_index(color))

    def hline(self, x, y, width, color):
        self._fb.hline(x, y, width, self._color_index(color))

    def vline(self, x, y, height, color):
        self._fb.vline(x, y, height, self._color_index(color))

    def text(self, value, x, y, color):
        self._fb.text(value, x, y, self._color_index(color))

    def command(self, command, data=None):
        self.cs.value(0)
        try:
            self.dc.value(0)
            self.spi.write(bytes((command,)))
            if data is not None:
                self.dc.value(1)
                self.spi.write(data)
        finally:
            self.cs.value(1)

    def show(self):
        x0, y0 = self.x_offset, self.y_offset
        x1, y1 = x0 + self.width - 1, y0 + self.height - 1
        self.command(0x2A, bytes((x0 >> 8, x0 & 255, x1 >> 8, x1 & 255)))
        self.command(0x2B, bytes((y0 >> 8, y0 & 255, y1 >> 8, y1 & 255)))
        self.cs.value(0)
        try:
            self.dc.value(0)
            self.spi.write(b"\x2c")
            self.dc.value(1)
            for y in range(self.height):
                # C blit clips the full source to this one destination row
                # and converts palette indices without Python pixel loops.
                self._row_fb.blit(self._fb, 0, -y, -1, self._palette_fb)
                self.spi.write(self._row)
        finally:
            self.cs.value(1)
