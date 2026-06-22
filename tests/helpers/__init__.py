"""Shared test helpers for the Cardre test suite.

Use these instead of redefining helpers in each test file, and instead of
importing helpers from other test modules (which creates fragile import chains).
"""

from __future__ import annotations

import io
import json
import tempfile
from pathlib import Path

import numpy as np
import polars as pl

from cardre.artifacts import write_json_artifact, write_parquet_artifact
from cardre.audit import (
    ArtifactRef,
    json_logical_hash,
    physical_hash,
    relative_path,
    table_logical_hash,
)
from cardre.store import ProjectStore

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SAMPLE_GERMAN_CREDIT_LINES = """A11 6 A34 A43 1169 A65 A75 4 A93 A101 4 A121 67 A143 A152 2 A173 1 A192 A201 1
A12 24 A32 A43 5951 A61 A73 2 A92 A101 4 A121 22 A142 A152 2 A173 1 A191 A201 2
""".strip().split("\n")


# ---------------------------------------------------------------------------
# Store helpers
# ---------------------------------------------------------------------------


def make_store() -> tuple[ProjectStore, Path]:
    """Create an isolated ProjectStore in a temp directory."""
    tmp = Path(tempfile.mkdtemp())
    store = ProjectStore(tmp / "test.cardre")
    store.initialize()
    return store, tmp


def make_sample_german_credit_file(tmp: Path) -> Path:
    """Write a small German Credit fixture file (2 rows, .data format)."""
    p = tmp / "german.data"
    p.write_text("\n".join(SAMPLE_GERMAN_CREDIT_LINES))
    return p


def make_sample_german_credit_csv(tmp: Path) -> Path:
    """Write a small German Credit fixture as CSV with header (2 rows)."""
    columns = [
        "checking_account_status", "duration_months", "credit_history", "purpose",
        "credit_amount", "savings_account_bonds", "present_employment_since",
        "installment_rate_percent_disposable_income", "personal_status_sex",
        "other_debtors_guarantors", "present_residence_since", "property",
        "age_years", "other_installment_plans", "housing",
        "existing_credits_at_bank", "job", "people_liable_maintenance",
        "telephone", "foreign_worker", "credit_risk_class",
    ]
    header = ",".join(columns)
    rows = [",".join(line.split()) for line in SAMPLE_GERMAN_CREDIT_LINES]
    p = tmp / "german_credit.csv"
    p.write_text("\n".join([header] + rows))
    return p


def make_large_german_credit_csv(tmp: Path) -> Path:
    """~100-row German Credit CSV suitable for scorecard pathway E2E tests."""
    good = "A11 6 A34 A43 1169 A65 A75 4 A93 A101 4 A121 67 A143 A152 2 A173 1 A192 A201 1"
    bad = "A12 24 A32 A43 5951 A61 A73 2 A92 A101 4 A121 22 A142 A152 2 A173 1 A191 A201 2"
    columns = [
        "checking_account_status", "duration_months", "credit_history", "purpose",
        "credit_amount", "savings_account_bonds", "present_employment_since",
        "installment_rate_percent_disposable_income", "personal_status_sex",
        "other_debtors_guarantors", "present_residence_since", "property",
        "age_years", "other_installment_plans", "housing",
        "existing_credits_at_bank", "job", "people_liable_maintenance",
        "telephone", "foreign_worker", "credit_risk_class",
    ]
    lines = [";".join(columns)]
    for i in range(50):
        parts_g = good.split()
        parts_g[0] = f"A{i % 11 + 11}"
        parts_g[1] = str(6 + (i % 48))
        parts_g[4] = str(1000 + i * 100)
        parts_g[10] = str(i % 4 + 1)
        parts_g[12] = str(20 + (i % 60))
        lines.append(",".join(parts_g))
    for i in range(50):
        parts_b = bad.split()
        parts_b[0] = f"A{i % 11 + 11}"
        parts_b[1] = str(12 + (i % 36))
        parts_b[4] = str(2000 + i * 200)
        parts_b[10] = str(i % 4 + 1)
        parts_b[12] = str(25 + (i % 55))
        lines.append(",".join(parts_b))
    p = tmp / "german_credit.csv"
    p.write_text("\n".join(lines))
    return p


def make_sample_german_credit_zip(tmp: Path) -> Path:
    """Write a zipped German Credit fixture file."""
    import zipfile
    zpath = tmp / "german.zip"
    with zipfile.ZipFile(zpath, "w") as zf:
        zf.writestr("german.data", "\n".join(SAMPLE_GERMAN_CREDIT_LINES))
    return zpath


# ---------------------------------------------------------------------------
# Synthetic CSV fixture generators for generic import tests
# ---------------------------------------------------------------------------


def make_synthetic_csv(tmp: Path, filename: str = "synthetic.csv", rows: int = 50) -> Path:
    """Create a synthetic CSV with header, numeric features, and binary target.
    
    Target column is ``default_flag`` with values ``Y``/``N`` (not 1/2).
    """
    rng = np.random.RandomState(42)
    data = {
        "customer_id": [f"C{i:04d}" for i in range(rows)],
        "age": list(rng.randint(18, 75, size=rows)),
        "income": [round(x, 2) for x in rng.uniform(20000, 150000, size=rows)],
        "credit_score": list(rng.randint(300, 850, size=rows)),
        "loan_amount": [round(x, 2) for x in rng.uniform(1000, 50000, size=rows)],
        "default_flag": ["Y" if rng.random() < 0.3 else "N" for _ in range(rows)],
    }
    header = ",".join(data.keys())
    lines = [header]
    for i in range(rows):
        lines.append(",".join(str(data[k][i]) for k in data))
    p = tmp / filename
    p.write_text("\n".join(lines))
    return p


def make_synthetic_tsv(tmp: Path, filename: str = "synthetic.tsv", rows: int = 50) -> Path:
    """Create a synthetic TSV with header, numeric features, and binary target."""
    rng = np.random.RandomState(42)
    data = {
        "customer_id": [f"C{i:04d}" for i in range(rows)],
        "age": list(rng.randint(18, 75, size=rows)),
        "income": [round(x, 2) for x in rng.uniform(20000, 150000, size=rows)],
        "default_flag": ["Y" if rng.random() < 0.3 else "N" for _ in range(rows)],
    }
    header = "\t".join(data.keys())
    lines = [header]
    for i in range(rows):
        lines.append("\t".join(str(data[k][i]) for k in data))
    p = tmp / filename
    p.write_text("\n".join(lines))
    return p


def make_synthetic_no_header_csv(tmp: Path, filename: str = "no_header.csv") -> Path:
    """Create a CSV without header row using positional columns."""
    rows = [
        "C0001,25,45000,Y",
        "C0002,62,120000,N",
        "C0003,34,62000,Y",
        "C0004,45,85000,N",
    ]
    p = tmp / filename
    p.write_text("\n".join(rows))
    return p


def make_synthetic_with_nulls_csv(tmp: Path, filename: str = "with_nulls.csv") -> Path:
    """Create a CSV with missing values for null_values testing."""
    rows = [
        "id,score,label",
        "1,85,Y",
        "2,,N",
        "3,72,",
        "4,,Y",
        "5,91,N",
    ]
    p = tmp / filename
    p.write_text("\n".join(rows))
    return p


# ---------------------------------------------------------------------------
# Synthetic dataset generators
# ---------------------------------------------------------------------------


def make_numeric_dataset(
    store: ProjectStore,
    n_rows: int = 100,
    seed: int = 42,
) -> tuple:
    """Create a synthetic 3-feature numeric dataset with binary target.

    Target is "bad" when ``feat_a > 55`` and ``feat_b > 22``.
    Returns ``(data_artifact, definition_artifact, dataframe)``.
    """
    rng = np.random.RandomState(seed)
    feat_a = rng.randn(n_rows) * 10 + 50
    feat_b = rng.randn(n_rows) * 5 + 20
    feat_c = rng.randn(n_rows) * 2 + 10
    target = ["bad" if feat_a[i] > 55 and feat_b[i] > 22 else "good" for i in range(n_rows)]

    df = pl.DataFrame({
        "feat_a": feat_a,
        "feat_b": feat_b,
        "feat_c": feat_c,
        "target": target,
    })

    data_art = write_parquet_artifact(
        store, artifact_type="dataset", role="train",
        stem="synthetic-train", frame=df, metadata={},
    )
    def_art = write_json_artifact(
        store, artifact_type="definition", role="definition",
        stem="synthetic-definition",
        payload={"target_column": "target", "good_values": ["good"], "bad_values": ["bad"]},
        metadata={},
    )
    return data_art, def_art, df


def make_oot_dataset(
    store: ProjectStore,
    df: pl.DataFrame | None = None,
    seed: int = 99,
) -> tuple:
    """Create an out-of-time dataset artifact for tests."""
    if df is None:
        rng = np.random.RandomState(123)
        df = pl.DataFrame({
            "feat_a": rng.randn(50) * 10 + 50,
            "feat_b": rng.randn(50) * 5 + 20,
            "feat_c": rng.randn(50) * 2 + 10,
            "target": ["bad" if i % 5 == 0 else "good" for i in range(50)],
        })
    else:
        rng = np.random.RandomState(seed)
        n_rows = df.height
        feat_a = df["feat_a"].to_numpy() + rng.randn(n_rows) * 2
        feat_b = df["feat_b"].to_numpy() + rng.randn(n_rows) * 1
        feat_c = df["feat_c"].to_numpy() + rng.randn(n_rows) * 0.5
        target = ["bad" if feat_a[i] > 55 and feat_b[i] > 22 else "good" for i in range(n_rows)]
        df = pl.DataFrame({
            "feat_a": feat_a,
            "feat_b": feat_b,
            "feat_c": feat_c,
            "target": target,
        })

    art = write_parquet_artifact(
        store, artifact_type="dataset", role="oot",
        stem="synthetic-oot", frame=df, metadata={},
    )
    return art, df


# ---------------------------------------------------------------------------
# Artifact helpers (backward-compatible artifact_id / filename format)
# ---------------------------------------------------------------------------


def _make_train_artifact(store, df, role="train"):
    """Register a dataset artifact using the legacy artifact_id format."""
    buf = io.BytesIO()
    df.write_parquet(buf)
    path = store.root / "datasets" / f"test-{role}.parquet"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(buf.getvalue())
    art = ArtifactRef(
        artifact_id=f"{role}_1", artifact_type="dataset", role=role,
        path=relative_path(path, store.root),
        physical_hash=physical_hash(path),
        logical_hash=table_logical_hash(df),
        media_type="application/vnd.apache.parquet", metadata={},
    )
    store.register_artifact(art)
    return art


def _make_json_artifact(store, payload, role="definition", stem="test"):
    """Register a JSON artifact using the legacy artifact_id format."""
    p = store.root / "artifacts" / f"{stem}.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(payload, sort_keys=True))
    art = ArtifactRef(
        artifact_id=f"{stem}_1", artifact_type=role, role=role,
        path=relative_path(p, store.root),
        physical_hash=physical_hash(p),
        logical_hash=json_logical_hash(payload),
        media_type="application/json", metadata={},
    )
    store.register_artifact(art)
    return art


def _make_parquet_report(store, df, role="report", stem="test"):
    """Register a Parquet report artifact using the legacy artifact_id format."""
    buf = io.BytesIO()
    df.write_parquet(buf)
    p = store.root / "reports" / f"{stem}.parquet"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(buf.getvalue())
    art = ArtifactRef(
        artifact_id=f"{stem}_1", artifact_type="report", role=role,
        path=relative_path(p, store.root),
        physical_hash=physical_hash(p),
        logical_hash=table_logical_hash(df),
        media_type="application/vnd.apache.parquet", metadata={},
    )
    store.register_artifact(art)
    return art
