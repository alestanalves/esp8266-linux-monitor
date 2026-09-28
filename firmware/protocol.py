"""Bounded JSON-lines transport and validation, usable in MicroPython/CPython."""

try:
    import ujson as json
except ImportError:
    import json


READY = '{"v":1,"type":"ready","device":"tft-monitor"}\n'


class LineBuffer:
    def __init__(self, limit=1024):
        self.limit = limit
        self.buffer = bytearray()
        self.dropping = False

    def reset(self):
        self.buffer = bytearray()
        self.dropping = False

    def feed(self, chunk):
        """Return complete byte lines. Discard oversized frames up to newline."""
        if isinstance(chunk, str):
            chunk = chunk.encode()
        lines = []
        for byte in chunk:
            if byte == 10:
                if self.buffer and not self.dropping:
                    lines.append(bytes(self.buffer))
                self.reset()
            elif byte == 13:
                continue
            elif byte < 32 or byte == 127:
                # Raw-REPL control bytes invalidate the partial frame. Ctrl-C
                # remains an intentional REPL escape at the MicroPython level.
                self.reset()
            elif not self.dropping:
                if len(self.buffer) >= self.limit:
                    self.buffer = bytearray()
                    self.dropping = True
                else:
                    self.buffer.append(byte)
        return lines


def _number(value, low, high):
    # Chained comparisons reject NaN and infinity as well as invalid ranges.
    return type(value) in (int, float) and low <= value <= high


def parse_line(line):
    """Return validated hello/stats, or None. Never trust peer JSON types."""
    try:
        if len(line) > 1024:
            return None
        if isinstance(line, (bytes, bytearray)):
            line = line.decode("utf-8")
        payload = json.loads(line)
        if not isinstance(payload, dict) or type(payload.get("v")) is not int:
            return None
        if payload["v"] != 1:
            return None
        kind = payload.get("type")
        if kind == "hello":
            return {"v": 1, "type": "hello"}
        if kind != "stats":
            return None
        for field in ("cpu", "ram", "disk"):
            if not _number(payload.get(field), 0, 100):
                return None
        for field in ("temp", "gpu_temp"):
            value = payload.get(field)
            if value is not None and not _number(value, -100, 250):
                return None
        gpu = payload.get("gpu")
        if gpu is not None and not _number(gpu, 0, 100):
            return None
        for field in ("rx", "tx"):
            if not _number(payload.get(field), 0, 1e15):
                return None
        if not _number(payload.get("uptime"), 0, 1e12):
            return None
        host = payload.get("host")
        clock = payload.get("time")
        if not isinstance(host, str) or not host or len(host) > 255:
            return None
        if not isinstance(clock, str) or len(clock) != 5 or clock[2] != ":":
            return None
        digits = clock[:2] + clock[3:]
        if not all("0" <= digit <= "9" for digit in digits):
            return None
        if int(clock[:2]) > 23 or int(clock[3:]) > 59:
            return None
        # Only expose known keys to the drawing code; unsupported sensor values
        # use None. Printable ASCII prevents framebuffer control/font glitches.
        result = {key: payload[key] for key in
                  ("cpu", "ram", "disk", "rx", "tx", "uptime", "time")}
        result.update({"v": 1, "type": "stats",
                       "host": "".join(c if 32 <= ord(c) < 127 else "?" for c in host),
                       "temp": payload.get("temp"), "gpu": gpu,
                       "gpu_temp": payload.get("gpu_temp")})
        return result
    except (ValueError, TypeError, KeyError, OverflowError, MemoryError, RuntimeError):
        return None
