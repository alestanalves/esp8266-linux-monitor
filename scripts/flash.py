#!/usr/bin/env python3
"""Install the TFT monitor on an ESP8266 NodeMCU running MicroPython, with backups.

Install dependencies with ``python -m pip install mpremote pyserial``.
Use ``python scripts/flash.py --list`` then ``--port auto`` or ``--port COM5``.
This copies Python files, never a base .bin image or an erase-flash operation.
Only ESP8266 is supported by the bundled NodeMCU display pin configuration.
Every overwritten file and any
existing boot.py are backed up before the first write. ``resume`` makes behavior
consistent across old/new mpremote versions. After backup, a soft reset releases
the previous application's heap before uploading. A final hardware reset runs main.py;
a raw-REPL soft reset alone can skip main.py.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import subprocess
import sys
from typing import Callable, Iterable


PROJECT_ROOT = Path(__file__).resolve().parents[1]
ESPRESSIF_VID = 0x303A
ESP8266_USB_BRIDGES = {(0x10C4, 0xEA60), (0x1A86, 0x7523), (0x1A86, 0x55D4)}
RESULT_MARKER = "__TFT_INSTALL_INFO__"


class DeploymentError(Exception):
    """An actionable installation failure, without a Python traceback."""


def discover_ports() -> list:
    try:
        from serial.tools import list_ports
    except ImportError as exc:
        raise DeploymentError(
            "Falta pyserial. Instale: python -m pip install mpremote pyserial"
        ) from exc
    return sorted(list_ports.comports(), key=lambda port: port.device)


def choose_port(ports: Iterable, requested: str = "auto"):
    ports = list(ports)
    if requested != "auto":
        for port in ports:
            if port.device == requested:
                return port
        # A manually provided serial path can exist without USB metadata.
        from types import SimpleNamespace

        return SimpleNamespace(device=requested, serial_number=None)
    # A bridge ID is only a candidate: it also appears on other products. Check
    # the running interpreter and SoC before writing anything to the board.
    candidates = [
        port for port in ports
        if port.vid == ESPRESSIF_VID or (port.vid, port.pid) in ESP8266_USB_BRIDGES
    ]
    if not candidates:
        raise DeploymentError(
            "Nenhum candidato ESP8266 USB serial encontrado (Espressif, CP210x, "
            "CH340 ou CH9102). Confira o cabo USB de "
            "dados, MicroPython e a conexão USB com este sistema. Em WSL, o USB "
            "precisa ser encaminhado ou execute este script no Windows. "
            "Use --list e --port para escolher uma porta manualmente."
        )
    if len(candidates) != 1:
        names = ", ".join(port.device for port in candidates)
        raise DeploymentError(
            f"Mais de um candidato ESP8266 encontrado: {names}. "
            "Escolha explicitamente com --port."
        )
    return candidates[0]


class Mpremote:
    def __init__(self, port: str, runner: Callable = subprocess.run):
        self.port = port
        self.runner = runner

    def run(self, *args: str, action: str) -> str:
        command = [
            sys.executable, "-m", "mpremote", "connect", f"port:{self.port}",
        ]
        if sys.platform == "win32":
            # Some Windows USB-UART drivers pulse reset when the port opens.
            # Let boot finish before mpremote sends Ctrl-C / enters raw REPL.
            command += ["sleep", "2"]
        command += ["resume", *args]
        try:
            result = self.runner(
                command, capture_output=True, text=True, timeout=60, check=False
            )
        except subprocess.TimeoutExpired as exc:
            raise DeploymentError(f"Tempo esgotado ao {action} em {self.port}.") from exc
        except OSError as exc:
            raise DeploymentError(f"Não foi possível iniciar mpremote para {action}.") from exc
        if result.returncode:
            # Device stdout/stderr can contain existing application secrets.
            raise DeploymentError(
                f"mpremote falhou ao {action} em {self.port} "
                f"(código {result.returncode}). Feche outros monitores seriais e "
                "o serviço deste projeto; confira as permissões USB e MicroPython."
            )
        return result.stdout

    def json_exec(self, code: str, *, action: str):
        output = self.run("exec", code, action=action)
        for line in reversed(output.splitlines()):
            if line.startswith(RESULT_MARKER):
                try:
                    return json.loads(line[len(RESULT_MARKER):])
                except ValueError:
                    break
        raise DeploymentError(f"Resposta inválida do ESP8266 ao {action}.")


def validate_device(info: dict) -> None:
    if info.get("implementation") != "micropython" or info.get("platform") != "esp8266":
        raise DeploymentError("A porta selecionada não executa MicroPython em ESP8266.")
    machine = str(info.get("machine", "")).upper()
    implementation_machine = str(info.get("implementation_machine", "")).upper()
    identities = f"{machine} {implementation_machine}"
    if "ESP8266" not in machine:
        raise DeploymentError("Não foi possível confirmar o modelo ESP8266 pelo MicroPython.")
    # USB bridge IDs are shared across boards. Reject inconsistent identities
    # instead of installing this pin configuration on the earlier ESP32/Pico.
    if re.search(r"ESP32|RP2[0-9]+|RASPBERRY", identities):
        raise DeploymentError(
            "A identidade da placa é incompatível com ESP8266 NodeMCU; "
            "instalação cancelada antes de gravar."
        )


def firmware_files(directory: Path) -> list[Path]:
    files = sorted(directory.glob("*.py"), key=lambda path: (path.name == "main.py", path.name))
    if not files or not any(path.name == "main.py" for path in files):
        raise DeploymentError(f"main.py não encontrado em {directory}.")
    for path in files:
        if not path.is_file() or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*\.py", path.name):
            raise DeploymentError(f"Nome de arquivo de firmware inválido: {path.name}")
    return files


def deploy(
    port,
    firmware_dir: Path = PROJECT_ROOT / "firmware",
    backup_root: Path = PROJECT_ROOT / "backups",
    *,
    runner: Callable = subprocess.run,
    report: Callable[[str], None] = print,
) -> Path:
    files = firmware_files(firmware_dir)
    names = sorted({path.name for path in files} | {"boot.py"})
    remote = Mpremote(port.device, runner)
    # resume + exec stops the running program without relying on auto-soft-reset.
    info = remote.json_exec(
        "import sys as _sys, os as _os, json as _json\n"
        "_existing = {}\n"
        f"for _name in {names!r}:\n"
        " if _name in _os.listdir('/'):\n"
        "  _stat = _os.stat('/' + _name)\n"
        "  _existing[_name] = [_stat[0], _stat[6]]\n"
        f"print({RESULT_MARKER!r} + _json.dumps({{"
        "'implementation': _sys.implementation.name, 'platform': _sys.platform, "
        "'implementation_machine': getattr(_sys.implementation, '_machine', ''), "
        "'machine': _os.uname().machine, 'existing': _existing}))",
        action="identificar MicroPython e os arquivos existentes",
    )
    validate_device(info)
    existing = info.get("existing", {})
    for name, metadata in existing.items():
        if metadata[0] & 0xF000 != 0x8000:
            raise DeploymentError(f"/{name} existe no ESP8266, mas não é arquivo regular.")

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    label = getattr(port, "serial_number", None) or port.device
    label = re.sub(r"[^A-Za-z0-9_.-]", "_", str(label))[:64]
    backup_dir = backup_root / f"{stamp}-{label}"
    backup_dir.mkdir(parents=True, mode=0o700)
    manifest = {
        "created_utc": stamp,
        "port": port.device,
        "machine": info["machine"],
        "status": "backing_up",
        "backed_up": [],
        "previously_absent": [path.name for path in files if path.name not in existing],
        "installed": [],
        "source_sha256": {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in files},
    }

    def save_manifest():
        (backup_dir / "manifest.json").write_text(
            json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )

    save_manifest()
    report(f"ESP8266 identificado: {info['machine']} ({port.device}).")
    report(f"Backup local: {backup_dir}")
    try:
        # Finish *all* backups before writing even the first application file.
        for name, metadata in sorted(existing.items()):
            local = backup_dir / name
            remote.run("fs", "cp", f":/{name}", str(local), action=f"salvar backup de {name}")
            if not local.is_file() or local.stat().st_size != metadata[1]:
                raise DeploymentError(f"Backup incompleto de {name}; nada foi instalado.")
            manifest["backed_up"].append(name)
            save_manifest()
        manifest["status"] = "preparing"
        save_manifest()
        # Imported modules and the framebuffer survive separate mpremote calls
        # with resume. Clear them only after every original file is backed up.
        # Check SHA-256 support now, so an incompatible base image causes no writes.
        remote.run(
            "soft-reset", "exec",
            "import gc; gc.collect(); import hashlib; hashlib.sha256()",
            action="liberar memória e conferir SHA-256 no ESP8266",
        )
        manifest["status"] = "installing"
        save_manifest()
        for path in files:
            remote.run("fs", "cp", str(path.resolve()), f":/{path.name}", action=f"instalar {path.name}")
            manifest["installed"].append(path.name)
            save_manifest()
        # Verify bytes on the actual device before calling the hardware reset.
        hashes = remote.json_exec(
            "import gc as _gc\n"
            "_gc.collect()\n"
            "import hashlib as _hashlib, binascii as _binascii, json as _json\n"
            "_hashes = {}\n"
            f"for _name in {[path.name for path in files]!r}:\n"
            " _hash = _hashlib.sha256()\n"
            " with open('/' + _name, 'rb') as _file:\n"
            "  while True:\n"
            "   _chunk = _file.read(1024)\n"
            "   if not _chunk: break\n"
            "   _hash.update(_chunk)\n"
            " _hashes[_name] = _binascii.hexlify(_hash.digest()).decode()\n"
            f"print({RESULT_MARKER!r} + _json.dumps(_hashes))",
            action="verificar os arquivos instalados",
        )
        if hashes != manifest["source_sha256"]:
            raise DeploymentError("A verificação SHA-256 dos arquivos instalados falhou.")
        manifest["status"] = "verified"
        save_manifest()
        # Match mpremote's reset shortcut: allow its command acknowledgement to
        # reach the host before reset. USB-UART bridges stay connected while
        # the MCU restarts; --no-follow also avoids waiting on the new main.py.
        remote.run(
            "exec", "--no-follow", "import time, machine; time.sleep_ms(100); machine.reset()",
            action="reiniciar o ESP8266 para executar main.py",
        )
        manifest["status"] = "complete"
        save_manifest()
    except (DeploymentError, OSError, KeyboardInterrupt) as exc:
        previous_status = manifest["status"]
        manifest["status"] = "failed"
        manifest["failed_during"] = previous_status
        try:
            save_manifest()
        except OSError:
            pass
        details = str(exc) if not isinstance(exc, KeyboardInterrupt) else "Operação interrompida."
        raise DeploymentError(
            f"{details} Instalação incompleta; backup e estado em {backup_dir}. "
            "Corrija o problema e execute novamente."
        ) from exc
    report(f"{len(files)} arquivos instalados e verificados. ESP8266 reiniciado.")
    return backup_dir


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Instala o monitor TFT no ESP8266 NodeMCU com backup automático.")
    parser.add_argument("--list", action="store_true", help="lista portas seriais e sai")
    parser.add_argument("--port", default="auto", help="auto, /dev/ttyUSB0, COM4 etc. (padrão: auto)")
    parser.add_argument("--firmware-dir", type=Path, default=PROJECT_ROOT / "firmware")
    parser.add_argument("--backup-dir", type=Path, default=PROJECT_ROOT / "backups")
    args = parser.parse_args(argv)
    try:
        ports = discover_ports()
        if args.list:
            if not ports:
                print("Nenhuma porta serial encontrada neste sistema.")
            for port in ports:
                usb = f"{port.vid:04x}:{port.pid:04x}" if port.vid is not None and port.pid is not None else "sem VID/PID"
                print(f"{port.device}\t{usb}\t{port.description}")
            return 0
        port = choose_port(ports, args.port)
        if importlib.util.find_spec("mpremote") is None:
            raise DeploymentError("Falta mpremote. Instale: python -m pip install mpremote pyserial")
        deploy(port, args.firmware_dir.resolve(), args.backup_dir.resolve())
        return 0
    except (DeploymentError, OSError) as exc:
        print(f"Erro: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("Instalação interrompida.", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
