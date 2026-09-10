"""Behavior-level regression tests for Slice 7 (#62 and #63).

Covers the public parameter / validation / result behavior of the import and
split nodes:

* ``ImportTabularDatasetNode`` must document ``max_rows`` as an explicit
  head limit (not sampling), apply it as a head limit, and surface a warning
  that states the head-limit semantics plainly.
* ``SplitTrainTestOotNode`` must not publish an empty train/test/OOT
  Artifact when a requested role cannot be populated; it must fail clearly
  before any output is published.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import polars as pl
import pytest

from cardre.adapters.filesystem.artifact_store import FsArtifactStore
from cardre.application.execution.output_publisher import StagingOutputPublisher
from cardre.domain.step import StepSpec
from cardre.nodes._params import NodeParams
from cardre.nodes.contracts import NodeContext, RuntimeMeta
from cardre.nodes.prep.import_ import ImportTabularDatasetNode
from cardre.nodes.prep.split import SplitTrainTestOotNode


class _FakeInputs:
    """Minimal InputCollection stub: returns a single role artifact and frame."""

    def __init__(self, frame: pl.DataFrame, artifact: object) -> None:
        self._frame = frame
        self._artifact = artifact

    def first(self, role: str) -> Any:
        return self._artifact

    def read_dataframe(self, artifact: Any) -> pl.DataFrame:
        return self._frame


class _FakeArtifact:
    artifact_id = "input-1"


def _context(inputs: Any, outputs: Any, params: dict, node_type: str) -> NodeContext:
    spec = StepSpec(
        step_id="prep-1",
        node_type=node_type,
        node_version="1",
        category="transform",
        params=NodeParams(params),
        params_hash="params-hash",
        parent_step_ids=[],
        canonical_step_id="prep-1",
    )
    return NodeContext(
        run_id="run-1",
        plan_version_id="plan-1",
        step_spec=spec,
        inputs=inputs,
        outputs=outputs,
        params=NodeParams(params),
        runtime=RuntimeMeta("run-1", "plan-1", "prep-1", node_type),
    )


def _write_ordered_parquet(path: Path, rows: int) -> Path:
    frame = pl.DataFrame({
        "id": list(range(rows)),
        "target": ["good" if i % 3 != 0 else "bad" for i in range(rows)],
    })
    frame.write_parquet(path)
    return path


class TestImportMaxRowsHeadLimit:
    def test_parameter_schema_documents_max_rows_as_head_limit(self):
        """The public parameter schema must name ``max_rows`` as a head limit,
        never as sampling."""
        node = ImportTabularDatasetNode()
        schema = node.parameter_schema()
        assert schema is not None
        method = schema.methods[0]
        max_rows_def = next(p for p in method.params if p.name == "max_rows")
        text = f"{max_rows_def.label} {max_rows_def.help_text}".lower()
        assert "head" in text or "first" in text, (
            "max_rows help must explicitly state it reads only the first N rows"
        )
        assert "sampling" not in text or "not sampling" in text, (
            "max_rows help must not describe it as a sampling mechanism"
        )

    def test_max_rows_reads_first_n_rows(self, tmp_path):
        """With a deterministic fixture, ``max_rows`` selects the first N rows
        (head limit) and the result carries that limit in its metadata."""
        src = _write_ordered_parquet(tmp_path / "input.parquet", rows=10)
        pub = StagingOutputPublisher(FsArtifactStore(tmp_path))
        context = _context(
            _FakeInputs(pl.DataFrame(), _FakeArtifact()),
            pub,
            {"source_path": str(src), "max_rows": 3},
            "cardre.import_dataset",
        )
        result = ImportTabularDatasetNode().run(context)
        assert len(result.staged_artifacts) == 1
        staged = result.staged_artifacts[0]
        frame = pl.read_parquet(staged.staging_path)
        assert frame.height == 3
        assert frame["id"].to_list() == [0, 1, 2]
        assert staged.metadata.get("max_rows_applied") == 3

    def test_max_rows_warning_names_head_limit(self, tmp_path):
        """The warning issued when limiting must state that only the first
        ``max_rows`` rows are imported, not that it samples the dataset."""
        src = _write_ordered_parquet(tmp_path / "input.parquet", rows=10)
        pub = StagingOutputPublisher(FsArtifactStore(tmp_path))
        context = _context(
            _FakeInputs(pl.DataFrame(), _FakeArtifact()),
            pub,
            {"source_path": str(src), "max_rows": 2},
            "cardre.import_dataset",
        )
        result = ImportTabularDatasetNode().run(context)
        codes = [w.get("code") for w in result.warnings]
        assert "SOURCE_ROW_LIMIT_APPLIED" in codes
        message = next(w["message"] for w in result.warnings
                       if w.get("code") == "SOURCE_ROW_LIMIT_APPLIED").lower()
        assert "first" in message
        assert "head" in message or "only" in message


class TestSplitNoEmptyRolePublication:
    def test_tiny_groups_fail_before_publishing_empty_roles(self, tmp_path):
        """One-row target groups cannot populate every requested role, so the
        node must raise a clear validation failure before any train/test/OOT
        Artifact is published."""
        frame = pl.DataFrame({"target": ["good", "bad"]})
        pub = StagingOutputPublisher(FsArtifactStore(tmp_path))
        inputs = _FakeInputs(frame, _FakeArtifact())
        context = _context(
            inputs,
            pub,
            {
                "train_fraction": 0.6,
                "test_fraction": 0.2,
                "oot_fraction": 0.2,
                "random_seed": 42,
                "target_column": "target",
            },
            "cardre.split_train_test_oot",
        )
        with pytest.raises(ValueError) as exc_info:
            SplitTrainTestOotNode().run(context)
        message = str(exc_info.value)
        assert "empty" in message or "cannot" in message.lower() or "too few" in message, message
        # No output Artifact may have been staged.
        assert pub.build_result().staged_artifacts == []

    def test_normal_pathway_still_publishes_all_roles(self, tmp_path):
        """A dataset large enough for every role keeps producing all three
        non-empty partitions (canonical pathway behavior preserved)."""
        rows = []
        for i in range(120):
            rows.append({"target": "good" if i % 3 != 0 else "bad"})
        frame = pl.DataFrame(rows)
        pub = StagingOutputPublisher(FsArtifactStore(tmp_path))
        inputs = _FakeInputs(frame, _FakeArtifact())
        context = _context(
            inputs,
            pub,
            {
                "train_fraction": 0.6,
                "test_fraction": 0.2,
                "oot_fraction": 0.2,
                "random_seed": 42,
                "target_column": "target",
            },
            "cardre.split_train_test_oot",
        )
        result = SplitTrainTestOotNode().run(context)
        published = {
            staged.role: pl.read_parquet(staged.staging_path)
            for staged in result.staged_artifacts
            if staged.media_type == "application/vnd.apache.parquet"
        }
        assert set(published) == {"train", "test", "oot"}
        for role in ("train", "test", "oot"):
            assert published[role].height > 0, f"{role} role is empty"
