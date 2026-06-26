"""Tests for sidecar/routes/evidence.py — DTO contract and field wiring."""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from cardre.store import ProjectStore

import pytest

from cardre.evidence import ArtifactEvidenceReader
from sidecar.routes.evidence import _to_item, _derive_step_status
from sidecar.models import EvidenceStatus, RunStepEvidenceItem


def _init_store(tmp: str) -> ProjectStore:
    from cardre.store import ProjectStore
    store = ProjectStore(Path(tmp))
    store.initialize()
    return store


def _make_run_with_artifact(tmp: str) -> tuple:
    """Create a minimal store with one run step that produces a WOE/IV artifact.

    Returns (store, prj_id, run_id, step_id, artifact_id).
    """
    import uuid
    from cardre.audit import StepSpec, utc_now_iso
    from cardre.artifacts import write_json_artifact
    from cardre.store import ProjectStore

    store = _init_store(tmp)
    prj_id = store.create_project("Test Project")
    plan_id = store.create_plan(prj_id, "Test Plan")
    step = StepSpec(
        "woe-step-1", "cardre.woe_iv", "", "build",
        {}, "", [], "baseline", 1, canonical_step_id="final-woe-iv",
    )
    pv_id = store.create_plan_version(plan_id, steps=[step])

    branch_id = str(uuid.uuid4())
    store._connect().execute(
        "INSERT INTO plan_branches (branch_id, plan_id, project_id, name, branch_type, "
        "base_plan_version_id, head_plan_version_id, created_at, updated_at, created_reason) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (branch_id, plan_id, prj_id, "Branch", "baseline", pv_id, pv_id,
         utc_now_iso(), utc_now_iso(), "test"),
    )
    store._connect().commit()

    run_id = store.create_run(plan_version_id=pv_id)
    art_ref = write_json_artifact(
        store, artifact_type="woe-iv-evidence", role="train",
        stem="test-woe",
        payload={"variables": [], "schema_version": "cardre.woe_iv_evidence.v1"},
        metadata={"schema_version": "cardre.woe_iv_evidence.v1"},
    )
    art_id = art_ref.artifact_id

    rs_id = str(uuid.uuid4())
    with store.transaction() as conn:
            conn.execute(
                "INSERT INTO run_steps (run_step_id, run_id, step_id, plan_version_id, "
                "status, output_artifact_ids_json, input_artifact_ids_json, execution_fingerprint_json, started_at, finished_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (rs_id, run_id, "woe-step-1", pv_id, "succeeded",
                 f'["{art_id}"]', '[]', '{"params_hash":"","output_artifact_logical_hashes":[]}',
                 utc_now_iso(), utc_now_iso()),
            )

    store.finish_run(run_id, status="succeeded")
    return store, prj_id, run_id, "woe-step-1", art_id


class TestToItem:
    """Tests for _to_item() — the DTO constructor function."""

    def test_source_step_id_equals_run_step_id(self):
        with tempfile.TemporaryDirectory() as tmp:
            store, prj_id, run_id, step_id, art_id = _make_run_with_artifact(tmp)
            reader = ArtifactEvidenceReader(store)

            item = _to_item(store, reader, art_id, run_step_id=step_id)
            assert item.source_step_id == step_id, (
                f"Expected source_step_id={step_id!r}, got {item.source_step_id!r}"
            )

    def test_canonical_step_id_not_evidence_kind(self):
        with tempfile.TemporaryDirectory() as tmp:
            store, prj_id, run_id, step_id, art_id = _make_run_with_artifact(tmp)
            reader = ArtifactEvidenceReader(store)

            item = _to_item(store, reader, art_id,
                            run_step_id=step_id,
                            canonical_step_id="final-woe-iv")
            assert item.canonical_step_id == "final-woe-iv"
            if item.evidence_kind:
                assert item.canonical_step_id != item.evidence_kind, (
                    "canonical_step_id must not equal evidence_kind"
                )

    def test_missing_artifact_returns_missing_status(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = _init_store(tmp)
            reader = ArtifactEvidenceReader(store)

            item = _to_item(store, reader, "nonexistent")
            assert item.status == EvidenceStatus.MISSING
            assert item.artifact_type == ""

    def test_unsupported_kind_returns_unsupported_status(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = _init_store(tmp)
            prj_id = store.create_project("Test")
            from cardre.audit import StepSpec, utc_now_iso
            from cardre.artifacts import write_json_artifact
            import uuid

            plan_id = store.create_plan(prj_id, "Test Plan")
            step = StepSpec(
                "exotic-step", "cardre.exotic", "", "build",
                {}, "", [], "baseline", 1, canonical_step_id="exotic",
            )
            pv_id = store.create_plan_version(plan_id, steps=[step])
            run_id = store.create_run(pv_id)
            art_ref = write_json_artifact(
                store, artifact_type="exotic-thing", role="train",
                stem="test-exotic", payload={"weird": True},
                metadata={"evidence_kind": "exotic-thing"},
            )
            art_id = art_ref.artifact_id

            rs_id = str(uuid.uuid4())
            with store.transaction() as conn:
                conn.execute(
                    "INSERT INTO run_steps (run_step_id, run_id, step_id, plan_version_id, "
                    "status, output_artifact_ids_json, input_artifact_ids_json, execution_fingerprint_json, started_at, finished_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (rs_id, run_id, "exotic-step", pv_id, "succeeded",
                     f'["{art_id}"]', '[]', '{"params_hash":"","output_artifact_logical_hashes":[]}',
                     utc_now_iso(), utc_now_iso()),
                )
            store.finish_run(run_id, status="succeeded")

            reader = ArtifactEvidenceReader(store)
            item = _to_item(store, reader, art_id, run_step_id="exotic-step")
            assert item.status == EvidenceStatus.UNSUPPORTED

    def test_summary_woe_iv_artifact(self):
        with tempfile.TemporaryDirectory() as tmp:
            store, prj_id, run_id, step_id, art_id = _make_run_with_artifact(tmp)
            reader = ArtifactEvidenceReader(store)
            item = _to_item(store, reader, art_id, run_step_id=step_id)
            assert item.summary is not None
            assert isinstance(item.summary, dict)
            assert item.evidence_kind is not None

    def test_summary_woe_iv_meaningful_values(self):
        """Summary must contain non-default values from the artifact payload."""
        import tempfile
        import uuid
        from pathlib import Path
        from cardre.store import ProjectStore
        from cardre.audit import StepSpec, utc_now_iso
        from cardre.artifacts import write_json_artifact
        from cardre.evidence import ArtifactEvidenceReader

        with tempfile.TemporaryDirectory() as tmp:
            store = ProjectStore(Path(tmp))
            store.initialize()
            prj_id = store.create_project("Test Project")
            plan_id = store.create_plan(prj_id, "Test Plan")
            step = StepSpec(
                "woe-step-2", "cardre.woe_iv", "", "build",
                {}, "", [], "baseline", 1, canonical_step_id="final-woe-iv",
            )
            pv_id = store.create_plan_version(plan_id, steps=[step])

            branch_id = str(uuid.uuid4())
            store._connect().execute(
                "INSERT INTO plan_branches (branch_id, plan_id, project_id, name, branch_type, "
                "base_plan_version_id, head_plan_version_id, created_at, updated_at, created_reason) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (branch_id, plan_id, prj_id, "Branch", "baseline", pv_id, pv_id,
                 utc_now_iso(), utc_now_iso(), "test"),
            )
            store._connect().commit()

            run_id = store.create_run(plan_version_id=pv_id)
            art_ref = write_json_artifact(
                store, artifact_type="woe-iv-evidence", role="train",
                stem="test-woe-meaningful",
                payload={
                    "variables": [
                        {"variable_name": "income_band", "iv": 0.42, "status": "included",
                         "bins": [{"bin_id": "b1"}]},
                        {"variable_name": "age_band", "iv": 0.31, "status": "included",
                         "bins": [{"bin_id": "b1"}]},
                    ],
                    "schema_version": "cardre.woe_iv_evidence.v1",
                },
                metadata={"schema_version": "cardre.woe_iv_evidence.v1"},
            )
            art_id = art_ref.artifact_id

            rs_id = str(uuid.uuid4())
            with store.transaction() as conn:
                conn.execute(
                    "INSERT INTO run_steps (run_step_id, run_id, step_id, plan_version_id, "
                    "status, output_artifact_ids_json, input_artifact_ids_json, execution_fingerprint_json, started_at, finished_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (rs_id, run_id, "woe-step-2", pv_id, "succeeded",
                     f'["{art_id}"]', '[]', '{"params_hash":"","output_artifact_logical_hashes":[]}',
                     utc_now_iso(), utc_now_iso()),
                )
            store.finish_run(run_id, status="succeeded")

            reader = ArtifactEvidenceReader(store)
            item = _to_item(store, reader, art_id, run_step_id="woe-step-2")
            assert item.summary is not None
            assert item.summary.get("selected_variable_count") == 2, (
                f"Expected 2 variables, got {item.summary.get('selected_variable_count')}"
            )
            assert item.summary.get("iv_max") == 0.42, (
                f"Expected iv_max=0.42, got {item.summary.get('iv_max')}"
            )
            top = item.summary.get("top_variables", [])
            assert len(top) >= 1
            assert top[0]["name"] == "income_band"
            assert top[0]["iv"] == 0.42


class TestDeriveStepStatus:
    """Tests for _derive_step_status() — response-level status aggregation."""

    def test_empty_items_returns_missing(self):
        assert _derive_step_status([]) == EvidenceStatus.MISSING

    def test_stale_overrides_partial(self):
        items = [
            RunStepEvidenceItem(artifact_id="a", artifact_type="t",
                                status=EvidenceStatus.STALE),
            RunStepEvidenceItem(artifact_id="b", artifact_type="t",
                                status=EvidenceStatus.UNSUPPORTED),
        ]
        assert _derive_step_status(items) == EvidenceStatus.STALE

    def test_mixed_unsupported_returns_partial(self):
        items = [
            RunStepEvidenceItem(artifact_id="a", artifact_type="t",
                                status=EvidenceStatus.AVAILABLE),
            RunStepEvidenceItem(artifact_id="b", artifact_type="t",
                                status=EvidenceStatus.UNSUPPORTED),
        ]
        assert _derive_step_status(items) == EvidenceStatus.PARTIAL

    def test_all_available_returns_available(self):
        items = [
            RunStepEvidenceItem(artifact_id="a", artifact_type="t",
                                status=EvidenceStatus.AVAILABLE),
            RunStepEvidenceItem(artifact_id="b", artifact_type="t",
                                status=EvidenceStatus.AVAILABLE),
        ]
        assert _derive_step_status(items) == EvidenceStatus.AVAILABLE
