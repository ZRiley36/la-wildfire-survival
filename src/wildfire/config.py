"""Paths and the YAML config, shared by every step."""
from functools import lru_cache
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
RAW = ROOT / "data/raw"
INTERIM = ROOT / "data/interim"
PROCESSED = ROOT / "data/processed"
DOCS = ROOT / "docs"
FIGURES = DOCS / "figures"


@lru_cache
def cfg(path=ROOT / "config/config.yaml"):
    with open(path) as f:
        return yaml.safe_load(f)


def interim(name):
    return INTERIM / f"{name}.parquet"
