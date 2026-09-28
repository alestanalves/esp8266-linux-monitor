"""Compact dashboard for both 160x128 landscape and 128x160 portrait."""

from st7735 import color565

BACKGROUND = color565(9, 16, 27)
PANEL = color565(22, 35, 51)
TEXT = color565(236, 243, 249)
MUTED = color565(145, 165, 184)
CYAN = color565(44, 211, 226)
GREEN = color565(74, 222, 128)
AMBER = color565(251, 191, 36)
RED = color565(248, 91, 100)


def rate_text(value):
    """At most five characters; binary B/K/M/G per second."""
    for unit in ("B", "K", "M", "G"):
        if value < 1024 or unit == "G":
            if value < 10 and unit != "B":
                return "%.1f%s" % (value, unit)
            return "%d%s" % (min(int(value), 9999), unit)
        value /= 1024


def uptime_text(seconds):
    minutes = int(seconds) // 60
    hours, minutes = divmod(minutes, 60)
    days, hours = divmod(hours, 24)
    if days:
        return "%dd%02dh" % (min(days, 999), hours)
    return "%02dh%02dm" % (hours, minutes)


def temperature_text(value):
    return "--" if value is None else "%dC" % round(value)


class Dashboard:
    def __init__(self, display):
        self.display = display
        self.width = display.width
        self.height = display.height
        self.columns = (self.width - 12) // 8

    def text(self, value, x, y, color=TEXT):
        available = (self.width - 6 - x) // 8
        if available > 0:
            self.display.text(str(value)[:available], x, y, color)

    def right(self, value, y, color=TEXT):
        value = str(value)[:self.columns]
        self.text(value, self.width - 6 - len(value) * 8, y, color)

    def bar(self, title, value, y, accent):
        d = self.display
        color = RED if value >= 90 else (AMBER if value >= 75 else accent)
        self.text(title, 6, y, MUTED)
        self.right("%3d%%" % round(value), y, color)
        d.fill_rect(6, y + 11, self.width - 12, 7, PANEL)
        filled = int((self.width - 12) * value / 100)
        if filled:
            d.fill_rect(6, y + 11, filled, 7, color)

    def draw(self, stats=None, stale=False):
        d = self.display
        d.fill(BACKGROUND)
        if stats is None:
            self._waiting()
        else:
            self._stats(stats, stale)
        d.show()

    def _waiting(self):
        d = self.display
        self.text("TFT MONITOR", 6, 8, CYAN)
        d.hline(6, 23, self.width - 12, PANEL)
        mid = self.width // 2
        d.rect(mid - 19, 34, 38, 24, MUTED)
        d.hline(mid - 10, 62, 20, MUTED)
        d.vline(mid, 58, 4, MUTED)
        self.text("AGUARDANDO USB", 6, 77, TEXT)
        self.text("Inicie o agente", 6, 92, MUTED)
        self.text("no Linux", 6, 104, MUTED)
        d.fill_rect(0, self.height - 14, self.width, 14, PANEL)
        self.text("SEM DADOS", 6, self.height - 11, AMBER)

    def _stats(self, stats, stale):
        d = self.display
        # Reserve five clock characters and one gap, even in portrait mode.
        host_columns = (self.width - 12 - 48) // 8
        self.text(stats["host"][:host_columns], 6, 5, CYAN)
        self.right(stats["time"], 5, MUTED)
        d.hline(6, 17, self.width - 12, PANEL)
        self.bar("CPU", stats["cpu"], 22, CYAN)
        self.bar("RAM", stats["ram"], 46, GREEN)
        temp = temperature_text(stats["temp"])
        disk = "%d%%" % round(stats["disk"])
        gpu = "--" if stats["gpu"] is None else "%d%%" % round(stats["gpu"])
        gpu_temp = temperature_text(stats["gpu_temp"])
        if self.width >= 160:
            self.text("CPU %s DSK %s" % (temp, disk), 6, 71)
            self.text("GPU %s %s" % (gpu, gpu_temp), 6, 84, MUTED)
            self.text("R %s T %s" % (rate_text(stats["rx"]), rate_text(stats["tx"])),
                      6, 97, CYAN)
        else:
            self.text("CPU " + temp, 6, 71)
            self.text("DSK " + disk, 6, 84)
            self.text("GPU %s %s" % (gpu, gpu_temp), 6, 97, MUTED)
            self.text("RX " + rate_text(stats["rx"]) + "/s", 6, 111, CYAN)
            self.text("TX " + rate_text(stats["tx"]) + "/s", 6, 123, CYAN)
        d.fill_rect(0, self.height - 14, self.width, 14, PANEL)
        status = "SEM SINAL" if stale else "USB"
        # In portrait, use a compact disconnected label to reserve uptime.
        if self.width < 160 and stale:
            status = "OFF"
        self.text(status, 6, self.height - 11, AMBER if stale else GREEN)
        self.right(uptime_text(stats["uptime"]), self.height - 11, MUTED)
