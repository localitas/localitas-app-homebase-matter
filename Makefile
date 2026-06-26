VENV := venv
PYTHON := $(VENV)/bin/python
PIP := $(VENV)/bin/pip
PORT ?= 9222
STORAGE ?= $(HOME)/.localitas/homebase/matter

.PHONY: help venv install dev stop test lint clean

help:
	@echo "homebase-matter — Matter sidecar for Localitas Homebase"
	@echo ""
	@echo "  make install   install dependencies into venv"
	@echo "  make dev       run sidecar natively on port $(PORT)"
	@echo "  make stop      kill running sidecar"
	@echo "  make test      run tests"
	@echo "  make lint      run gofmt equivalent (ruff + pyright stub)"

venv:
	@python3 -m venv $(VENV)

install: venv
	@$(PIP) install -q --upgrade pip
	@$(PIP) install -q -r requirements.txt
	@echo "✅ dependencies installed"

dev: install
	@mkdir -p $(STORAGE) $(HOME)/.localitas/logs/homebase-matter
	@$(PYTHON) main.py --listen :$(PORT) --storage $(STORAGE)

stop:
	@-pkill -f "homebase-matter.*main.py" 2>/dev/null || true
	@-lsof -ti:$(PORT) | xargs -r kill -9 2>/dev/null || true
	@echo "✅ stopped"

test: install
	@$(VENV)/bin/pytest test_app.py -v

lint: install
	@$(VENV)/bin/python -m py_compile main.py app.py matter.py routes.py
	@echo "✅ syntax ok"

clean:
	@rm -rf $(VENV) __pycache__ .pytest_cache *.pyc
