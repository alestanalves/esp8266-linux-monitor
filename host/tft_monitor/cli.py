"""Command-line entry point and reconnect loop."""

from __future__ import annotations

import argparse
import logging
import math
import signal
import sys
import threading
import time
from pathlib import Path

import serial

from . import __version__
from .metrics import MetricsCollector
from .transport import MonitorConnection, encode_message

LOG = logging.getLogger(__name__)


def interval_seconds(value):
    number = float(value)
    if not math.isfinite(number) or number < 0.2:
        raise argparse.ArgumentTypeError("o intervalo deve ser pelo menos 0.2 segundos")
    return number


def parser():
    result = argparse.ArgumentParser(description="Monitor Linux/CachyOS na tela TFT do ESP8266 por USB.")
    result.add_argument("--port", default="auto", help="porta serial ou auto (padrão: auto, USB Espressif/CP210x/CH340/CH9102)")
    result.add_argument("--interval", type=interval_seconds, default=1.0, help="intervalo em segundos (padrão: 1)")
    result.add_argument("--disk", default="/", help="caminho do filesystem monitorado (padrão: /)")
    result.add_argument("--interface", default="auto", help="interface de rede ou auto (soma interfaces físicas ativas)")
    result.add_argument("--dump", action="store_true", help="imprime JSON continuamente, sem acessar a serial")
    result.add_argument("--once", action="store_true", help="imprime uma amostra JSON e sai, sem acessar a serial")
    result.add_argument("--verbose", action="store_true", help="habilita logs de diagnóstico")
    result.add_argument("--version", action="version", version=__version__)
    return result


def run_monitor(collector, connection, stop, *, interval=1.0, clock=time.monotonic):
    """Reconnect after cable removal; stop.wait makes shutdown interruptible."""
    last_error = None
    last_report = -math.inf
    try:
        while not stop.is_set():
            try:
                if connection.connection is None:
                    connection.connect(stop)
                    last_error = None
                if stop.is_set():
                    break
                started = clock()
                connection.send(collector.sample())
                stop.wait(max(0.0, interval - (clock() - started)))
            except (OSError, serial.SerialException) as exc:
                connection.close()
                message = str(exc)
                if message != last_error or clock() - last_report >= 30:
                    LOG.warning("%s; nova tentativa em 2 s", message)
                    last_error = message
                    last_report = clock()
                stop.wait(2.0)
    finally:
        connection.close()


def main(argv=None):
    args = parser().parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s")
    if not Path(args.disk).exists():
        LOG.error("Caminho de disco inexistente: %s", args.disk)
        return 2
    stop = threading.Event()
    previous_handlers = {}
    for sig in (signal.SIGINT, signal.SIGTERM):
        previous_handlers[sig] = signal.signal(sig, lambda *_: stop.set())
    try:
        collector = MetricsCollector(disk=args.disk, interface=args.interface)
        if args.interface != "auto" and args.interface not in collector.previous_net:
            LOG.warning("Interface %s ausente; taxas serão zero até ela aparecer", args.interface)
        # psutil's first nonblocking CPU sample is not meaningful.
        stop.wait(min(args.interval, 1.0))
        if args.dump or args.once:
            while not stop.is_set():
                started = time.monotonic()
                sys.stdout.write(encode_message(collector.sample()).decode("ascii"))
                sys.stdout.flush()
                if args.once:
                    break
                stop.wait(max(0.0, args.interval - (time.monotonic() - started)))
        else:
            run_monitor(collector, MonitorConnection(args.port), stop, interval=args.interval)
        return 0
    except BrokenPipeError:
        return 0
    except (OSError, ValueError) as exc:
        LOG.error("Falha ao coletar métricas: %s", exc)
        return 1
    finally:
        for sig, handler in previous_handlers.items():
            signal.signal(sig, handler)
