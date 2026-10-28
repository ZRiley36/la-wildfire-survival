PY := .venv/bin/python

.PHONY: all setup download inventory pipeline test

all: pipeline test

setup:
	python3 -m venv .venv
	$(PY) -m pip install -r requirements.txt
	$(PY) -m pip install -e .

download:
	$(PY) -m wildfire.download

inventory:
	$(PY) -m wildfire.inventory > docs/data_inventory.json

pipeline:
	$(PY) -m wildfire

test:
	$(PY) -m pytest -q
