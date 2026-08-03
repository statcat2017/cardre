"""Characterization tests for CreateComparison and RefreshComparison use cases.

Ported from tests/test_comparison_service.py to exercise the new
application-layer use cases through the production persistence stack.
"""

from __future__ import annotations

import json
import uuid

import pytest

from cardre.application.governance.create_comparison import (
    CreateComparison,
    CreateComparisonCommand,
)
from cardre.application.governance.refresh_comparison import (
    RefreshComparison,
    RefreshComparisonCommand,
)
from cardre.domain.errors import CardreError


def _stub_publisher_factory(uow_factory):
    """A publication-publisher factory for RefreshComparison tests.

    The publisher is the protocol seam only — the writer (artifact finalize)
    is supplied by the use case. Used where a test drives a real publish path
    or where the publisher is never reached (missing-comparison / not-ready
    paths).
    """
    from cardre.application.publications.publisher import PublicationPublisher

    def factory(project_id=None):
        return PublicationPublisher(lambda: uow_factory.for_project(project_id))

    return factory


class _FakeIdGenerator:
    def __init__(self):
        self._counter = 0
    def new_id(self) -> str:
        self._counter += 1
        return f"fake-id-{self._counter}"


# =========================================================================
# CreateComparison
# =========================================================================


def _seed_branch(uow, project_id, plan_id, pv_id, name="branch"):
    return uow.branches.create_branch(
        project_id=project_id, plan_id=plan_id, name=name,
        branch_type="challenger", base_plan_version_id=pv_id,
        head_plan_version_id=pv_id, created_reason="test",
    )


class TestCreateComparison:
    def test_create_comparison_success(self, provisioned_project):
        project_id, uow_factory, _, _ = provisioned_project
        with uow_factory.for_project(project_id) as uow:
            plan_id = uow.plans.create_plan(project_id, "test-plan")
            pv_id = uow.plans.create_version(plan_id, [], description="v1", is_committed=True)
            challenger_pv_id = uow.plans.create_version(plan_id, [], description="v2", is_committed=True)
            baseline_id = _seed_branch(uow, project_id, plan_id, pv_id, "baseline")
            challenger_id = _seed_branch(uow, project_id, plan_id, challenger_pv_id, "challenger")
            uow.commit()

        use_case = CreateComparison(uow_factory, _FakeIdGenerator())
        result = use_case(CreateComparisonCommand(
            project_id=project_id, plan_id=plan_id,
            baseline_branch_id=baseline_id,
            challenger_branch_ids=[challenger_id],
            created_reason="Test comparison.",
        ))

        assert result.comparison_id
        assert result.baseline_branch_id == baseline_id
        assert result.challenger_branch_ids == [challenger_id]

        with uow_factory.for_project(project_id) as uow:
            saved = uow.comparisons.get_comparison(result.comparison_id)
        assert saved is not None
        assert saved["plan_id"] == plan_id

    def test_create_comparison_missing_baseline_raises(self, provisioned_project):
        project_id, uow_factory, _, _ = provisioned_project
        use_case = CreateComparison(uow_factory, _FakeIdGenerator())
        with pytest.raises(CardreError, match="BASELINE_BRANCH_NOT_FOUND"):
            use_case(CreateComparisonCommand(
                project_id=project_id, plan_id="pl1",
                baseline_branch_id="nonexistent",
                challenger_branch_ids=[],
            ))

    def test_create_comparison_missing_challenger_raises(self, provisioned_project):
        project_id, uow_factory, _, _ = provisioned_project
        with uow_factory.for_project(project_id) as uow:
            plan_id = uow.plans.create_plan(project_id, "test-plan")
            pv_id = uow.plans.create_version(plan_id, [], description="v1", is_committed=True)
            baseline_id = _seed_branch(uow, project_id, plan_id, pv_id, "baseline")
            uow.commit()

        use_case = CreateComparison(uow_factory, _FakeIdGenerator())
        with pytest.raises(CardreError, match="CHALLENGER_BRANCH_NOT_FOUND"):
            use_case(CreateComparisonCommand(
                project_id=project_id, plan_id=plan_id,
                baseline_branch_id=baseline_id,
                challenger_branch_ids=["nonexistent"],
            ))

    def test_create_comparison_rejects_baseline_from_another_plan(self, provisioned_project):
        """A comparison must not aggregate branches from a different plan."""
        project_id, uow_factory, _, _ = provisioned_project
        with uow_factory.for_project(project_id) as uow:
            plan_a = uow.plans.create_plan(project_id, "plan-a")
            plan_b = uow.plans.create_plan(project_id, "plan-b")
            pv_a = uow.plans.create_version(plan_a, [], description="va", is_committed=True)
            pv_b = uow.plans.create_version(plan_b, [], description="vb", is_committed=True)
            baseline_a = _seed_branch(uow, project_id, plan_a, pv_a, "baseline-a")
            baseline_b = _seed_branch(uow, project_id, plan_b, pv_b, "baseline-b")
            uow.commit()

        use_case = CreateComparison(uow_factory, _FakeIdGenerator())
        with pytest.raises(CardreError, match="BRANCH_SCOPE_MISMATCH"):
            use_case(CreateComparisonCommand(
                project_id=project_id, plan_id=plan_a,
                baseline_branch_id=baseline_b,  # from plan B
                challenger_branch_ids=[],
                created_reason="Test comparison.",
            ))
        # Nothing may be persisted.
        with uow_factory.read_only(project_id) as uow:
            assert uow.comparisons.list_for_project(project_id) == []
        assert baseline_a  # sanity: branch exists in plan A

    def test_create_comparison_rejects_challenger_from_another_plan(self, provisioned_project):
        project_id, uow_factory, _, _ = provisioned_project
        with uow_factory.for_project(project_id) as uow:
            plan_a = uow.plans.create_plan(project_id, "plan-a")
            plan_b = uow.plans.create_plan(project_id, "plan-b")
            pv_a = uow.plans.create_version(plan_a, [], description="va", is_committed=True)
            pv_b = uow.plans.create_version(plan_b, [], description="vb", is_committed=True)
            baseline_a = _seed_branch(uow, project_id, plan_a, pv_a, "baseline-a")
            challenger_b = _seed_branch(uow, project_id, plan_b, pv_b, "challenger-b")
            uow.commit()

        use_case = CreateComparison(uow_factory, _FakeIdGenerator())
        with pytest.raises(CardreError, match="BRANCH_SCOPE_MISMATCH"):
            use_case(CreateComparisonCommand(
                project_id=project_id, plan_id=plan_a,
                baseline_branch_id=baseline_a,
                challenger_branch_ids=[challenger_b],
                created_reason="Test comparison.",
            ))
        with uow_factory.read_only(project_id) as uow:
            assert uow.comparisons.list_for_project(project_id) == []


# =========================================================================
# RefreshComparison
# =========================================================================


class _FakeEvidencePort:
    def find_typed(self, step_map, canonical_step_id, plan_version_id, evidence_branch_id, kinds):
        return None


class _FakeArtifactWriter:
    def __init__(self):
        self.written = []

    def write_json(self, *, artifact_type, role, stem, payload, metadata):
        artifact_id = f"art-{len(self.written)}-{uuid.uuid4().hex[:4]}"
        self.written.append(artifact_id)
        from cardre.domain.artifacts import ArtifactRef
        from cardre.domain.diagnostics import utc_now_iso
        return ArtifactRef(
            artifact_id=artifact_id, artifact_type=artifact_type, role=role,
            path=f"/tmp/{artifact_id}", physical_hash=f"phys_{artifact_id}",
            logical_hash=f"log_{artifact_id}", media_type="application/json",
            created_at=utc_now_iso(), metadata=metadata,
        )


class _PreRegisteredArtifactWriter:
    """Artifact writer backed by artifacts pre-registered before the use case runs.

    The use case holds an IMMEDIATE transaction, so we cannot open a second
    write connection mid-call. Instead, artifacts are pre-registered once,
    and write_json returns them in order.
    """

    def __init__(self, db_path, count):
        import sqlite3

        from cardre.adapters.sqlite.artifact_repo import ArtifactRepo
        from cardre.domain.artifacts import ArtifactRef
        from cardre.domain.diagnostics import utc_now_iso
        self._artifacts: list[ArtifactRef] = []
        self._idx = 0
        conn = sqlite3.connect(str(db_path), timeout=30)
        conn.row_factory = sqlite3.Row
        repo = ArtifactRepo(conn)
        for i in range(count):
            now = utc_now_iso()
            art = ArtifactRef(
                artifact_id=f"pre-art-{i}", artifact_type="branch_comparison",
                role="comparison", path=f"/tmp/pre-art-{i}",
                physical_hash=f"phys-pre-{i}", logical_hash=f"log-pre-{i}",
                media_type="application/json", created_at=now, metadata={},
            )
            repo.register(art)
            self._artifacts.append(art)
        conn.commit()
        conn.close()

    def write_json(self, *, artifact_type, role, stem, payload, metadata):
        art = self._artifacts[self._idx]
        self._idx += 1
        return art


class TestRefreshComparison:
    def test_refresh_missing_comparison_raises(self, provisioned_project):
        project_id, uow_factory, _, _ = provisioned_project
        use_case = RefreshComparison(
            uow_factory, _FakeEvidencePort(), _FakeArtifactWriter(),
            _stub_publisher_factory(uow_factory),
        )
        with pytest.raises(CardreError, match="COMPARISON_NOT_FOUND"):
            use_case(RefreshComparisonCommand(
                project_id=project_id, comparison_id="nonexistent",
            ))

    def test_refresh_not_ready_when_branch_has_missing_evidence(self, provisioned_project):
        project_id, uow_factory, _, _ = provisioned_project
        with uow_factory.for_project(project_id) as uow:
            plan_id = uow.plans.create_plan(project_id, "test-plan")
            pv_id = uow.plans.create_version(plan_id, [], description="v1", is_committed=True)
            baseline_id = _seed_branch(uow, project_id, plan_id, pv_id, "baseline")
            challenger_id = _seed_branch(uow, project_id, plan_id, pv_id, "challenger")
            comparison_id = str(uuid.uuid4())
            uow._conn.execute(
                "INSERT INTO branch_comparisons "
                "(comparison_id, project_id, plan_id, baseline_branch_id, "
                " comparison_spec_json, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                (comparison_id, project_id, plan_id, baseline_id,
                 json.dumps({"roles": ["train"]}), "2020-01-01T00:00:00Z"),
            )
            uow._conn.execute(
                "INSERT INTO comparison_challenger_branches (comparison_id, branch_id, position) "
                "VALUES (?, ?, ?)",
                (comparison_id, challenger_id, 0),
            )
            uow.commit()

        use_case = RefreshComparison(
            uow_factory, _FakeEvidencePort(), _FakeArtifactWriter(),
            _stub_publisher_factory(uow_factory),
        )
        result = use_case(RefreshComparisonCommand(
            project_id=project_id, comparison_id=comparison_id,
        ))

        assert result.ready is False
        assert result.blocked_reason is not None
        assert len(result.missing_or_stale) > 0

    def test_refresh_ready_challenger_publishes_and_persists_artifact(
        self, provisioned_project, monkeypatch,
    ):
        from cardre.adapters.evidence.comparison_reader import _comparison_payload
        from cardre.adapters.evidence.parsers import get_adapter
        from cardre.adapters.filesystem.artifact_store import FsArtifactStore
        from cardre.domain.artifacts import ArtifactRef
        from cardre.domain.evidence.kinds import EvidenceKind
        from cardre.modeling.schema import MODEL_ARTIFACT_SCHEMA_VERSION

        project_id, uow_factory, _, root = provisioned_project
        with uow_factory.for_project(project_id) as uow:
            plan_id = uow.plans.create_plan(project_id, "test-plan")
            pv_id = uow.plans.create_version(plan_id, [], description="v1", is_committed=True)
            challenger_pv_id = uow.plans.create_version(plan_id, [], description="v2", is_committed=True)
            baseline_id = _seed_branch(uow, project_id, plan_id, pv_id, "baseline")
            challenger_id = _seed_branch(uow, project_id, plan_id, challenger_pv_id, "challenger")
            comparison_id = str(uuid.uuid4())
            uow._conn.execute(
                "INSERT INTO branch_comparisons "
                "(comparison_id, project_id, plan_id, baseline_branch_id, comparison_spec_json, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (comparison_id, project_id, plan_id, baseline_id, json.dumps({"include_model": True}), "2020-01-01T00:00:00Z"),
            )
            uow._conn.execute(
                "INSERT INTO comparison_challenger_branches (comparison_id, branch_id, position) "
                "VALUES (?, ?, 0)",
                (comparison_id, challenger_id),
            )
            uow.commit()

        def canonical_model(coefficient):
            return {
                "schema_version": MODEL_ARTIFACT_SCHEMA_VERSION,
                "model_family": "logistic_regression",
                "target_column": "defaulted",
                "target_event_value": "1",
                "class_mapping": {"0": "0", "1": "1"},
                "probability_column_index": 1,
                "feature_contract": {"features": ["income"]},
                "training": {"row_count": 10},
                "model_payload": {"coefficients": {"income": coefficient}, "intercept": -0.2},
            }

        baseline_path = root / "baseline-model.json"
        challenger_path = root / "challenger-model.json"
        baseline_path.write_text(json.dumps(canonical_model(0.1)), encoding="utf-8")
        challenger_path.write_text(json.dumps(canonical_model(0.3)), encoding="utf-8")

        class CanonicalModelEvidencePort:
            def find_typed(self, step_map, canonical_step_id, plan_version_id, evidence_branch_id, kinds):
                if EvidenceKind.MODEL_ARTIFACT not in kinds:
                    return None
                path = baseline_path if plan_version_id == pv_id else challenger_path
                artifact = ArtifactRef(
                    artifact_id="model-artifact", artifact_type="model", role="model",
                    path=str(path), physical_hash="model-hash", logical_hash="model-logical",
                    metadata={"schema_version": MODEL_ARTIFACT_SCHEMA_VERSION},
                )
                parsed = get_adapter(EvidenceKind.MODEL_ARTIFACT).parse(path, artifact, FsArtifactStore(root))
                return _comparison_payload(parsed)

        monkeypatch.setattr(
            RefreshComparison, "_check_readiness",
            lambda self, uow, branch_id, plan_version_id, is_baseline=False: [],
        )
        result = RefreshComparison(
            uow_factory, CanonicalModelEvidencePort(), FsArtifactStore(root),
            _stub_publisher_factory(uow_factory),
        )(RefreshComparisonCommand(project_id=project_id, comparison_id=comparison_id))

        assert result.ready is True
        assert result.comparison_artifact_id is not None
        with uow_factory.read_only(project_id) as uow:
            artifact = uow.artifacts.get(result.comparison_artifact_id)
            snapshot = uow.comparisons.get_comparison_snapshot(result.comparison_snapshot_id)
        assert artifact is not None
        assert snapshot["comparison_artifact_id"] == artifact.artifact_id
        assert artifact.metadata["schema_version"] == "cardre.comparison_artifact.v1"
        assert FsArtifactStore(root).resolve_path(artifact).exists()
        content = json.loads(FsArtifactStore(root).read_bytes(artifact))
        variable = content["model"]["variables"][0]
        assert variable["baseline"]["coefficient"] == 0.1
        assert variable["challengers"][challenger_id]["coefficient"] == 0.3
        assert variable["difference"]["coefficient_delta_vs_baseline"] == pytest.approx(0.2)

    def test_refresh_rolls_back_on_challenger_failure(
        self, provisioned_project, monkeypatch,
    ):
        project_id, uow_factory, _, root = provisioned_project
        with uow_factory.for_project(project_id) as uow:
            plan_id = uow.plans.create_plan(project_id, "test-plan")
            pv_id = uow.plans.create_version(plan_id, [], description="v1", is_committed=True)
            baseline_id = _seed_branch(uow, project_id, plan_id, pv_id, "baseline")
            challenger_pv_ids = [
                uow.plans.create_version(plan_id, [], description=f"chall-v{i}", is_committed=True)
                for i in range(2)
            ]
            challenger_ids = []
            for i, cpv in enumerate(challenger_pv_ids):
                cid = uow.branches.create_branch(
                    project_id=project_id, plan_id=plan_id, name=f"challenger-{i}",
                    branch_type="challenger", base_plan_version_id=pv_id,
                    head_plan_version_id=cpv, created_reason="Challenger.",
                )
                challenger_ids.append(cid)
            comparison_id = str(uuid.uuid4())
            uow._conn.execute(
                "INSERT INTO branch_comparisons "
                "(comparison_id, project_id, plan_id, baseline_branch_id, "
                " comparison_spec_json, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                (comparison_id, project_id, plan_id, baseline_id,
                 json.dumps({"roles": ["train"]}), "2020-01-01T00:00:00Z"),
            )
            for i, cid in enumerate(challenger_ids):
                uow._conn.execute(
                    "INSERT INTO comparison_challenger_branches (comparison_id, branch_id, position) "
                    "VALUES (?, ?, ?)",
                    (comparison_id, cid, i),
                )
            uow.commit()

        from cardre.adapters.filesystem.artifact_store import FsArtifactStore

        writer = FsArtifactStore(root)
        use_case = RefreshComparison(
            uow_factory, _FakeEvidencePort(), writer,
            _stub_publisher_factory(uow_factory),
        )

        original_build = use_case._build_content
        call_count = {"n": 0}

        def _failing_build(*args, **kwargs):
            call_count["n"] += 1
            if call_count["n"] == 2:
                raise RuntimeError("Simulated challenger failure")
            return original_build(*args, **kwargs)

        monkeypatch.setattr(use_case, "_build_content", _failing_build)
        monkeypatch.setattr(
            "cardre.application.governance.refresh_comparison.RefreshComparison._check_readiness",
            lambda self, uow, branch_id, plan_version_id, is_baseline=False: [],
        )

        with pytest.raises(RuntimeError, match="Simulated challenger failure"):
            use_case(RefreshComparisonCommand(
                project_id=project_id, comparison_id=comparison_id,
            ))

        with uow_factory.for_project(project_id) as uow:
            comparison = uow.comparisons.get_comparison(comparison_id)
            assert comparison["latest_snapshot_id"] is None
            snapshots = uow._conn.execute(
                "SELECT COUNT(*) FROM branch_comparison_snapshots WHERE comparison_id = ?",
                (comparison_id,),
            ).fetchone()[0]
            assert snapshots == 0
