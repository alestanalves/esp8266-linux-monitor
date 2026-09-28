"""Stream forwarding contracts without accessing a physical serial device."""

import importlib.util
import io
from pathlib import Path
import queue
import threading
from types import SimpleNamespace

import pytest

from tft_monitor.transport import encode_message


@pytest.fixture
def bridge():
    path = Path(__file__).resolve().parents[1] / "scripts/serial-stream.py"
    spec = importlib.util.spec_from_file_location("serial_stream_under_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def sample(cpu):
    return {"v": 1, "type": "stats", "host": "linux", "cpu": cpu}


def test_reader_keeps_only_latest_sample_when_consumer_is_unavailable(bridge):
    samples = queue.Queue(maxsize=1)
    finished = threading.Event()
    errors = []
    source = io.BytesIO(b"".join(encode_message(sample(i)) for i in range(100)))

    bridge.read_samples(source, samples, finished, errors)

    assert finished.is_set()
    assert not errors
    assert samples.qsize() == 1
    captured, newest = samples.get_nowait()
    assert captured > 0
    assert newest == sample(99)


@pytest.mark.parametrize("invalid", [
    b'{"v":1,"type":"stats","cpu":NaN}\n',
    b'{"v":1,"type":"hello"}\n',
    b'{"v":1,"type":"stats"}',  # EOF midway through a frame.
    b"x" * 1025 + b"\n",
    b"\xff\n",
])
def test_invalid_input_finishes_with_error_without_queuing_data(bridge, invalid):
    samples = queue.Queue(maxsize=1)
    finished = threading.Event()
    errors = []

    bridge.read_samples(io.BytesIO(invalid), samples, finished, errors)

    assert finished.is_set()
    assert errors
    assert samples.empty()


def prepare_main(monkeypatch, bridge, data, on_connect=None):
    """Finish stdin deterministically, then exercise the consumer loop."""
    samples = queue.Queue(maxsize=1)
    now = [100.0]

    class InlineReader:
        def __init__(self, *, target, args, daemon):
            self.target, self.args = target, args

        def start(self):
            self.target(*self.args)

    class Monitor:
        connection = None
        attempts = 0
        sent = []
        closed = False

        def connect(self, stop):
            self.attempts += 1
            if on_connect:
                on_connect(self, samples, now)
            self.connection = object()

        def send(self, payload):
            self.sent.append(payload)

        def close(self):
            self.closed = True
            self.connection = None

    monitor = Monitor()
    monkeypatch.setattr(bridge, "MonitorConnection", lambda port: monitor)
    monkeypatch.setattr(bridge, "queue", SimpleNamespace(Queue=lambda maxsize: samples, Empty=queue.Empty))
    monkeypatch.setattr(bridge, "threading", SimpleNamespace(Event=threading.Event, Thread=InlineReader))
    monkeypatch.setattr(bridge, "time", SimpleNamespace(monotonic=lambda: now[0], sleep=lambda seconds: None))
    monkeypatch.setattr(bridge, "sys", SimpleNamespace(stdin=SimpleNamespace(buffer=io.BytesIO(data))))
    return monitor


def test_eof_sends_last_sample_once_and_closes_connection(bridge, monkeypatch):
    monitor = prepare_main(monkeypatch, bridge, encode_message(sample(25)))

    assert bridge.main(["--port", "TEST"]) == 0

    assert monitor.sent == [sample(25)]
    assert monitor.closed


def test_empty_eof_never_opens_serial(bridge, monkeypatch):
    monitor = prepare_main(monkeypatch, bridge, b"")

    assert bridge.main([]) == 0

    assert monitor.attempts == 0
    assert monitor.closed


def test_sample_that_ages_during_connect_is_not_replayed(bridge, monkeypatch):
    def delayed_connection(monitor, samples, now):
        now[0] += 4.0

    monitor = prepare_main(monkeypatch, bridge, encode_message(sample(25)), delayed_connection)

    assert bridge.main([]) == 0

    assert monitor.sent == []
    assert monitor.closed


def test_reconnect_delivers_new_sample_instead_of_failed_sample(bridge, monkeypatch):
    def interrupted_connection(monitor, samples, now):
        if monitor.attempts == 1:
            bridge.read_samples(io.BytesIO(encode_message(sample(75))), samples, threading.Event(), [])
            raise OSError("USB disconnected")

    monitor = prepare_main(monkeypatch, bridge, encode_message(sample(25)), interrupted_connection)

    assert bridge.main([]) == 0

    assert monitor.attempts == 2
    assert monitor.sent == [sample(75)]
    assert monitor.closed


def test_invalid_stdin_returns_failure_and_closes_connection(bridge, monkeypatch):
    monitor = prepare_main(monkeypatch, bridge, b"invalid JSON\n")

    assert bridge.main([]) == 1

    assert monitor.attempts == 0
    assert monitor.closed
