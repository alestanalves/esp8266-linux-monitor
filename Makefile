.PHONY: setup test run dump flash ports service
PYTHON = .venv/bin/python
PORT ?= auto

setup:
	bash scripts/setup.sh

test:
	$(PYTHON) -m pytest -q

run:
	.venv/bin/tft-monitor --port $(PORT)

dump:
	.venv/bin/tft-monitor --once

flash:
	$(PYTHON) scripts/flash.py --port $(PORT)

ports:
	$(PYTHON) scripts/flash.py --list

service:
	sudo bash scripts/install-service.sh
