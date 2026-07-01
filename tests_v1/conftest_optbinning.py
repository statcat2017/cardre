"""Test fixtures for optbinning batch tests.

Generates small Parquet datasets for unit testing.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import polars as pl
import pytest


FIXTURE_DIR = Path(__file__).parent / "fixtures"


@pytest.fixture(scope="session")
def binning_binary_small() -> pl.DataFrame:
    """~500 rows, 3 numeric variables, 2 categorical, binary target.

    Age (numeric): 18-80, roughly uniform.
    Income (numeric): 20k-150k, right-skewed.
    Months_on_book (numeric): 1-120, uniform.
    Employment (categorical): Employed, Self-employed, Unemployed, Retired.
    Region (categorical): North, South, East, West.
    Target: bad_flag (0/1), ~20% event rate.

    Good values: [0], bad values: [1].
    """
    import random

    random.seed(42)
    n = 500
    rows: list[dict[str, Any]] = []
    for _ in range(n):
        age = random.randint(18, 80)
        income = round(random.lognormvariate(10.8, 0.6), 0)
        mob = random.randint(1, 120)
        emp = random.choice(["Employed", "Self-employed", "Unemployed", "Retired"])
        region = random.choice(["North", "South", "East", "West"])
        # Higher age = lower bad rate, lower income = higher bad rate
        bad_prob = 0.3 - 0.002 * age + 0.000003 * income + (0.1 if emp == "Unemployed" else 0)
        bad_prob = max(0.01, min(0.8, bad_prob))
        bad_flag = 1 if random.random() < bad_prob else 0
        rows.append({
            "age": age,
            "income": income,
            "months_on_book": mob,
            "employment": emp,
            "region": region,
            "bad_flag": bad_flag,
        })
    return pl.DataFrame(rows)


@pytest.fixture(scope="session")
def binning_binary_categorical() -> pl.DataFrame:
    """High-cardinality categorical dataset. ~300 rows with 25+ categories."""
    import random

    random.seed(43)
    n = 300
    cats = [f"cat_{i}" for i in range(25)]
    rows = []
    for _ in range(n):
        cat = random.choice(cats)
        bad = 1 if random.random() < 0.15 else 0
        rows.append({"feature_cat": cat, "bad_flag": bad})
    return pl.DataFrame(rows)


@pytest.fixture(scope="session")
def binning_binary_special_codes() -> pl.DataFrame:
    """Dataset with special code values (-999, -99) in numeric columns."""
    import random

    random.seed(44)
    n = 400
    rows = []
    special_values = [-999, -99]
    for _ in range(n):
        score = random.choice([random.randint(300, 900)] + special_values)
        age = random.choice([random.randint(18, 80)] + special_values)
        bad = 1 if random.random() < 0.2 else 0
        rows.append({
            "bureau_score": score,
            "age": age,
            "bad_flag": bad,
        })
    return pl.DataFrame(rows)


@pytest.fixture(scope="session")
def binning_binary_missing() -> pl.DataFrame:
    """Dataset with null values in numeric and categorical columns."""
    import random

    random.seed(45)
    n = 400
    rows = []
    for _ in range(n):
        val = random.choice([random.randint(10, 100), None])
        cat = random.choice([None, "A", "B", "C", "D"])
        age = random.choice([random.randint(18, 80), None])
        bad = 1 if random.random() < 0.2 else 0
        rows.append({
            "score": val,
            "cat_col": cat,
            "age": age,
            "bad_flag": bad,
        })
    return pl.DataFrame(rows)
