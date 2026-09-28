"""Deployment checks with a fake mpremote process and no USB hardware."""

import hashlib
import json
from pathlib import Path
import subprocess
import tempfile
from types import SimpleNamespace
import unittest

from scripts.flash import DeploymentError, RESULT_MARKER, choose_port, deploy


def port(device="/dev/ttyUSB0", vid=0x10C4, pid=0xEA60):
    return SimpleNamespace(device=device, vid=vid, pid=pid, serial_number="TEST123")


class FakeMpremote:
    def __init__(
        self, old_files, *, fail_backup=None, platform="esp8266", corrupt=False,
        machine="ESP module with ESP8266", implementation_machine="", fail_prepare=False,
    ):
        self.files = dict(old_files)
        self.events = []
        self.fail_backup = fail_backup
        self.platform = platform
        self.corrupt = corrupt
        self.machine = machine
        self.implementation_machine = implementation_machine
        self.fail_prepare = fail_prepare

    def __call__(self, command, **kwargs):
        assert kwargs["capture_output"] and kwargs["text"]
        assert "resume" in command
        args = command[command.index("resume") + 1:]
        stdout = ""
        if args[:2] == ["soft-reset", "exec"]:
            self.events.append(("soft-reset", None))
            if self.fail_prepare:
                return subprocess.CompletedProcess(command, 1, "secret", "secret")
        elif args[:2] == ["fs", "cp"]:
            source, destination = args[2:]
            if source.startswith(":/"):
                name = source[2:]
                self.events.append(("backup", name))
                if name == self.fail_backup:
                    return subprocess.CompletedProcess(command, 1, "secret", "secret")
                Path(destination).write_bytes(self.files[name])
            else:
                name = destination[2:]
                self.events.append(("write", name))
                self.files[name] = Path(source).read_bytes()
        elif args[:2] == ["exec", "--no-follow"]:
            assert "time.sleep_ms(100); machine.reset()" in args[2]
            self.events.append(("reset", None))
        elif "_existing" in args[1]:
            self.events.append(("identify", None))
            info = {
                "implementation": "micropython", "platform": self.platform,
                "machine": self.machine,
                "implementation_machine": self.implementation_machine,
                "existing": {name: [0x8000, len(body)] for name, body in self.files.items()},
            }
            stdout = RESULT_MARKER + json.dumps(info) + "\r\n"
        else:
            assert args[1].index("_gc.collect()") < args[1].index("import hashlib")
            self.events.append(("verify", None))
            hashes = {
                name: hashlib.sha256(body).hexdigest()
                for name, body in self.files.items() if name != "boot.py"
            }
            stdout = RESULT_MARKER + json.dumps({} if self.corrupt else hashes)
        return subprocess.CompletedProcess(command, 0, stdout, "")


class PortSelectionTests(unittest.TestCase):
    def test_auto_filters_other_usb_vendors(self):
        esp8266 = port()
        self.assertIs(choose_port([port("/dev/ttyUSB1", 0x0403), esp8266]), esp8266)

    def test_auto_accepts_supported_bridges_and_espressif(self):
        for vid, pid in ((0x10C4, 0xEA60), (0x1A86, 0x7523), (0x1A86, 0x55D4), (0x303A, 0x1001)):
            with self.subTest(vid=vid, pid=pid):
                candidate = port(vid=vid, pid=pid)
                self.assertIs(choose_port([candidate]), candidate)

    def test_auto_ignores_pico_and_unrelated_products_from_bridge_vendors(self):
        for vid, pid in ((0x2E8A, 0x0005), (0x10C4, 0x0001), (0x1A86, 0x0001)):
            with self.subTest(vid=vid, pid=pid):
                with self.assertRaisesRegex(DeploymentError, "Nenhum candidato ESP8266"):
                    choose_port([port(vid=vid, pid=pid)])

    def test_auto_never_picks_arbitrary_esp8266(self):
        with self.assertRaisesRegex(DeploymentError, "Mais de um"):
            choose_port([port(), port("/dev/ttyACM1")])
        with self.assertRaisesRegex(DeploymentError, "Nenhum candidato ESP8266"):
            choose_port([port("/dev/ttyUSB0", 0x0403)])

    def test_manual_port_can_lack_usb_metadata(self):
        self.assertEqual(choose_port([], "COM7").device, "COM7")


class DeploymentTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.firmware = self.root / "firmware"
        self.firmware.mkdir()
        (self.firmware / "main.py").write_bytes(b"import display\n")
        (self.firmware / "display.py").write_bytes(b"COLOR = 123\n")

    def install(self, fake):
        return deploy(port(), self.firmware, self.root / "backups", runner=fake, report=lambda _: None)

    def test_all_backups_precede_all_writes_and_reset_follows_verification(self):
        old = {"main.py": b"old main", "display.py": b"old display", "boot.py": b"old boot"}
        fake = FakeMpremote(old)
        backup = self.install(fake)
        first_write = next(i for i, event in enumerate(fake.events) if event[0] == "write")
        self.assertEqual({name for action, name in fake.events[:first_write] if action == "backup"}, set(old))
        soft_reset = fake.events.index(("soft-reset", None))
        self.assertLess(soft_reset, first_write)
        self.assertTrue(all(i < soft_reset for i, (action, _) in enumerate(fake.events) if action == "backup"))
        for name, contents in old.items():
            self.assertEqual((backup / name).read_bytes(), contents)
        self.assertEqual(fake.files["boot.py"], old["boot.py"])
        self.assertEqual(fake.events[-3:], [("write", "main.py"), ("verify", None), ("reset", None)])
        self.assertEqual(json.loads((backup / "manifest.json").read_text())["status"], "complete")

    def test_backup_failure_prevents_every_remote_write_and_redacts_process_output(self):
        fake = FakeMpremote({"main.py": b"old", "boot.py": b"old boot"}, fail_backup="main.py")
        with self.assertRaises(DeploymentError) as failure:
            self.install(fake)
        self.assertNotIn("secret", str(failure.exception))
        self.assertFalse(any(action in ("write", "soft-reset", "reset") for action, _ in fake.events))

    def test_rejects_esp32_and_pico_before_backup_or_write(self):
        for platform, machine in (
            ("esp32", "Generic ESP32 module with ESP32"),
            ("esp32", "Generic ESP32S3 module with ESP32S3"),
            ("rp2", "Raspberry Pi Pico W with RP2040"),
        ):
            with self.subTest(platform=platform, machine=machine):
                fake = FakeMpremote({}, platform=platform, machine=machine)
                with self.assertRaisesRegex(DeploymentError, "MicroPython em ESP8266"):
                    self.install(fake)
                self.assertEqual(fake.events, [("identify", None)])
        self.assertFalse((self.root / "backups").exists())

    def test_platform_alone_does_not_identify_esp8266(self):
        for chip in ("ESP32", "ESP32S3", "RP2040", "unknown board"):
            with self.subTest(chip=chip):
                fake = FakeMpremote({}, machine=f"Generic {chip} module with {chip}")
                with self.assertRaisesRegex(DeploymentError, "confirmar o modelo ESP8266"):
                    self.install(fake)
                self.assertEqual(fake.events, [("identify", None)])
        self.assertFalse((self.root / "backups").exists())

    def test_implementation_machine_also_rejects_incompatible_soc(self):
        fake = FakeMpremote({}, implementation_machine="Custom with ESP32S3")
        with self.assertRaisesRegex(DeploymentError, "incompatível com ESP8266"):
            self.install(fake)
        self.assertEqual(fake.events, [("identify", None)])

    def test_unknown_machine_is_not_assumed_esp8266_from_implementation_alone(self):
        fake = FakeMpremote({}, machine="unknown board", implementation_machine="ESP8266")
        with self.assertRaisesRegex(DeploymentError, "confirmar o modelo"):
            self.install(fake)
        self.assertEqual(fake.events, [("identify", None)])

    def test_soft_reset_or_missing_sha256_prevents_every_write(self):
        fake = FakeMpremote({"main.py": b"original"}, fail_prepare=True)
        with self.assertRaises(DeploymentError) as failure:
            self.install(fake)
        self.assertNotIn("secret", str(failure.exception))
        self.assertEqual(fake.events, [("identify", None), ("backup", "main.py"), ("soft-reset", None)])
        manifest_path = next((self.root / "backups").glob("*/manifest.json"))
        manifest = json.loads(manifest_path.read_text())
        self.assertEqual(manifest["failed_during"], "preparing")
        self.assertEqual(manifest["installed"], [])
        self.assertEqual((manifest_path.parent / "main.py").read_bytes(), b"original")

    def test_checksum_mismatch_prevents_reset_and_records_failure(self):
        fake = FakeMpremote({}, corrupt=True)
        with self.assertRaisesRegex(DeploymentError, "SHA-256"):
            self.install(fake)
        self.assertNotIn(("reset", None), fake.events)
        manifest = next((self.root / "backups").glob("*/manifest.json"))
        self.assertEqual(json.loads(manifest.read_text())["status"], "failed")


if __name__ == "__main__":
    unittest.main()
