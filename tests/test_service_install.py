"""Exercise installer transactions without root, package downloads or systemd.

Only the root guard and absolute system paths are redirected in a temporary
copy. Account, Python package and service commands are fakes; file operations
are real, so replacement/preservation of installed files is checked on disk.
"""

import os
from pathlib import Path
import shutil
import subprocess

import pytest


PROJECT = Path(__file__).resolve().parents[1]


@pytest.fixture
def installation(tmp_path):
    project = tmp_path / "project"
    root = tmp_path / "root"
    commands = tmp_path / "commands"
    log = tmp_path / "commands.log"
    commands.mkdir()
    (project / "scripts").mkdir(parents=True)
    (root / "run/systemd/system").mkdir(parents=True)
    shutil.copytree(PROJECT / "systemd", project / "systemd")
    for name in ("install-service.sh", "install-cachyos.sh", "uninstall-service.sh"):
        source = (PROJECT / "scripts" / name).read_text()
        source = source.replace("${EUID}", "0")
        for prefix in ("/opt/", "/etc/", "/run/"):
            source = source.replace(prefix, str(root) + prefix)
        (project / "scripts" / name).write_text(source)

    def executable(name, body):
        path = commands / name
        path.write_text("#!/bin/bash\nset -eu\n" + body)
        path.chmod(0o755)

    for name in ("systemctl", "udevadm", "groupadd", "useradd", "pacman"):
        executable(name, 'printf "%s %s\\n" "${0##*/}" "$*" >> "$TEST_LOG"\n')
    executable("getent", "exit 1\n")
    executable("id", "exit 1\n")
    executable("python3", r'''
printf 'python3 %s\n' "$*" >> "$TEST_LOG"
if [[ $1 == -c ]]; then
    exit "${FAIL_PREFLIGHT:-0}"
fi
[[ $1 == -m && $2 == venv ]]
mkdir -p "$3/bin"
cat > "$3/bin/python" <<'PYTHON'
#!/bin/bash
set -eu
printf 'venv-python %s\n' "$*" >> "$TEST_LOG"
if [[ $1 == -m && $2 == pip ]]; then
    exit "${FAIL_PIP:-0}"
fi
PYTHON
cat > "$3/bin/tft-monitor" <<'MONITOR'
#!/bin/bash
printf '1.0.0\n'
MONITOR
chmod +x "$3/bin/python" "$3/bin/tft-monitor"
''')
    environment = {
        **os.environ,
        "PATH": str(commands) + os.pathsep + os.environ["PATH"],
        "TEST_LOG": str(log),
    }

    class Installation:
        def __init__(self):
            self.root = root
            self.base = root / "opt/tft-monitor"
            self.config = root / "etc/tft-monitor.env"

        def run(self, script="install-service.sh", *arguments, **env):
            return subprocess.run(
                ["bash", str(project / "scripts" / script), *arguments],
                env={**environment, **env}, capture_output=True, text=True,
                timeout=10,
            )

        def commands(self):
            return log.read_text() if log.exists() else ""

        def clear_log(self):
            log.write_text("")

    return Installation()


def test_first_install_enables_boot_and_udev_access(installation):
    result = installation.run()
    assert result.returncode == 0, result.stderr
    environment = installation.base / "venv"
    assert environment.is_symlink()
    assert (environment / "bin/tft-monitor").is_file()
    assert environment.resolve().stat().st_mode & 0o777 == 0o755
    assert "TFT_PORT=auto" in installation.config.read_text()
    commands = installation.commands()
    assert commands.index("venv-python -m pip install") < commands.index("systemctl stop")
    assert "systemctl enable --now tft-monitor.service" in commands
    rules = installation.root / "etc/udev/rules.d/70-tft-monitor.rules"
    assert 'GROUP="tft-monitor", MODE="0660"' in rules.read_text()
    assert 'ATTRS{idVendor}=="1a86", ATTRS{idProduct}=="7523"' in rules.read_text()


def test_upgrade_replaces_legacy_directory_and_preserves_configuration(installation):
    legacy = installation.base / "venv"
    legacy.mkdir(parents=True)
    (legacy / "original.txt").write_text("old environment")
    installation.config.parent.mkdir(parents=True)
    installation.config.write_text("TFT_PORT=/dev/serial/by-id/custom\n")
    result = installation.run()
    assert result.returncode == 0, result.stderr
    assert legacy.is_symlink()
    assert installation.config.read_text() == "TFT_PORT=/dev/serial/by-id/custom\n"
    saved = list((installation.base / "venvs").glob("legacy-*/original.txt"))
    assert len(saved) == 1
    assert saved[0].read_text() == "old environment"


def test_reinstall_builds_new_environment_even_at_same_package_version(installation):
    assert installation.run().returncode == 0
    original = (installation.base / "venv").resolve()
    installation.config.write_text("TFT_INTERVAL=2\n")
    installation.clear_log()
    result = installation.run()
    assert result.returncode == 0, result.stderr
    assert (installation.base / "venv").resolve() != original
    assert original.is_dir()
    assert installation.config.read_text() == "TFT_INTERVAL=2\n"
    assert "venv-python -m pip install" in installation.commands()


@pytest.mark.parametrize("failure", ["FAIL_PREFLIGHT", "FAIL_PIP"])
def test_failed_preparation_keeps_existing_service_and_environment(installation, failure):
    assert installation.run().returncode == 0
    original = (installation.base / "venv").resolve()
    environments = list((installation.base / "venvs").iterdir())
    installation.clear_log()
    result = installation.run(**{failure: "1"})
    assert result.returncode != 0
    assert (installation.base / "venv").resolve() == original
    assert list((installation.base / "venvs").iterdir()) == environments
    assert "systemctl " not in installation.commands()
    assert "udevadm " not in installation.commands()


def test_unsupported_init_fails_before_mutations(installation):
    (installation.root / "run/systemd/system").rmdir()
    result = installation.run()
    assert result.returncode != 0
    assert "systemd ativo" in result.stderr
    assert not installation.base.exists()
    assert installation.commands() == ""


def test_cachyos_wrapper_installs_dependencies_then_service(installation):
    result = installation.run("install-cachyos.sh")
    assert result.returncode == 0, result.stderr
    commands = installation.commands()
    assert "pacman -S --needed python python-pip base-devel" in commands
    assert commands.index("pacman ") < commands.index("venv-python -m pip install")
    assert "systemctl enable --now tft-monitor.service" in commands


@pytest.mark.parametrize("purge", [False, True])
def test_uninstall_removes_service_and_application_with_optional_config(installation, purge):
    assert installation.run().returncode == 0
    installation.clear_log()
    arguments = ("--purge-config",) if purge else ()
    result = installation.run("uninstall-service.sh", *arguments)
    assert result.returncode == 0, result.stderr
    assert not installation.base.exists()
    assert not (installation.root / "etc/systemd/system/tft-monitor.service").exists()
    assert not (installation.root / "etc/udev/rules.d/70-tft-monitor.rules").exists()
    assert installation.config.exists() is not purge
    assert "systemctl disable --now tft-monitor.service" in installation.commands()
