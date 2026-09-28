"""Bounded JSON-line handshake and safe USB serial discovery."""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path

import serial
from serial.tools import list_ports

LOG = logging.getLogger(__name__)
PICO_VID = 0x2E8A
ESPRESSIF_VID = 0x303A
USB_UART_IDS = {(0x10C4, 0xEA60), (0x1A86, 0x7523), (0x1A86, 0x55D4)}
MAX_LINE = 1024


class DeviceUnavailable(OSError):
    pass


def encode_message(message):
    return (json.dumps(message, ensure_ascii=True, allow_nan=False, separators=(",", ":")) + "\n").encode("ascii")


def candidate_ports(port="auto", ports=None):
    if port != "auto":
        return [port]
    detected = list_ports.comports() if ports is None else ports
    return sorted({entry.device for entry in detected
                   if entry.vid in (ESPRESSIF_VID, PICO_VID)
                   or (entry.vid, entry.pid) in USB_UART_IDS})


def control_lines(port, ports=None):
    """Do not assert reset/boot lines on ESP8266/ESP32 USB-UART bridges.

    Native USB CDC needs DTR; bridge DTR/RTS may be wired to GPIO0/EN.
    Configure the states before open(), although some OS drivers can still
    produce a transient pulse when the underlying file descriptor opens.
    Unknown explicit ports use the conservative USB-UART settings.
    """
    detected = list_ports.comports() if ports is None else ports
    target = Path(port).resolve()
    for entry in detected:
        if Path(entry.device).resolve() == target:
            return entry.vid in (ESPRESSIF_VID, PICO_VID), entry.vid == PICO_VID
    return False, False


def handshake(connection, stop, *, timeout=4.0, clock=time.monotonic):
    deadline = clock() + timeout
    next_hello = 0.0
    pending = bytearray()
    dropping = False
    while not stop.is_set() and clock() < deadline:
        now = clock()
        if now >= next_hello:
            connection.write(encode_message({"v": 1, "type": "hello"}))
            next_hello = now + 0.6
        chunk = connection.read_until(b"\n", MAX_LINE)
        if not chunk:
            continue
        if dropping:
            if chunk.endswith(b"\n"):
                dropping = False
            continue
        pending.extend(chunk)
        if len(pending) > MAX_LINE:
            pending.clear()
            dropping = not chunk.endswith(b"\n")
            continue
        if not pending.endswith(b"\n"):
            continue
        try:
            reply = json.loads(pending)
        except (ValueError, UnicodeError):
            reply = None
        pending.clear()
        if isinstance(reply, dict) and type(reply.get("v")) is int and reply["v"] == 1 and reply.get("type") == "ready" and reply.get("device") in ("tft-monitor", "pico-monitor"):
            return
    raise DeviceUnavailable("ESP8266 não respondeu ao protocolo tft-monitor; verifique o firmware e feche o mpremote/Thonny")


class MonitorConnection:
    def __init__(self, port="auto", *, serial_factory=serial.Serial, discover=candidate_ports,
                 line_settings=control_lines):
        self.port = port
        self.serial_factory = serial_factory
        self.discover = discover
        self.line_settings = line_settings
        self.connection = None

    def connect(self, stop):
        self.close()
        ports = self.discover(self.port)
        if not ports:
            raise DeviceUnavailable("ESP8266 USB não encontrado (CP210x/CH340/CH9102); aguardando conexão")
        errors = []
        for port in ports:
            if stop.is_set():
                break
            connection = None
            try:
                connection = self.serial_factory(port=None, baudrate=115200, timeout=0.2,
                                                 write_timeout=1.0, exclusive=True)
                connection.dtr, connection.rts = self.line_settings(port)
                connection.port = port
                connection.open()
                connection.reset_input_buffer()
                handshake(connection, stop)
                self.connection = connection
                LOG.info("Monitor conectado em %s", port)
                return
            except (OSError, serial.SerialException) as exc:
                errors.append(f"{port}: {exc}")
                if connection is not None:
                    try:
                        connection.close()
                    except (OSError, serial.SerialException):
                        pass
        raise DeviceUnavailable("; ".join(errors) or "Conexão interrompida")

    def send(self, message):
        if self.connection is None:
            raise DeviceUnavailable("Monitor desconectado")
        payload = encode_message(message)
        written = self.connection.write(payload)
        if written != len(payload):
            raise DeviceUnavailable("Escrita serial incompleta")

    def close(self):
        if self.connection is not None:
            try:
                self.connection.close()
            except (OSError, serial.SerialException):
                pass
            finally:
                self.connection = None
