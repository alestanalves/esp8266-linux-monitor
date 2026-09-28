#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
if [[ $# -gt 0 ]]; then
    printf 'Uso: sudo bash scripts/install-cachyos.sh\nInstala dependencias e habilita o agente USB no boot do CachyOS/Arch.\n'
    [[ $# -eq 1 && $1 == --help ]]
    exit
fi
if [[ ${EUID} -ne 0 ]]; then
    printf 'Execute com sudo: sudo bash scripts/install-cachyos.sh\n' >&2
    exit 1
fi
if ! command -v pacman >/dev/null || ! command -v systemctl >/dev/null || [[ ! -d /run/systemd/system ]]; then
    printf 'Este script requer CachyOS/Arch com pacman e systemd ativo.\n' >&2
    printf 'Em outros Linux com systemd, use scripts/install-service.sh.\n' >&2
    exit 1
fi
printf 'Instalando dependencias do agente. O pacman pedira confirmacao se necessario.\n'
# Do not refresh the package database alone (-Sy), which can cause partial
# upgrades on Arch. The user's normal system update remains separate.
pacman -S --needed python python-pip base-devel
exec bash "$SCRIPT_DIR/install-service.sh"
