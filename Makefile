.PHONY: all test lint fmt up down ps seed analyze audit serve help

PYTHON ?= uv run python
PYTEST ?= uv run pytest
RUFF   ?= uv run ruff

COMPOSE ?= $(shell which podman-compose 2>/dev/null || which docker-compose 2>/dev/null || echo "docker compose")

help:
	@echo "hermes-ai-midas Makefile targets:"
	@echo "  make test             - Run complete offline test suite (151+ tests)"
	@echo "  make lint             - Run ruff static analysis"
	@echo "  make fmt              - Format code with ruff"
	@echo "  make analyze SCRIPT=x - Analyze a PySpark script with AST Inspector"
	@echo "  make calculate        - Run FinOps pricing calculator"
	@echo "  make serve            - Run Airflow Webhook FastAPI server on :8000"
	@echo "  make audit            - Run proactive Cron Auditor over workloads"
	@echo "  make up               - Bring up local emulation container topology"
	@echo "  make down             - Stop container topology"
	@echo "  make ps               - Status of containers"

test:
	$(PYTEST) -v

lint:
	$(RUFF) check

fmt:
	$(RUFF) format
	$(RUFF) check --fix

analyze:
	$(PYTHON) -m hermes_midas.cli analyze --script $(if $(SCRIPT),$(SCRIPT),workloads/glue/customer360_elt.py)

calculate:
	$(PYTHON) -m hermes_midas.cli calculate --engine $(if $(ENGINE),$(ENGINE),glue) --duration-secs $(if $(SECS),$(SECS),3600) --units $(if $(UNITS),$(UNITS),10)

serve:
	$(PYTHON) -m hermes_midas.cli serve --port 8000 --host 0.0.0.0

audit:
	$(PYTHON) -m hermes_midas.cli audit --repo .

up:
	$(COMPOSE) -f compose.yaml up -d

down:
	$(COMPOSE) -f compose.yaml down

ps:
	$(COMPOSE) -f compose.yaml ps
