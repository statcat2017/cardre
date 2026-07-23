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
            baseline_id = _seed_branch(uow, project_id, plan_id, pv_id, "baseline")
            challenger_id = _seed_branch(uow, project_id, plan_id, pv_id, "challenger")
            uow.commit()

        use_case = CreateComparison(uow_factory)
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
        use_case = CreateComparison(uow_factory)
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

        use_case = CreateComparison(uow_factory)
        with pytest.raises(CardreError, match="CHALLENGER_BRANCH_NOT_FOUND"):
            use_case(CreateComparisonCommand(
                project_id=project_id, plan_id=plan_id,
                baseline_branch_id=baseline_id,
                challenger_branch_ids=["nonexistent"],
            ))


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
        use_case = RefreshComparison(uow_factory, _FakeEvidencePort(), _FakeArtifactWriter())
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

        use_case = RefreshComparison(uow_factory, _FakeEvidencePort(), _FakeArtifactWriter())
        result = use_case(RefreshComparisonCommand(
            project_id=project_id, comparison_id=comparison_id,
        ))

        assert result.ready is False
        assert result.blocked_reason is not None
        assert len(result.missing_or_stale) > 0

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

        writer = _PreRegisteredArtifactWriter(root / "project.sqlite", count=2)
        use_case = RefreshComparison(uow_factory, _FakeEvidencePort(), writer)

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
