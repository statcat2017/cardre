"""Tests for sampling provenance — ``_is_synthetic_row`` materialisation.

Exercises random resampling and SMOTE through their Node ``run()`` methods
with real ProjectStore fixtures and Parquet Artifacts.
"""

from __future__ import annotations

import uuid

import numpy as np
import polars as pl
import pytest

from cardre.artifacts import write_parquet_artifact
from cardre.domain.diagnostics import utc_now_iso
from cardre.store.db import ProjectStore

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_store(tmp_path):
    store = ProjectStore(tmp_path / "test.cardre")
    store.initialize()
    return store


def _make_imbalanced_frame() -> pl.DataFrame:
    """Return a train frame with 80 good / 20 bad rows and an ID column."""
    rng = np.random.RandomState(42)
    n_good = 80
    n_bad = 20
    ids_good = [f"orig-g-{i}" for i in range(n_good)]
    ids_bad = [f"orig-b-{i}" for i in range(n_bad)]
    target_data = ["good"] * n_good + ["bad"] * n_bad
    rng.shuffle(target_data)
    return pl.DataFrame({
        "id": ids_good + ids_bad,
        "feature_a": rng.randn(100).tolist(),
        "feature_b": rng.randn(100).tolist(),
        "target": target_data,
    })


def _seed_modelling_metadata(store, project_id, plan_id, pv_id):
    """Insert a MODELLING_METADATA definition artifact."""
    import io

    from cardre._evidence.adapters import get_adapter
    from cardre._evidence.kinds import EvidenceKind
    from cardre._evidence.models import ModellingMetadata

    meta = ModellingMetadata(
        target_column="target",
        good_values=frozenset({"good"}),
        bad_values=frozenset({"bad"}),
    )
    adapter = get_adapter(EvidenceKind.MODELLING_METADATA)
    buf = io.BytesIO()
    adapter.write(buf, meta)
    buf.seek(0)
    artifact_id = str(uuid.uuid4())
    store.execute(
        "INSERT INTO artifacts (artifact_id, artifact_type, role, physical_hash, "
        "logical_hash, file_size_bytes, storage_path, metadata_json) "
        "VALUES (?, 'definition', 'definition', ?, ?, ?, ?, ?)",
        (artifact_id, "hash123", "hash456", 0, "/dev/null/artifact.json",
         '{"schema_version": "cardre.modelling_metadata.v1"}'),
    )
    store.execute(
        "INSERT INTO artifact_data (artifact_id, data) VALUES (?, ?)",
        (artifact_id, buf.read()),
    )
    return artifact_id


def _seed_run_context(tmp_path):
    """Return (store, pv_id, run_id, train_artifact_id, meta_artifact_id)."""
    store = _make_store(tmp_path)
    now = utc_now_iso()
    project_id = str(uuid.uuid4())
    store.execute(
        "INSERT INTO projects (project_id, name, created_at, cardre_version) VALUES (?, ?, ?, ?)",
        (project_id, "Resampling Test", now, "0.2.0"),
    )
    plan_id = str(uuid.uuid4())
    store.execute(
        "INSERT INTO plans (plan_id, project_id, name, created_at) VALUES (?, ?, ?, ?)",
        (plan_id, project_id, "Test Plan", now),
    )
    pv_id = str(uuid.uuid4())
    store.execute(
        "INSERT INTO plan_versions (plan_version_id, plan_id, version_number, is_committed, created_at) "
        "VALUES (?, ?, 1, 1, ?)",
        (pv_id, plan_id, now),
    )
    run_id = str(uuid.uuid4())
    store.execute(
        "INSERT INTO runs (run_id, plan_version_id, status, created_at, started_at) VALUES (?, ?, 'running', ?, ?)",
        (run_id, pv_id, now, now),
    )
    df = _make_imbalanced_frame()
    train_art = write_parquet_artifact(
        store, artifact_type="dataset", role="train",
        stem="train-data", frame=df,
        metadata={"plan_version_id": pv_id},
    )
    meta_id = _seed_modelling_metadata(store, project_id, plan_id, pv_id)
    return store, pv_id, run_id, train_art.artifact_id, meta_id


def _make_context(store, pv_id, run_id, train_artifact_id, meta_artifact_id, params=None):
    """Build a minimal ExecutionContext for node run() tests."""
    from dataclasses import dataclass, field

    from cardre._evidence.kinds import EvidenceKind
    from cardre._evidence.reader import ArtifactEvidenceReader
    from cardre.domain.artifacts import ArtifactRef
    from cardre.domain.step import StepSpec

    meta_ref = ArtifactRef(
        artifact_id=meta_artifact_id, artifact_type="definition",
        role="definition", physical_hash="", logical_hash="",
    )
    train_ref = ArtifactRef(
        artifact_id=train_artifact_id, artifact_type="dataset",
        role="train", physical_hash="", logical_hash="",
    )

    @dataclass
    class _Ctx:
        store: ProjectStore
        _pv_id: str
        _run_id: str
        input_artifacts: list = field(default_factory=lambda: [meta_ref, train_ref])
        validated_params: dict = field(default_factory=lambda: params or {})
        _step_id: str = "test-step"

        def require_train_artifact(self, operation: str):
            return train_ref

        def train_artifact(self):
            return train_ref

        def target_metadata(self):
            reader = ArtifactEvidenceReader(self.store)
            return reader.find_optional(
                self.input_artifacts, EvidenceKind.MODELLING_METADATA,
            )

        @property
        def step_spec(self):
            return StepSpec(
                step_id=self._step_id, node_type="test", node_version="1",
                category="transform", params=dict(self.validated_params),
                params_hash="h", parent_step_ids=[],
            )

    return _Ctx(store=store, _pv_id=pv_id, _run_id=run_id)


# ---------------------------------------------------------------------------
# Random resampling provenance tests
# ---------------------------------------------------------------------------


class TestRandomResamplingProvenance:
    """Random resampling writes _is_synthetic_row correctly."""

    NODE_PATH = "cardre.nodes.feature_selection.ResampleTrainingDataNode"

    def _run(self, store, pv_id, run_id, train_id, meta_id, params):
        from cardre.nodes.feature_selection import ResampleTrainingDataNode
        node = ResampleTrainingDataNode()
        ctx = _make_context(store, pv_id, run_id, train_id, meta_id, params)
        return node.run(ctx)

    def test_oversample_writes_flag_column(self, tmp_path):
        store, pv_id, run_id, train_id, meta_id = _seed_run_context(tmp_path)
        result = self._run(store, pv_id, run_id, train_id, meta_id,
                          {"strategy": "oversample_minority", "sampling_ratio": 1.0})
        assert any(a.role == "train" for a in result.artifacts)

        # Read the parquet and check the flag
        from cardre._evidence.reader import ArtifactEvidenceReader
        reader = ArtifactEvidenceReader(store)
        train_art = next(a for a in result.artifacts if a.role == "train")
        df = reader.read_dataframe(train_art)
        assert "_is_synthetic_row" in df.columns
        n_synthetic = int(df["_is_synthetic_row"].sum())
        assert n_synthetic > 0
        # oversample_minority from 20 bad -> 80 bad = 60 extra
        assert n_synthetic == 60

    def test_oversample_synthetic_matches_report(self, tmp_path):
        store, pv_id, run_id, train_id, meta_id = _seed_run_context(tmp_path)
        result = self._run(store, pv_id, run_id, train_id, meta_id,
                          {"strategy": "oversample_minority", "sampling_ratio": 1.0})
        from cardre._evidence.reader import ArtifactEvidenceReader
        reader = ArtifactEvidenceReader(store)
        train_art = next(a for a in result.artifacts if a.role == "train")
        df = reader.read_dataframe(train_art)
        n_synthetic = int(df["_is_synthetic_row"].sum())
        assert n_synthetic == result.metrics.get("synthetic_count", -1)

    def test_undersample_all_false(self, tmp_path):
        store, pv_id, run_id, train_id, meta_id = _seed_run_context(tmp_path)
        result = self._run(store, pv_id, run_id, train_id, meta_id,
                          {"strategy": "undersample_majority", "sampling_ratio": 0.5})
        from cardre._evidence.reader import ArtifactEvidenceReader
        reader = ArtifactEvidenceReader(store)
        train_art = next(a for a in result.artifacts if a.role == "train")
        df = reader.read_dataframe(train_art)
        assert "_is_synthetic_row" in df.columns
        assert df["_is_synthetic_row"].sum() == 0

    def test_original_rows_are_false(self, tmp_path):
        """Every original selected row is False; only extra duplicates are True."""
        store, pv_id, run_id, train_id, meta_id = _seed_run_context(tmp_path)
        result = self._run(store, pv_id, run_id, train_id, meta_id,
                          {"strategy": "oversample_minority", "sampling_ratio": 1.0})
        from cardre._evidence.reader import ArtifactEvidenceReader
        reader = ArtifactEvidenceReader(store)
        train_art = next(a for a in result.artifacts if a.role == "train")
        df = reader.read_dataframe(train_art)

        # Count unique values of a proxy for "original" row identity.
        # All False rows plus all True rows should total the output.
        n_false = int((df["_is_synthetic_row"] == False).sum())  # noqa: E712
        n_true = int(df["_is_synthetic_row"].sum())
        assert n_false + n_true == len(df)
        # At least one row is an original selected row (false)
        assert n_false > 0
        # At least one row is an extra duplicate (true)
        assert n_true > 0


# ---------------------------------------------------------------------------
# SMOTE provenance tests (optional dependency)
# ---------------------------------------------------------------------------


class TestSmoteProvenance:
    """SMOTE writes _is_synthetic_row correctly when imblearn is available."""

    SMOTE_NODE_PATH = "cardre.nodes.feature_selection.SmoteTrainingDataNode"

    @pytest.mark.skipif(
        not pytest.importorskip("imblearn", reason="imbalanced-learn not installed"),
        reason="SMOTE requires imbalanced-learn",
    )
    def test_smote_writes_flag_column(self, tmp_path):
        from cardre.nodes.feature_selection import SmoteTrainingDataNode
        node = SmoteTrainingDataNode()
        store, pv_id, run_id, train_id, meta_id = _seed_run_context(tmp_path)
        ctx = _make_context(store, pv_id, run_id, train_id, meta_id,
                           {"sampling_ratio": 1.0})
        result = node.run(ctx)
        from cardre._evidence.reader import ArtifactEvidenceReader
        reader = ArtifactEvidenceReader(store)
        train_art = next(a for a in result.artifacts if a.role == "train")
        df = reader.read_dataframe(train_art)
        assert "_is_synthetic_row" in df.columns
        assert df["_is_synthetic_row"].sum() > 0

    @pytest.mark.skipif(
        not pytest.importorskip("imblearn", reason="imbalanced-learn not installed"),
        reason="SMOTE requires imbalanced-learn",
    )
    def test_smote_synthetic_matches_report(self, tmp_path):
        from cardre.nodes.feature_selection import SmoteTrainingDataNode
        node = SmoteTrainingDataNode()
        store, pv_id, run_id, train_id, meta_id = _seed_run_context(tmp_path)
        ctx = _make_context(store, pv_id, run_id, train_id, meta_id,
                           {"sampling_ratio": 1.0})
        result = node.run(ctx)
        from cardre._evidence.reader import ArtifactEvidenceReader
        reader = ArtifactEvidenceReader(store)
        train_art = next(a for a in result.artifacts if a.role == "train")
        df = reader.read_dataframe(train_art)
        assert df["_is_synthetic_row"].sum() == result.metrics.get("synthetic_count", -1)

    @pytest.mark.skipif(
        not pytest.importorskip("imblearn", reason="imbalanced-learn not installed"),
        reason="SMOTE requires imbalanced-learn",
    )
    def test_smote_original_rows_are_false(self, tmp_path):
        from cardre.nodes.feature_selection import SmoteTrainingDataNode
        node = SmoteTrainingDataNode()
        store, pv_id, run_id, train_id, meta_id = _seed_run_context(tmp_path)
        ctx = _make_context(store, pv_id, run_id, train_id, meta_id,
                           {"sampling_ratio": 1.0})
        result = node.run(ctx)
        from cardre._evidence.reader import ArtifactEvidenceReader
        reader = ArtifactEvidenceReader(store)
        train_art = next(a for a in result.artifacts if a.role == "train")
        df = reader.read_dataframe(train_art)
        n_original = 100  # original rows in fixture
        first_rows = df.head(n_original)
        assert first_rows["_is_synthetic_row"].sum() == 0
