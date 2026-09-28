#!/usr/bin/env bash
set -euo pipefail
PURGE_CONFIG=false
case "${1:-}" in
    --help)
        printf 'Uso: sudo bash scripts/uninstall-service.sh [--purge-config]\nRemove o agente; preserva /etc/tft-monitor.env sem --purge-config.\n'
        exit 0 ;;
    --purge-config) PURGE_CONFIG=true ;;
    '') ;;
    *) printf 'Opcao desconhecida. Use --help.\n' >&2; exit 2 ;;
esac
if [[ $# -gt 1 ]]; then
    printf 'Use --help para ver as opcoes.\n' >&2
    exit 2
fi
if [[ ${EUID} -ne 0 ]]; then
    printf 'Execute com sudo: sudo bash scripts/uninstall-service.sh\n' >&2
    exit 1
fi
if ! command -v systemctl >/dev/null || [[ ! -d /run/systemd/system ]]; then
    printf 'Este desinstalador requer Linux com systemd ativo.\n' >&2
    exit 1
fi
if [[ -f /etc/systemd/system/tft-monitor.service ]]; then
    systemctl disable --now tft-monitor.service
fi
rm -f -- /etc/systemd/system/tft-monitor.service /etc/udev/rules.d/70-tft-monitor.rules
rm -rf -- /opt/tft-monitor
if [[ $PURGE_CONFIG == true ]]; then
    rm -f -- /etc/tft-monitor.env
fi
systemctl daemon-reload
udevadm control --reload-rules
udevadm trigger --subsystem-match=tty --action=change
printf 'Agente removido. O usuario/grupo tft-monitor foram preservados para reinstalacao.\n'
if [[ $PURGE_CONFIG == false ]]; then
    printf 'Configuracao preservada: /etc/tft-monitor.env\n'
fi
