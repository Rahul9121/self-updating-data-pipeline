PYTHON ?= python
VENV ?= .venv
PIP := $(VENV)/bin/pip
PY := $(VENV)/bin/python

ifeq ($(OS),Windows_NT)
PIP := $(VENV)\Scripts\pip.exe
PY := $(VENV)\Scripts\python.exe
endif

.PHONY: setup run test site lint clean

setup:
	$(PYTHON) -m venv $(VENV)
	$(PIP) install -r requirements.txt

run:
	$(PY) -m pipeline.run

test:
	$(PY) -m pytest tests -q

site:
	$(PY) -m pipeline.build_site

lint:
	$(PY) -m ruff check src tests

clean:
	rm -rf $(VENV) .pytest_cache .ruff_cache data/*.db data/*.parquet site/dist
