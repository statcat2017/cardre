"""Pytest fixtures for the golden comparison test suite.

Loads frozen R scorecard reference fixtures as Polars DataFrames and
dicts.  Also provides the path to the UCI-format ``german.data`` used
by ``ImportGermanCreditNode``.
"""

from __future__ import annotations

from pathlib import Path

import polars as pl
import pytest

from tests.golden_scorecard.helpers import (
    GOLDEN_DIR,
    load_golden_csvs,
    load_golden_jsons,
    load_golden_metadata,
)


@pytest.fixture(scope="session")
def golden_csv() -> dict[str, pl.DataFrame]:
    """All CSV golden fixtures keyed by stem name."""
    return load_golden_csvs()


@pytest.fixture(scope="session")
def golden_json() -> dict[str, object]:
    """All JSON golden fixtures keyed by stem name."""
    return load_golden_jsons()


@pytest.fixture(scope="session")
def golden_metadata() -> dict:
    """The ``metadata.json`` dict."""
    return load_golden_metadata()


@pytest.fixture(scope="session")
def golden_raw_data() -> Path:
    """Path to the UCI-format ``german.data`` fixture file."""
    return GOLDEN_DIR / "german.data"
