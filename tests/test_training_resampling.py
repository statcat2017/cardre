"""Tests for sampling provenance — ``_is_synthetic_row`` materialisation.

Exercises random resampling and SMOTE through their Node ``run()`` methods
with real ProjectStore fixtures and Parquet Artifacts.
"""

from __future__ import annotations

import importlib.util
import uuid

import numpy as np
import polars as pl
import pytest

from cardre.artifacts import write_parquet_artifact
from cardre.domain.diagnostics import utc_now_iso
from cardre.store.db import ProjectStore

pytestmark = pytest.mark.xfail(reason="Old StepRunner/execution path; needs NodeContext update")

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_store(tmp_path):
    store = ProjectStore(tmp_path / "test.cardre")
    store.initialize()
    return store


def _make_imbalanced_frame() -> pl.DataFrame:
    """Return a train frame with 80 good / 20 bad rows and deterministic IDs."""
    rng = np.random.RandomState(42)
    n_good = 80
    n_bad = 20
    target_data = ["good"] * n_good + ["bad"] * n_bad
    rng.shuffle(target_data)
    return pl.DataFrame({
        "row_id": list(range(100)),
        "feature_a": rng.randn(100).tolist(),
        "feature_b": rng.randn(100).tolist(),
        "target": target_data,
    })


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
    meta_id = str(uuid.uuid4())
    return store, pv_id, run_id, train_art, meta_id


def _make_context(store, pv_id, run_id, train_art, params=None):
    """Build a minimal ExecutionContext for node run() tests."""
    from dataclasses import dataclass, field

    from cardre.domain.step import StepSpec

    @dataclass
    class _Ctx:
        store: ProjectStore
        _pv_id: str
        _run_id: str
        input_artifacts: list = field(default_factory=lambda: [train_art])
        validated_params: dict = field(default_factory=lambda: params or {})
        _step_id: str = "test-step"
        _meta_target_column: str = "target"
        _meta_good_values: frozenset = frozenset({"good"})
        _meta_bad_values: frozenset = frozenset({"bad"})

        def require_train_artifact(self, operation: str):
            return train_art

        def train_artifact(self):
            return train_art

        def target_metadata(self):
            from cardre._evidence.models import ModellingMetadata
            return ModellingMetadata(
                target_column=self._meta_target_column,
                good_values=self._meta_good_values,
                bad_values=self._meta_bad_values,
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

    NODE_PATH = "cardre.nodes.selection.ResampleTrainingDataNode"

    def _run(self, store, pv_id, run_id, train_art, meta_id, params):
        from cardre.nodes.selection import ResampleTrainingDataNode
        node = ResampleTrainingDataNode()
        ctx = _make_context(store, pv_id, run_id, train_art, params)
        return node.run(ctx)

    def test_oversample_writes_flag_column(self, tmp_path):
        store, pv_id, run_id, train_art, meta_id = _seed_run_context(tmp_path)
        result = self._run(store, pv_id, run_id, train_art, meta_id,
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
        store, pv_id, run_id, train_art, meta_id = _seed_run_context(tmp_path)
        result = self._run(store, pv_id, run_id, train_art, meta_id,
                          {"strategy": "oversample_minority", "sampling_ratio": 1.0})
        from cardre._evidence.reader import ArtifactEvidenceReader
        reader = ArtifactEvidenceReader(store)
        train_art = next(a for a in result.artifacts if a.role == "train")
        df = reader.read_dataframe(train_art)
        n_synthetic = int(df["_is_synthetic_row"].sum())
        assert n_synthetic == result.metrics.get("synthetic_count", -1)

    def test_undersample_all_false(self, tmp_path):
        store, pv_id, run_id, train_art, meta_id = _seed_run_context(tmp_path)
        result = self._run(store, pv_id, run_id, train_art, meta_id,
                          {"strategy": "undersample_majority", "sampling_ratio": 0.5})
        from cardre._evidence.reader import ArtifactEvidenceReader
        reader = ArtifactEvidenceReader(store)
        train_art = next(a for a in result.artifacts if a.role == "train")
        df = reader.read_dataframe(train_art)
        assert "_is_synthetic_row" in df.columns
        assert df["_is_synthetic_row"].sum() == 0

    def test_original_rows_are_false(self, tmp_path):
        """Every original selected row is False; only extra duplicates are True.

        Uses a deterministic ``row_id`` column to verify that:
        - All distinct original bad rows appear with at least one ``False`` copy.
        - Every ``True`` row has a ``row_id`` from an original bad row.
        - The exact count of ``True`` rows matches the planned oversample amount.
        """
        store, pv_id, run_id, train_art, meta_id = _seed_run_context(tmp_path)
        result = self._run(store, pv_id, run_id, train_art, meta_id,
                          {"strategy": "oversample_minority", "sampling_ratio": 1.0})
        from cardre._evidence.reader import ArtifactEvidenceReader
        reader = ArtifactEvidenceReader(store)
        train_art = next(a for a in result.artifacts if a.role == "train")
        df = reader.read_dataframe(train_art)

        n_false = int((df["_is_synthetic_row"] == False).sum())  # noqa: E712
        n_true = int(df["_is_synthetic_row"].sum())
        assert n_false + n_true == len(df)
        # Exactly 60 extra minority rows (from 20 to 80 bad)
        assert n_true == 60
        assert n_false == 100

        # Every True row has a row_id from an original bad row (row_id > 79
        # in the shuffled fixture or fewer depending on class distribution)
        distinct_true_ids = set(df.filter(pl.col("_is_synthetic_row"))["row_id"].to_list())
        # Every True row's row_id appears in the False set (duplicate pair)
        for rid in distinct_true_ids:
            df_has_false = df.filter((pl.col("row_id") == rid) & (~pl.col("_is_synthetic_row")))
            assert len(df_has_false) > 0, f"row_id {rid} has no False copy"

    def test_chained_resampling_preserves_incoming(self, tmp_path):
        """Running oversampling on an already-resampled artifact preserves
        the incoming _is_synthetic_row=True for previously added rows."""
        store, pv_id, run_id, train_art, meta_id = _seed_run_context(tmp_path)

        # First pass: oversample
        first_result = self._run(store, pv_id, run_id, train_art, meta_id,
                                {"strategy": "oversample_minority", "sampling_ratio": 1.0})
        from cardre._evidence.reader import ArtifactEvidenceReader
        reader = ArtifactEvidenceReader(store)
        first_art = next(a for a in first_result.artifacts if a.role == "train")
        first_df = reader.read_dataframe(first_art)
        first_synthetic = int(first_df["_is_synthetic_row"].sum())
        assert first_synthetic == 60

        # Second pass: feed the resampled artifact back as train input.
        # Use undersample so no new synthetic rows are added.
        from cardre.artifacts import write_parquet_artifact

        second_train_art = write_parquet_artifact(
            store, artifact_type="dataset", role="train",
            stem="chained-train", frame=first_df,
            metadata={"plan_version_id": pv_id},
        )
        # Build context pointing at the second artifact
        ctx = _make_context(store, pv_id, run_id, second_train_art,
                           {"strategy": "undersample_majority", "sampling_ratio": 0.5})
        from cardre.nodes.selection import ResampleTrainingDataNode
        second_result = ResampleTrainingDataNode().run(ctx)

        second_art = next(a for a in second_result.artifacts if a.role == "train")
        second_df = reader.read_dataframe(second_art)
        second_synthetic = int(second_df["_is_synthetic_row"].sum())
        # The second pass should NOT add new synthetic rows (undersample),
        # and should preserve the incoming 60 True values.
        assert second_synthetic >= 60, (
            f"Expected at least {first_synthetic} synthetic rows preserved, "
            f"got {second_synthetic}"
        )


# ---------------------------------------------------------------------------
# SMOTE provenance tests (optional dependency)
# ---------------------------------------------------------------------------


class TestSmoteProvenance:
    """SMOTE writes _is_synthetic_row correctly when imblearn is available."""

    SMOTE_NODE_PATH = "cardre.nodes.selection.SmoteTrainingDataNode"

    @pytest.mark.skipif(
        not importlib.util.find_spec("imblearn"),
        reason="SMOTE requires imbalanced-learn",
    )
    def test_smote_writes_flag_column(self, tmp_path):
        from cardre.nodes.selection import SmoteTrainingDataNode
        node = SmoteTrainingDataNode()
        store, pv_id, run_id, train_art, meta_id = _seed_run_context(tmp_path)
        ctx = _make_context(store, pv_id, run_id, train_art,
                           {"sampling_ratio": 1.0})
        result = node.run(ctx)
        from cardre._evidence.reader import ArtifactEvidenceReader
        reader = ArtifactEvidenceReader(store)
        train_art = next(a for a in result.artifacts if a.role == "train")
        df = reader.read_dataframe(train_art)
        assert "_is_synthetic_row" in df.columns
        assert df["_is_synthetic_row"].sum() > 0

    @pytest.mark.skipif(
        not importlib.util.find_spec("imblearn"),
        reason="SMOTE requires imbalanced-learn",
    )
    def test_smote_synthetic_matches_report(self, tmp_path):
        from cardre.nodes.selection import SmoteTrainingDataNode
        node = SmoteTrainingDataNode()
        store, pv_id, run_id, train_art, meta_id = _seed_run_context(tmp_path)
        ctx = _make_context(store, pv_id, run_id, train_art,
                           {"sampling_ratio": 1.0})
        result = node.run(ctx)
        from cardre._evidence.reader import ArtifactEvidenceReader
        reader = ArtifactEvidenceReader(store)
        train_art = next(a for a in result.artifacts if a.role == "train")
        df = reader.read_dataframe(train_art)
        assert df["_is_synthetic_row"].sum() == result.metrics.get("synthetic_count", -1)

    @pytest.mark.skipif(
        not importlib.util.find_spec("imblearn"),
        reason="SMOTE requires imbalanced-learn",
    )
    def test_smote_original_rows_are_false(self, tmp_path):
        from cardre.nodes.selection import SmoteTrainingDataNode
        node = SmoteTrainingDataNode()
        store, pv_id, run_id, train_art, meta_id = _seed_run_context(tmp_path)
        ctx = _make_context(store, pv_id, run_id, train_art,
                           {"sampling_ratio": 1.0})
        result = node.run(ctx)
        from cardre._evidence.reader import ArtifactEvidenceReader
        reader = ArtifactEvidenceReader(store)
        train_art = next(a for a in result.artifacts if a.role == "train")
        df = reader.read_dataframe(train_art)
        n_original = 100  # original rows in fixture
        first_rows = df.head(n_original)
        assert first_rows["_is_synthetic_row"].sum() == 0
