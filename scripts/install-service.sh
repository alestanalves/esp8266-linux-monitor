#!/usr/bin/env bash
set -euo pipefail
PROJECT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
INSTALL_DIR=/opt/tft-monitor
if [[ $# -gt 0 ]]; then
    printf 'Uso: sudo bash scripts/install-service.sh\nInstala ou atualiza o agente e habilita o envio por USB em todo boot.\n'
    [[ $# -eq 1 && $1 == --help ]]
    exit
fi
if [[ ${EUID} -ne 0 ]]; then
    printf 'Execute com sudo: sudo bash scripts/install-service.sh\n' >&2
    exit 1
fi
umask 022
if ! command -v systemctl >/dev/null || [[ ! -d /run/systemd/system ]]; then
    printf 'Este instalador requer Linux com systemd ativo. Em outros sistemas, use tft-monitor manualmente.\n' >&2
    exit 1
fi
for tool in python3 udevadm getent groupadd useradd install mktemp; do
    if ! command -v "$tool" >/dev/null; then
        printf 'Comando necessario nao encontrado: %s\n' "$tool" >&2
        exit 1
    fi
done
if ! python3 -c 'import sys, venv; assert sys.version_info >= (3, 10)' >/dev/null 2>&1; then
    printf 'Requer Python 3.10+ com venv. CachyOS: use install-cachyos.sh. Debian/Ubuntu: instale python3-venv.\n' >&2
    exit 1
fi

# Build a fresh environment before touching the running service. This also
# replaces an outdated venv after a system Python upgrade and installs local
# changes even when the project version number has not changed.
install -d -m 0755 "$INSTALL_DIR/venvs"
CANDIDATE="$(mktemp -d "$INSTALL_DIR/venvs/venv.XXXXXXXX")"
NEXT_LINK="$INSTALL_DIR/.venv-next.$$"
cleanup() {
    rm -f -- "$NEXT_LINK"
    if [[ -n "$CANDIDATE" ]]; then
        rm -rf -- "$CANDIDATE"
    fi
}
trap cleanup EXIT
chmod 0755 "$CANDIDATE"
if ! python3 -m venv "$CANDIDATE"; then
    printf 'Falha ao criar venv. Instale python3-venv (Debian/Ubuntu) ou python-pip (CachyOS/Arch).\n' >&2
    exit 1
fi
"$CANDIDATE/bin/python" -m pip install --disable-pip-version-check "$PROJECT_DIR"
"$CANDIDATE/bin/python" -c 'import psutil, serial, tft_monitor.cli'
"$CANDIDATE/bin/tft-monitor" --version

getent group tft-monitor >/dev/null || groupadd --system tft-monitor
id tft-monitor >/dev/null 2>&1 || useradd --system --gid tft-monitor --no-create-home --home-dir /nonexistent --shell /bin/false tft-monitor
install -d -m 0755 /etc/systemd/system /etc/udev/rules.d
install -m 0644 "$PROJECT_DIR/systemd/tft-monitor.service" /etc/systemd/system/tft-monitor.service
if [[ ! -f /etc/tft-monitor.env ]]; then
    install -m 0644 "$PROJECT_DIR/systemd/tft-monitor.env" /etc/tft-monitor.env
fi
install -m 0644 "$PROJECT_DIR/systemd/70-tft-monitor.rules" /etc/udev/rules.d/70-tft-monitor.rules

# Reload also makes the newly installed unit available on a first installation.
systemctl daemon-reload
# Preserve the original directory used by earlier releases. New installations
# use a symlink, so switching to a fully built environment is atomic.
systemctl stop tft-monitor.service
if [[ -d "$INSTALL_DIR/venv" && ! -L "$INSTALL_DIR/venv" ]]; then
    mv -- "$INSTALL_DIR/venv" "$INSTALL_DIR/venvs/legacy-$(date +%Y%m%dT%H%M%S)-$$"
fi
ln -s -- "$CANDIDATE" "$NEXT_LINK"
mv -Tf -- "$NEXT_LINK" "$INSTALL_DIR/venv"
CANDIDATE=""
udevadm control --reload-rules
udevadm trigger --subsystem-match=tty --action=change
systemctl enable --now tft-monitor.service
printf '\nServico habilitado e iniciado: envia dados em todo boot, mesmo sem login.\n'
printf 'Se o USB estiver ausente, o agente aguarda e reconecta automaticamente.\n'
printf 'Configuracao preservada: /etc/tft-monitor.env\n'
printf 'Logs: journalctl -u tft-monitor -f\n'
printf 'Apos atualizar a versao do Python do sistema, execute este instalador novamente.\n'
