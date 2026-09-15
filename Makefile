PYTHON ?= $(shell command -v python3 2>/dev/null || command -v python 2>/dev/null || echo python)
CONFIG ?= config/default.yaml
RUN_DIR ?=

.PHONY: test smoke phase1 validate lint format ai-sync ai-check ai-install

test:
	$(PYTHON) -m pytest -q

smoke:
	$(PYTHON) -m pytest tests/integration -q -m "integration and not slow"

phase1:
	fxhe-phase1 --config $(CONFIG) --profile smoke

validate:
	@if [ -z "$(RUN_DIR)" ]; then echo "RUN_DIR is required"; exit 1; fi
	fxhe-validate-run --run-dir $(RUN_DIR)

lint:
	ruff check src/ tests/

format:
	ruff format src/ tests/

ai-sync:
	$(PYTHON) scripts/sync_agent_docs.py --write

ai-check:
	$(PYTHON) scripts/sync_agent_docs.py --check
	$(PYTHON) scripts/validate_repo_skills.py

ai-install:
	$(PYTHON) scripts/install_repo_skills.py --mode auto
