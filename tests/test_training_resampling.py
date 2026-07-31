"""Tests for sampling provenance — ``_is_synthetic_row`` materialisation.

Exercises random resampling and SMOTE through their Node ``run()`` methods
using a ``NodeContext`` built over ``FsArtifactStore`` and
``StagingOutputPublisher``.
"""

from __future__ import annotations

import importlib.util
import json
from types import SimpleNamespace
from typing import Any

import numpy as np
import polars as pl
import pytest

from cardre.adapters.filesystem.artifact_store import FsArtifactStore
from cardre.application.execution.input_collection import TargetMeta
from cardre.application.execution.output_publisher import StagingOutputPublisher
from cardre.domain.evidence.kinds import EvidenceKind
from cardre.domain.step import StepSpec
from cardre.nodes.contracts import NodeContext, RuntimeMeta

RESAMPLE_NODE_TYPE = "cardre.resample_training_data"
SMOTE_NODE_TYPE = "cardre.smote_training_data"


class FakeInputs:
    """Minimal InputCollection providing one train artifact + target metadata."""

    def __init__(
        self,
        train_artifact: Any,
        frame: pl.DataFrame,
        metadata: Any | None = None,
    ) -> None:
        self._train_artifact = train_artifact
        self._frame = frame
        self._metadata = metadata or TargetMeta(
            target_column="target",
            good_values=frozenset({"good"}),
            bad_values=frozenset({"bad"}),
        )

    def by_role(self, role: str) -> list[Any]:
        return [self._train_artifact] if role == "train" else []

    def by_kind(self, kind: EvidenceKind) -> list[Any]:
        return []

    def first(self, role: str) -> Any | None:
        return self._train_artifact if role == "train" else None

    def require(self, role: str, node_type: str) -> Any:
        artifact = self.first(role)
        if artifact is None:
            raise ValueError(f"{node_type} requires a '{role}' artifact")
        return artifact

    def read(self, artifact: Any, kind: EvidenceKind) -> Any:
        raise NotImplementedError

    def read_optional(self, artifact: Any, kind: EvidenceKind) -> Any | None:
        return None

    def read_dataframe(self, artifact: Any) -> pl.DataFrame:
        assert artifact is self._train_artifact
        return self._frame

    def read_bytes(self, artifact: Any) -> bytes:
        raise NotImplementedError

    def target_metadata(self) -> Any | None:
        return self._metadata

    def find_frozen_bundle(self) -> Any | None:
        return None

    def artifact_ref(self, artifact_id: str, *, physical_hash: str | None = None) -> Any | None:
        if self._train_artifact.artifact_id == artifact_id:
            return self._train_artifact
        return None


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


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


def _artifact(artifact_id: str) -> SimpleNamespace:
    return SimpleNamespace(artifact_id=artifact_id, role="train")


def _make_context(
    store: FsArtifactStore,
    train_artifact: Any,
    frame: pl.DataFrame,
    params: dict[str, Any],
    node_type: str,
) -> NodeContext:
    spec = StepSpec(
        step_id="resample-step",
        node_type=node_type,
        node_version="1",
        category="transform",
        params=params,
        params_hash="hash",
        parent_step_ids=[],
    )
    return NodeContext(
        run_id="run-1",
        plan_version_id="plan-1",
        step_spec=spec,
        inputs=FakeInputs(train_artifact, frame),
        outputs=StagingOutputPublisher(store),
        params=params,
        runtime=RuntimeMeta("run-1", "plan-1", "resample-step", node_type),
    )


def _run(
    node,
    store: FsArtifactStore,
    frame: pl.DataFrame,
    params: dict[str, Any],
    node_type: str,
    train_artifact: Any | None = None,
):
    train_artifact = train_artifact or _artifact("train-artifact")
    context = _make_context(store, train_artifact, frame, params, node_type)
    result = node.run(context)
    for staged in result.staged_artifacts:
        store.publish(staged)
    return result


def _read_train(store: FsArtifactStore, result) -> pl.DataFrame:
    staged = next(a for a in result.staged_artifacts if a.role == "train")
    return pl.read_parquet(store.resolve_path(staged))


def _read_report(store: FsArtifactStore, result) -> dict[str, Any]:
    staged = next(a for a in result.staged_artifacts if a.role == "report")
    return json.loads(store.read_bytes(staged))


# ---------------------------------------------------------------------------
# Random resampling provenance tests
# ---------------------------------------------------------------------------


class TestRandomResamplingProvenance:
    """Random resampling writes _is_synthetic_row correctly."""

    NODE_PATH = "cardre.nodes.selection.ResampleTrainingDataNode"

    def _run_node(self, store, frame, params, train_artifact=None):
        from cardre.nodes.selection import ResampleTrainingDataNode
        return _run(ResampleTrainingDataNode(), store, frame, params,
                    RESAMPLE_NODE_TYPE, train_artifact=train_artifact)

    def test_oversample_writes_flag_column(self, tmp_path):
        store = FsArtifactStore(tmp_path)
        result = self._run_node(store, _make_imbalanced_frame(),
                                {"strategy": "oversample_minority", "sampling_ratio": 1.0})
        assert any(a.role == "train" for a in result.staged_artifacts)

        df = _read_train(store, result)
        assert "_is_synthetic_row" in df.columns
        n_synthetic = int(df["_is_synthetic_row"].sum())
        assert n_synthetic > 0
        # oversample_minority from 20 bad -> 80 bad = 60 extra
        assert n_synthetic == 60

    def test_oversample_synthetic_matches_report(self, tmp_path):
        store = FsArtifactStore(tmp_path)
        result = self._run_node(store, _make_imbalanced_frame(),
                                {"strategy": "oversample_minority", "sampling_ratio": 1.0})
        df = _read_train(store, result)
        n_synthetic = int(df["_is_synthetic_row"].sum())
        assert n_synthetic == result.metrics.get("synthetic_count", -1)
        report = _read_report(store, result)
        assert report["synthetic_rows_added"] == n_synthetic
        assert report["strategy"] == "oversample_minority"

    def test_undersample_all_false(self, tmp_path):
        store = FsArtifactStore(tmp_path)
        result = self._run_node(store, _make_imbalanced_frame(),
                                {"strategy": "undersample_majority", "sampling_ratio": 0.5})
        df = _read_train(store, result)
        assert "_is_synthetic_row" in df.columns
        assert df["_is_synthetic_row"].sum() == 0

    def test_original_rows_are_false(self, tmp_path):
        """Every original selected row is False; only extra duplicates are True.

        Uses a deterministic ``row_id`` column to verify that:
        - All distinct original bad rows appear with at least one ``False`` copy.
        - Every ``True`` row has a ``row_id`` from an original bad row.
        - The exact count of ``True`` rows matches the planned oversample amount.
        """
        store = FsArtifactStore(tmp_path)
        result = self._run_node(store, _make_imbalanced_frame(),
                                {"strategy": "oversample_minority", "sampling_ratio": 1.0})
        df = _read_train(store, result)

        n_false = int((~df["_is_synthetic_row"]).sum())
        n_true = int(df["_is_synthetic_row"].sum())
        assert n_false + n_true == len(df)
        # Exactly 60 extra minority rows (from 20 to 80 bad)
        assert n_true == 60
        assert n_false == 100

        # Every True row has a row_id from an original bad row
        distinct_true_ids = set(df.filter(pl.col("_is_synthetic_row"))["row_id"].to_list())
        for rid in distinct_true_ids:
            df_has_false = df.filter((pl.col("row_id") == rid) & (~pl.col("_is_synthetic_row")))
            assert len(df_has_false) > 0, f"row_id {rid} has no False copy"

    def test_chained_resampling_preserves_incoming(self, tmp_path):
        """Running oversampling on an already-resampled artifact preserves
        the incoming _is_synthetic_row=True for previously added rows."""
        store = FsArtifactStore(tmp_path)
        frame = _make_imbalanced_frame()

        # First pass: oversample
        first_result = self._run_node(store, frame,
                                      {"strategy": "oversample_minority", "sampling_ratio": 1.0})
        first_df = _read_train(store, first_result)
        first_synthetic = int(first_df["_is_synthetic_row"].sum())
        assert first_synthetic == 60

        # Second pass: stage + publish the resampled frame as the train input.
        second_staged = store.stage_table(
            role="train",
            kind=EvidenceKind.RESAMPLING_EVIDENCE.value,
            frame=first_df,
            metadata={"source_artifact_id": "first-pass"},
        )
        store.publish(second_staged)
        second_train_art = _artifact(second_staged.provisional_artifact_id)
        second_result = self._run_node(
            store, first_df,
            {"strategy": "undersample_majority", "sampling_ratio": 0.5},
            train_artifact=second_train_art,
        )
        second_df = _read_train(store, second_result)
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

    def _run_node(self, store, frame):
        from cardre.nodes.selection import SmoteTrainingDataNode
        return _run(SmoteTrainingDataNode(), store, frame,
                    {"sampling_ratio": 1.0}, SMOTE_NODE_TYPE)

    @pytest.mark.skipif(
        not importlib.util.find_spec("imblearn"),
        reason="SMOTE requires imbalanced-learn",
    )
    def test_smote_writes_flag_column(self, tmp_path):
        store = FsArtifactStore(tmp_path)
        result = self._run_node(store, _make_imbalanced_frame())
        df = _read_train(store, result)
        assert "_is_synthetic_row" in df.columns
        assert df["_is_synthetic_row"].sum() > 0

    @pytest.mark.skipif(
        not importlib.util.find_spec("imblearn"),
        reason="SMOTE requires imbalanced-learn",
    )
    def test_smote_synthetic_matches_report(self, tmp_path):
        store = FsArtifactStore(tmp_path)
        result = self._run_node(store, _make_imbalanced_frame())
        df = _read_train(store, result)
        assert df["_is_synthetic_row"].sum() == result.metrics.get("synthetic_count", -1)
        report = _read_report(store, result)
        assert report["synthetic_rows_added"] == df["_is_synthetic_row"].sum()

    @pytest.mark.skipif(
        not importlib.util.find_spec("imblearn"),
        reason="SMOTE requires imbalanced-learn",
    )
    def test_smote_original_rows_are_false(self, tmp_path):
        store = FsArtifactStore(tmp_path)
        result = self._run_node(store, _make_imbalanced_frame())
        df = _read_train(store, result)
        n_original = 100  # original rows in fixture
        first_rows = df.head(n_original)
        assert first_rows["_is_synthetic_row"].sum() == 0
