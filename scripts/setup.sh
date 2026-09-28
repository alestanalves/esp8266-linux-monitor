#!/usr/bin/env bash
set -euo pipefail
PROJECT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_DIR"
if ! command -v python3 >/dev/null; then
    printf 'Instale Python 3.10 ou mais recente. Consulte as dependencias da sua distribuicao no README.\n' >&2
    exit 1
fi
python3 -c 'import sys; sys.exit("Este projeto requer Python 3.10 ou mais recente") if sys.version_info < (3, 10) else None'
if ! python3 -m venv --help >/dev/null 2>&1; then
    printf 'Instale o suporte a venv do Python (python3-venv no Debian/Ubuntu).\n' >&2
    exit 1
fi
python3 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -e '.[flash,dev]'
printf '\nPronto. Teste: .venv/bin/tft-monitor --once\n'
printf 'Listar placas: .venv/bin/python scripts/flash.py --list\n'
