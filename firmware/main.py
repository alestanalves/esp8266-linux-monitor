"""Run on boot. USB/UART JSON lines in; ST7735 dashboard out.

Ctrl-C intentionally returns to the MicroPython REPL so mpremote can update
the firmware. Other malformed/control input is discarded by protocol.py.
"""

import sys
import time
import gc
try:
    import uselect as select
except ImportError:
    import select

import config
from protocol import LineBuffer, parse_line, READY


def prepare_board():
    """USB/UART only: stop Wi-Fi and its AP before allocating display RAM."""
    if sys.platform != config.BOARD:
        raise RuntimeError("Firmware configurado para " + config.BOARD)
    import esp
    import network
    esp.osdebug(None)
    network.WLAN(network.STA_IF).active(False)
    network.WLAN(network.AP_IF).active(False)
    gc.collect()


def make_display():
    if sys.platform != config.BOARD:
        raise RuntimeError("Firmware configurado para " + config.BOARD)
    from machine import Pin, SPI
    from st7735 import ST7735
    # ESP8266 hardware SPI1 pins are fixed. In particular GPIO12/MISO
    # cannot be reused as DC/CS/reset even though the TFT sends no data.
    if (config.SPI_ID, config.SCK_PIN, config.MOSI_PIN) != (1, 14, 13):
        raise ValueError("ESP8266 SPI1 exige SCK GPIO14 e MOSI GPIO13")
    spi = SPI(config.SPI_ID, baudrate=config.SPI_BAUDRATE,
              polarity=0, phase=0)
    gc.collect()
    return ST7735(spi, Pin(config.CS_PIN, Pin.OUT, value=1),
                  Pin(config.DC_PIN, Pin.OUT, value=0),
                  Pin(config.RESET_PIN, Pin.OUT, value=1),
                  rotation=config.ROTATION, x_offset=config.X_OFFSET,
                  y_offset=config.Y_OFFSET, bgr=config.BGR, invert=config.INVERT)


def run():
    prepare_board()
    from dashboard import Dashboard
    gc.collect()
    ui = Dashboard(make_display())
    ui.draw()
    stream = getattr(sys.stdin, "buffer", sys.stdin)
    poller = select.poll()
    poller.register(stream, select.POLLIN)
    parser = LineBuffer(config.MAX_LINE_BYTES)
    stats = None
    last_stats = None
    last_draw = time.ticks_ms()
    was_stale = False
    dirty = False
    while True:
        # Bound serial work so a noisy peer cannot starve stale detection/UI.
        for _ in range(config.SERIAL_BYTES_PER_TICK):
            try:
                events = poller.poll(0)
                if not events or not (events[0][1] & select.POLLIN):
                    break
                char = stream.read(1)
                if not char:
                    break
            except (OSError, ValueError):
                parser.reset()
                break
            for line in parser.feed(char):
                payload = parse_line(line)
                if payload is None:
                    continue
                if payload["type"] == "hello":
                    # Only handshakes produce output; metrics never fill TX.
                    try:
                        sys.stdout.write(READY)
                    except OSError:
                        pass
                else:
                    stats = payload
                    last_stats = time.ticks_ms()
                    dirty = True
        now = time.ticks_ms()
        stale = last_stats is not None and time.ticks_diff(now, last_stats) > config.STALE_MS
        if stale != was_stale:
            dirty = True
        if dirty and time.ticks_diff(now, last_draw) >= config.DRAW_INTERVAL_MS:
            ui.draw(stats, stale)
            last_draw = now
            was_stale = stale
            dirty = False
            gc.collect()
        time.sleep_ms(config.LOOP_SLEEP_MS)


if __name__ == "__main__":
    run()
