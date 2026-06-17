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
    """Write a small German Credit fixture file (2 rows)."""
    p = tmp / "german.data"
    p.write_text("\n".join(SAMPLE_GERMAN_CREDIT_LINES))
    return p


def make_sample_german_credit_zip(tmp: Path) -> Path:
    """Write a zipped German Credit fixture file."""
    import zipfile
    zpath = tmp / "german.zip"
    with zipfile.ZipFile(zpath, "w") as zf:
        zf.writestr("german.data", "\n".join(SAMPLE_GERMAN_CREDIT_LINES))
    return zpath


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


def _make_parquet_report(store, df, role="report", stem="report"):
    """Register a Parquet report artifact using the legacy artifact_id format."""
    buf = io.BytesIO()
    df.write_parquet(buf)
    p = store.root / "datasets" / f"{stem}.parquet"
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


def make_oot_dataset(
    store: ProjectStore,
    df: pl.DataFrame,
    seed: int = 99,
) -> tuple:
    """Create an OOT dataset by perturbing the original feature values."""
    rng = np.random.RandomState(seed)
    n_rows = df.height
    feat_a = df["feat_a"].to_numpy() + rng.randn(n_rows) * 2
    feat_b = df["feat_b"].to_numpy() + rng.randn(n_rows) * 1
    feat_c = df["feat_c"].to_numpy() + rng.randn(n_rows) * 0.5
    target = ["bad" if feat_a[i] > 55 and feat_b[i] > 22 else "good" for i in range(n_rows)]
    oot_df = pl.DataFrame({
        "feat_a": feat_a, "feat_b": feat_b, "feat_c": feat_c, "target": target,
    })
    oot_art = write_parquet_artifact(
        store, artifact_type="dataset", role="oot",
        stem="synthetic-oot", frame=oot_df, metadata={},
    )
    return oot_art, oot_df
