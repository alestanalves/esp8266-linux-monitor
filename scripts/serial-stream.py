#!/usr/bin/env python3
"""Forward the Linux collector's JSON stream to a Windows USB serial port.

Run under Windows Python with pyserial installed. The WSL collector supplies
stdin via ``tft-monitor --dump``; only the newest sample is kept on reconnect.
"""

from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path
import queue
import sys
import threading
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "host"))

from tft_monitor.transport import MonitorConnection, encode_message, handshake

LOG = logging.getLogger("serial-stream")


def read_samples(stream, samples, finished, errors):
    try:
        while True:
            line = stream.readline(1025)
            if not line:
                break
            if len(line) > 1024 or not line.endswith(b"\n"):
                raise ValueError("Amostra ultrapassa o limite de 1024 bytes")
            sample = json.loads(line)
            if not isinstance(sample, dict) or sample.get("v") != 1 or sample.get("type") != "stats":
                raise ValueError("Esperado pacote stats v1 do coletor Linux")
            encode_message(sample)  # Reject non-finite numbers before serial I/O.
            try:
                samples.get_nowait()
            except queue.Empty:
                pass
            samples.put_nowait((time.monotonic(), sample))
    except (OSError, ValueError) as exc:
        errors.append(str(exc))
    finally:
        finished.set()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", default="auto")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    samples = queue.Queue(maxsize=1)
    finished = threading.Event()
    stop = threading.Event()
    errors = []
    reader = threading.Thread(target=read_samples, args=(sys.stdin.buffer, samples, finished, errors), daemon=True)
    reader.start()
    monitor = MonitorConnection(args.port)
    sent = 0
    checked = time.monotonic()
    try:
        while not finished.is_set() or not samples.empty():
            try:
                captured, sample = samples.get(timeout=0.2)
            except queue.Empty:
                continue
            try:
                if monitor.connection is None:
                    monitor.connect(stop)
                # The firmware must show stale data if the collector stops.
                if time.monotonic() - captured > 3:
                    continue
                monitor.send(sample)
                sent += 1
                if sent == 1:
                    LOG.info("Metricas Linux em envio: host=%s, porta=%s", sample.get("host"), args.port)
                if time.monotonic() - checked >= 30:
                    handshake(monitor.connection, stop)
                    LOG.info("ESP8266 respondeu; %d amostras enviadas", sent)
                    checked = time.monotonic()
            except OSError as exc:
                LOG.warning("%s; nova tentativa em 2 s", exc)
                monitor.close()
                time.sleep(2)
    except KeyboardInterrupt:
        pass
    finally:
        stop.set()
        monitor.close()
    if errors:
        LOG.error("Entrada encerrada: %s", errors[0])
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
