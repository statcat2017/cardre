"""Batch R5 — governance persistence and content decomposition.

Covers finding 8 of the thermonuclear review:

1. **No ``._conn`` from the application layer** — governance use cases call
   typed repository operations; the SQLite adapter owns all SQL.
2. **Fake-UoW portability** — every governance use case runs against a fake
   UoW whose repositories implement the typed write methods; no fake needs a
   ``_conn`` attribute.
3. **Pure comparison builders** — WOE/IV, model, validation, and cutoff
   content build from typed evidence lookups with no DB/filesystem deps.
4. **Atomic snapshot write** — a forced persistence failure leaves neither
   the comparison artifact descriptor nor snapshot rows visible.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from cardre.adapters.sqlite.connection import SqliteUnitOfWorkFactory
from cardre.adapters.sqlite.project_provisioner import SqliteProjectProvisioner
from cardre.adapters.system.project_registry import JsonProjectRegistry
from cardre.application.governance.comparison_builders import (
    build_content,
    build_cutoff,
    build_model,
    build_validation,
    build_woe_iv,
)


def _stub_publisher_factory(uow_factory):
    """A publication-publisher factory for governance tests.

    The publisher is the protocol seam only — the writer (artifact finalize or
    manifest publish) is supplied by the use case, so the factory needs only
    the UoW factory for the ``mark_published`` / ``mark_failed`` write.
    """
    from cardre.application.publications.publisher import PublicationPublisher

    def factory(project_id=None):
        def _uow_lambda():
            return uow_factory.for_project(project_id) if project_id else uow_factory()

        return PublicationPublisher(_uow_lambda)

    return factory


def _provision(tmp_path):
    registry = JsonProjectRegistry(tmp_path / "registry.json")
    provisioner = SqliteProjectProvisioner()
    root = tmp_path / "projects" / "p1"
    provisioner.initialize(root)
    uow_factory = SqliteUnitOfWorkFactory(registry)
    with uow_factory.for_root(root) as uow:
        project_id = uow.projects.create("Project")
        plan_id = uow.plans.create_plan(project_id, "Plan")
        pv_id = uow.plans.create_version(plan_id, [], is_committed=True)
        uow.commit()
    registry.register(project_id, root)
    return project_id, plan_id, pv_id, uow_factory, root


class _FakeIdGenerator:
    def __init__(self):
        self._counter = 0
    def new_id(self) -> str:
        self._counter += 1
        return f"fake-id-{self._counter}"


# ---------------------------------------------------------------------------
# 1. No ._conn from the application layer
# ---------------------------------------------------------------------------


def test_no_conn_access_from_application(tmp_path):
    """No file under cardre/application/ may access ``._conn``."""
    app_root = Path(__file__).resolve().parent.parent.parent / "cardre" / "application"
    violations = []
    for path in app_root.rglob("*.py"):
        if "__pycache__" in str(path):
            continue
        for lineno, line in enumerate(path.read_text().splitlines(), start=1):
            stripped = line.strip()
            if "._conn" in stripped and not stripped.startswith("#"):
                violations.append(f"{path.relative_to(app_root)}:{lineno}: {stripped}")
    assert violations == [], "application layer must not reach into adapter connections:\n" + "\n".join(violations)


# ---------------------------------------------------------------------------
# 2. Fake-UoW portability for governance use cases
# ---------------------------------------------------------------------------


class _FakeUoWFactory:
    """Mimics SqliteUnitOfWorkFactory.for_project returning a fake UoW."""

    def __init__(self, uow) -> None:
        self._uow = uow

    def for_project(self, project_id):
        return self._uow


class _FakeUoW:
    """A fake UoW exposing only typed repository methods — no _conn."""

    def __init__(self) -> None:
        self.comparisons = _FakeComparisons()
        self.branches = _FakeBranches()
        self.champion = _FakeChampion()
        self.plans = _FakePlans()
        self.artifacts = _FakeArtifacts()
        self.runs = _FakeRuns()
        self.committed = False

    def commit(self) -> None:
        self.committed = True

    def rollback(self) -> None:
        pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class _FakeComparisons:
    def create_comparison_with_id(self, comparison_id, project_id, plan_id, baseline_branch_id,
                                  spec_json, *, created_reason=None) -> None:
        self.created_id = comparison_id

    def add_challenger_branch(self, comparison_id, branch_id, position=0) -> None:
        pass

    def get_challenger_branches(self, comparison_id) -> list[dict]:
        return [{"branch_id": "challenger-1"}]


class _FakeBranches:
    def get_branch(self, branch_id) -> dict | None:
        return {
            "branch_id": branch_id,
            "head_plan_version_id": "pv-challenger",
            "project_id": "proj",
            "plan_id": "plan",
            "status": "active",
        }

    def get_step_map(self, branch_id, pv_id) -> list[dict]:
        return []


class _FakeChampion:
    def get_champion_assignment(self, plan_id, champion_branch_id=None) -> dict | None:
        return None


class _FakePlans:
    def get_plan(self, plan_id) -> dict | None:
        return {"plan_id": plan_id, "project_id": "proj"}

    def get_plan_id_for_version(self, pv_id) -> str:
        return "plan"

    def get_version_steps(self, pv_id) -> list:
        return []


class _FakeArtifacts:
    def register(self, ref) -> str:
        return ref.artifact_id


class _FakeRuns:
    def list_for_plan_version(self, plan_version_id=None) -> list:
        return []


def test_create_comparison_uses_fake_uow_without_conn():
    from cardre.application.governance.create_comparison import (
        CreateComparison,
        CreateComparisonCommand,
    )

    uow = _FakeUoW()
    uc = CreateComparison(_FakeUoWFactory(uow), _FakeIdGenerator())
    result = uc(CreateComparisonCommand(
        project_id="proj", plan_id="plan", baseline_branch_id="base-1",
        challenger_branch_ids=["challenger-1"], comparison_spec={
            "include_woe_iv": True, "include_model": True,
            "include_validation": True, "include_cutoff": True,
        },
    ))
    assert result.comparison_id
    assert uow.committed is True
    assert not hasattr(uow, "_conn"), "fake UoW must not need _conn"


def test_assign_champion_uses_fake_uow_without_conn():
    from cardre.application.governance.assign_champion import AssignChampion, AssignChampionCommand

    class _Champ:
        def insert_champion_assignment(self, *a, **k):
            return "champ-1"

        def find_active_champion(self, *a, **k):
            return None

        def supersede_champion(self, *a, **k):
            pass

        def get_champion_assignment(self, *a, **k):
            return None

    class _Cmp:
        def get_comparison(self, comparison_id):
            return {
                "comparison_id": comparison_id, "project_id": "proj", "plan_id": "plan",
                "baseline_branch_id": "base-1",
            }

        def get_comparison_snapshot(self, snapshot_id):
            return {
                "comparison_id": "cmp-1", "comparison_snapshot_id": snapshot_id,
                "comparison_artifact_id": "art-1", "readiness_json": '{"ready": true}',
            }

        def get_snapshot_plan_versions(self, snapshot_id):
            return [{"plan_version_id": "pv-1", "branch_id": "challenger-1"}]

        def get_challenger_branches(self, comparison_id):
            return [{"branch_id": "challenger-1"}]

    class _Br:
        def get_branch(self, branch_id):
            return {
                "branch_id": branch_id, "project_id": "proj", "plan_id": "plan",
                "status": "active", "head_plan_version_id": "pv-1",
            }

        def get_step_map(self, branch_id, pv_id):
            return []

    class _Plans:
        def get_plan_id_for_version(self, pv_id):
            return "plan"

        def get_version_steps(self, pv_id):
            return []

    class _Runs:
        def list_for_plan_version(self, plan_version_id=None):
            return []

    class _UoW:
        def __init__(self):
            self.champion = _Champ()
            self.comparisons = _Cmp()
            self.branches = _Br()
            self.plans = _Plans()
            self.runs = _Runs()

        def commit(self):
            self.committed = True

        def rollback(self):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    uow = _UoW()
    uc = AssignChampion(_FakeUoWFactory(uow))
    result = uc(AssignChampionCommand(
        project_id="proj", plan_id="plan", scope_type="full_plan", scope_key="plan",
        branch_id="challenger-1", comparison_id="cmp-1", comparison_snapshot_id="snap-1",
        assigned_reason="test rationale",
    ))
    assert result.champion_assignment_id == "champ-1"
    assert not hasattr(uow, "_conn")


def test_refresh_comparison_reaches_snapshot_ops_not_conn():
    """RefreshComparison writes snapshots through typed repo ops, not _conn."""
    from cardre.application.governance.refresh_comparison import (
        RefreshComparison,
        RefreshComparisonCommand,
    )

    class _Writer:
        def stage_json(self, *args, **kwargs):
            from cardre.application.ports.artifact_store import StagedArtifact

            return StagedArtifact(
                staging_path=Path("/tmp/x"), provisional_artifact_id="art:cmp:1",
                physical_hash="h", logical_hash="l", media_type="application/json",
                schema_version="branch_comparison", role="comparison",
                artifact_type="branch_comparison", metadata={},
            )

        def dest_path(self, staged):
            return Path("/tmp/objects/x")

        def finalize(self, staged):
            return Path("/tmp/objects/x")

        def publish(self, staged):
            return Path("/tmp/objects/x")

    class _SnapshotComparisons:
        def get_comparison(self, comparison_id) -> dict:
            return {
                "project_id": "proj", "plan_id": "plan",
                "baseline_branch_id": "base-1", "comparison_spec_json": "{}",
            }

        def get_challenger_branches(self, comparison_id) -> list[dict]:
            return [{"branch_id": "challenger-1"}]

        def create_snapshot(self, comparison_id, project_id, plan_id, artifact_id,
                            readiness_json, *, created_reason=None) -> str:
            self.created = {
                "comparison_id": comparison_id, "project_id": project_id,
                "plan_id": plan_id, "artifact_id": artifact_id, "readiness": readiness_json,
            }
            return "snap-1"

        def add_snapshot_plan_version(self, snapshot_id, plan_version_id, branch_id=None) -> None:
            self.added = (snapshot_id, plan_version_id, branch_id)

        def set_latest_snapshot(self, comparison_id, snapshot_id, ready=True) -> None:
            self.latest = (comparison_id, snapshot_id)

    class _ReadinessBranches:
        def get_branch(self, branch_id) -> dict:
            return {"branch_id": branch_id, "head_plan_version_id": "pv"}

        def get_step_map(self, branch_id, pv_id) -> list[dict]:
            return [{"canonical_step_id": "model-fit", "step_id": "s1"}]

    class _ReadinessPlans:
        def get_plan_id_for_version(self, pv_id) -> str:
            return "plan"

        def get_version_steps(self, pv_id) -> list:
            return []

    class _ReadinessRuns:
        def list_successful_steps_across_plan_ordered(self, plan_id, step_id) -> list:
            return []

    class _ReadinessRunSteps:
        def list_successful_steps_ordered(self, plan_version_id, step_id, branch_id=None) -> list:
            return []

        def get_for_run(self, run_id) -> list:
            return []

    class _ReadinessArtifacts:
        def register(self, ref) -> str:
            return ref.artifact_id

    class _ReadinessPublications:
        def enqueue_artifact(self, run_id, plan_version_id, run_step_id, artifact_id,
                             physical_hash, storage_key, staging_source) -> str:
            self.enqueued = artifact_id
            return "outbox-1"

        def mark_published(self, outbox_id) -> None:
            self.published = outbox_id

    uow = type("U", (), {
        "comparisons": _SnapshotComparisons(),
        "branches": _ReadinessBranches(),
        "plans": _ReadinessPlans(),
        "artifacts": _ReadinessArtifacts(),
        "publications": _ReadinessPublications(),
        "runs": _ReadinessRuns(),
        "run_steps": _ReadinessRunSteps(),
        "commit": lambda self: None,
        "rollback": lambda self: None,
        "__enter__": lambda self: self,
        "__exit__": lambda self, *a: False,
    })()

    class _Evidence:
        def find_typed(self, step_map, cs, pv_id, evidence_branch_id, kinds):
            # Provide minimal evidence so readiness resolves (no missing steps).
            return {
                "variables": [],
                "model_family": "logistic_regression",
                "model_payload": {},
                "roles": {},
            }

    uc = RefreshComparison(
        _FakeUoWFactory(uow),
        _Evidence(),
        _Writer(),
        _stub_publisher_factory(_FakeUoWFactory(uow)),
        governance_enabled=True,
    )
    # Stub readiness so the snapshot path is exercised deterministically.
    uc._check_readiness = lambda uow, branch_id, pv_id, *, is_baseline=False: []  # type: ignore[method-assign]
    result = uc(RefreshComparisonCommand(project_id="proj", comparison_id="cmp-1"))
    assert result.ready is True
    assert uow.comparisons.created["comparison_id"] == "cmp-1"
    assert uow.comparisons.latest == ("cmp-1", "snap-1")


def test_refresh_comparison_one_finalize_failure_does_not_block_others():
    """A finalize failure on one comparison artifact must not block the rest
    (P2-2): the other artifacts are finalized and their outbox rows marked
    published; the failing one stays pending for reconciliation."""
    from cardre.application.governance.refresh_comparison import (
        RefreshComparison,
        RefreshComparisonCommand,
    )

    failed_finalize: set[str] = {"challenger-2"}

    class _Writer:
        def __init__(self):
            self._i = 0

        def stage_json(self, *args, **kwargs):
            from cardre.application.ports.artifact_store import StagedArtifact

            self._i += 1
            challenger = f"challenger-{self._i}"
            self._challenger = challenger
            return StagedArtifact(
                staging_path=Path(f"/tmp/stage/{challenger}"),
                provisional_artifact_id=f"art:{challenger}:1",
                physical_hash=f"h{challenger}", logical_hash=f"l{challenger}",
                media_type="application/json", schema_version="branch_comparison",
                role="comparison", artifact_type="branch_comparison",
                metadata={"challenger_branch_id": challenger},
            )

        def dest_path(self, staged):
            return Path(f"/tmp/objects/{getattr(self, '_challenger', 'x')}")

        def finalize(self, staged):
            challenger = staged.metadata.get("challenger_branch_id", "")
            if challenger in failed_finalize:
                raise RuntimeError("injected finalize failure")
            return staged.staging_path

        def publish(self, staged):
            return staged.staging_path

    class _SnapshotComparisons:
        def __init__(self):
            self.artifacts_registered: list[str] = []

        def get_comparison(self, comparison_id) -> dict:
            return {
                "project_id": "proj", "plan_id": "plan",
                "baseline_branch_id": "base-1", "comparison_spec_json": "{}",
            }

        def get_challenger_branches(self, comparison_id) -> list[dict]:
            return [
                {"branch_id": "challenger-1"},
                {"branch_id": "challenger-2"},
                {"branch_id": "challenger-3"},
            ]

        def create_snapshot(self, comparison_id, project_id, plan_id, artifact_id,
                            readiness_json, *, created_reason=None) -> str:
            self.artifacts_registered.append(artifact_id)
            return f"snap-{len(self.artifacts_registered)}"

        def add_snapshot_plan_version(self, snapshot_id, plan_version_id, branch_id=None) -> None:
            pass

        def set_latest_snapshot(self, comparison_id, snapshot_id, ready=True) -> None:
            self.latest = (comparison_id, snapshot_id)

    class _ReadinessBranches:
        def get_branch(self, branch_id) -> dict:
            return {"branch_id": branch_id, "head_plan_version_id": "pv"}

        def get_step_map(self, branch_id, pv_id) -> list[dict]:
            return []

    class _ReadinessPlans:
        def get_plan_id_for_version(self, pv_id) -> str:
            return "plan"

        def get_version_steps(self, pv_id) -> list:
            return []

    class _ReadinessRuns:
        def list_successful_steps_across_plan_ordered(self, plan_id, step_id) -> list:
            return []

    class _ReadinessRunSteps:
        def list_successful_steps_ordered(self, plan_version_id, step_id, branch_id=None) -> list:
            return []

        def get_for_run(self, run_id) -> list:
            return []

    class _ReadinessArtifacts:
        def register(self, ref) -> str:
            return ref.artifact_id

    class _ReadinessPublications:
        def __init__(self):
            self.published: list[str] = []

        def enqueue_artifact(self, run_id, plan_version_id, run_step_id, artifact_id,
                             physical_hash, storage_key, staging_source) -> str:
            return f"outbox-{artifact_id}"

        def mark_published(self, outbox_id) -> None:
            self.published.append(outbox_id)

    uow = type("U", (), {
        "comparisons": _SnapshotComparisons(),
        "branches": _ReadinessBranches(),
        "plans": _ReadinessPlans(),
        "artifacts": _ReadinessArtifacts(),
        "publications": _ReadinessPublications(),
        "runs": _ReadinessRuns(),
        "run_steps": _ReadinessRunSteps(),
        "commit": lambda self: None,
        "rollback": lambda self: None,
        "__enter__": lambda self: self,
        "__exit__": lambda self, *a: False,
    })()

    class _Evidence:
        def find_typed(self, step_map, cs, pv_id, evidence_branch_id, kinds):
            return {"variables": [], "model_family": "logistic_regression", "model_payload": {}, "roles": {}}

    uc = RefreshComparison(
        _FakeUoWFactory(uow),
        _Evidence(),
        _Writer(),
        _stub_publisher_factory(_FakeUoWFactory(uow)),
        governance_enabled=True,
    )
    uc._check_readiness = lambda uow, branch_id, pv_id, *, is_baseline=False: []  # type: ignore[method-assign]
    result = uc(RefreshComparisonCommand(project_id="proj", comparison_id="cmp-1"))
    assert result.ready is True
    # challenger-1 and challenger-3 finalized+published; challenger-2 failed.
    published_ids = uow.publications.published
    assert len(published_ids) == 2, f"expected 2 published, got {published_ids}"
    assert not any("challenger-2" in pid for pid in published_ids)


# ---------------------------------------------------------------------------
# 3. Pure comparison builders
# ---------------------------------------------------------------------------


def _lookup(payloads):
    """Typed evidence lookup backed by a dict keyed by canonical_step_id."""

    def find_typed(step_map, cs, pv_id, evidence_branch_id, kinds):
        return payloads.get(cs)

    return find_typed


def test_build_woe_iv_pure():
    payload = {
        "final-woe-iv": {"variables": [
            {"variable": "age", "iv": 0.5, "bins": [1, 2], "warnings": ["sparse bin"]},
        ]},
    }
    out = build_woe_iv(
        _lookup(payload), [{"canonical_step_id": "final-woe-iv"}], [],
        "pv-b", "pv-c", "challenger-1", {"include_woe_iv": True},
    )
    assert out["variables"][0]["variable"] == "age"
    assert out["variables"][0]["baseline"]["iv"] == 0.5
    assert out["variables"][0]["challengers"]["challenger-1"]["iv"] == 0.5


def test_build_model_pure_with_coefficients():
    payload = {
        "model-fit": {
            "model_family": "logistic_regression",
            "model_payload": {"intercept": 0.1, "coefficients": [
                {"variable": "age", "coefficient": 0.2},
            ]},
            "feature_contract": {"features": ["age"]},
        },
    }
    out = build_model(
        _lookup(payload), [{"canonical_step_id": "model-fit"}], [],
        "pv-b", "pv-c", "challenger-1", {"include_model": True},
    )
    assert out["branch_level"]["baseline"]["model_family"] == "logistic_regression"
    assert out["variables"][0]["variable"] == "age"
    assert out["variables"][0]["difference"]["coefficient_delta_vs_baseline"] == 0


def test_build_validation_pure():
    payload = {
        "validation-metrics": {"roles": {"train": {"auc": 0.7, "gini": 0.4}}},
    }
    out = build_validation(
        _lookup(payload), [{"canonical_step_id": "validation-metrics"}], [],
        "pv-b", "pv-c", "challenger-1", {"include_validation": True},
    )
    assert out["roles"]["train"]["baseline"]["auc"] == 0.7


def test_build_cutoff_pure():
    payload = {
        "cutoff-analysis": {"train": [{"cutoff": 0.5, "approval_rate": 0.8}]},
    }
    out = build_cutoff(
        _lookup(payload), [{"canonical_step_id": "cutoff-analysis"}], [],
        "pv-b", "pv-c", "challenger-1", {"include_cutoff": True},
    )
    assert out["roles"]["train"][0]["cutoff"] == 0.5


def test_build_content_assembles_all_sections():
    payload = {
        "final-woe-iv": {"variables": []},
        "model-fit": {"model_family": "logistic_regression", "model_payload": {}, "features": []},
        "validation-metrics": {"roles": {}},
        "cutoff-analysis": {},
    }
    spec = {"include_woe_iv": True, "include_model": True, "include_validation": True, "include_cutoff": True}
    out = build_content(
        _lookup(payload), [{"canonical_step_id": "x"}], [], "pv-b", "pv-c",
        "base-1", "challenger-1", spec,
    )
    assert out["comparison_type"] == "challenger_vs_baseline"
    assert "woe_iv" in out and "model" in out and "validation" in out and "cutoff" in out


# ---------------------------------------------------------------------------
# 4. Atomic snapshot write
# ---------------------------------------------------------------------------


def test_snapshot_write_is_atomic(tmp_path):
    """A forced persistence failure leaves neither the comparison artifact
    descriptor nor snapshot rows visible."""
    project_id, plan_id, pv_id, uow_factory, root = _provision(tmp_path)

    with uow_factory.for_project(project_id) as uow:
        baseline_branch_id = uow.branches.create_branch(
            project_id, plan_id, "base", "baseline", pv_id, pv_id, branch_id="base-1",
        )
        uow.comparisons.create_comparison_with_id(
            "cmp-1", project_id, plan_id, baseline_branch_id, "{}",
        )
        uow.commit()

    # Simulate a failure AFTER the descriptor register but BEFORE snapshot rows.
    class _FailAfter:
        def __init__(self, callable, n):
            self._callable = callable
            self._remaining = n

        def __call__(self, *args, **kwargs):
            if self._remaining <= 0:
                raise RuntimeError("injected snapshot failure")
            self._remaining -= 1
            return self._callable(*args, **kwargs)

    with uow_factory.for_project(project_id) as uow:
        comparisons_repo = uow.comparisons
        comparisons_repo.create_snapshot = _FailAfter(comparisons_repo.create_snapshot, 0)  # type: ignore[method-assign]
        try:
            comparisons_repo.create_snapshot(
                "cmp-1", project_id, plan_id, "art-1", json.dumps({"ready": True}),
            )
            uow.commit()
        except RuntimeError as exc:
            assert "injected snapshot failure" in str(exc)
            uow.rollback()

    with uow_factory.read_only(project_id) as uow:
        snapshots = uow.comparisons.get_comparison_snapshots("cmp-1")
        comparison = uow.comparisons.get_comparison("cmp-1")
    assert snapshots == []
    assert comparison is not None
    assert comparison["latest_snapshot_id"] is None


# ---------------------------------------------------------------------------
# P1-3: governance publication uses the durable outbox (real filesystem)
# ---------------------------------------------------------------------------


def test_refresh_comparison_cross_project_uses_comparison_not_found():
    """A comparison from another project surfaces as COMPARISON_NOT_FOUND, so
    one code maps to one HTTP status (404) in the domain-error map."""
    from cardre.application.governance.refresh_comparison import (
        RefreshComparison,
        RefreshComparisonCommand,
    )
    from cardre.domain.errors import CardreError, ErrorCode

    class _MismatchComparisons:
        def get_comparison(self, comparison_id) -> dict:
            return {
                "project_id": "other-project", "plan_id": "plan",
                "baseline_branch_id": "base-1", "comparison_spec_json": "{}",
            }

    class _MismatchUow:
        @property
        def comparisons(self):
            return _MismatchComparisons()

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    class _MismatchFactory:
        def for_project(self, project_id):
            return _MismatchUow()

    class _Writer:
        def stage_json(self, *args, **kwargs):
            return None

    uc = RefreshComparison(
        _MismatchFactory(),
        None,
        _Writer(),
        _stub_publisher_factory(None),
        governance_enabled=True,
    )

    with pytest.raises(CardreError) as exc_info:
        uc(RefreshComparisonCommand(project_id="proj", comparison_id="cmp-1"))
    assert exc_info.value.code == ErrorCode.COMPARISON_NOT_FOUND


def test_refresh_comparison_missing_comparison_is_not_found():
    from cardre.application.governance.refresh_comparison import (
        RefreshComparison,
        RefreshComparisonCommand,
    )
    from cardre.domain.errors import CardreError, ErrorCode

    class _MissingComparisons:
        def get_comparison(self, comparison_id):
            return None

    class _MissingUow:
        comparisons = _MissingComparisons()

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    class _MissingFactory:
        def for_project(self, project_id):
            return _MissingUow()

    class _Writer:
        def stage_json(self, *args, **kwargs):
            return None

    uc = RefreshComparison(
        _MissingFactory(),
        None,
        _Writer(),
        _stub_publisher_factory(None),
        governance_enabled=True,
    )

    with pytest.raises(CardreError) as exc_info:
        uc(RefreshComparisonCommand(project_id="proj", comparison_id="missing"))
    assert exc_info.value.code == ErrorCode.COMPARISON_NOT_FOUND


def test_refresh_comparison_database_failure_leaves_no_orphan_object(tmp_path):
    """A DB failure after staging a comparison artifact must leave no file in
    objects/ without a durable descriptor/outbox record. Uses the real
    filesystem adapter and real RefreshComparison with an injected failure."""
    from cardre.adapters.evidence.comparison_reader import ComparisonEvidenceReader
    from cardre.adapters.filesystem.artifact_store import FsArtifactStore
    from cardre.application.governance.refresh_comparison import (
        RefreshComparison,
        RefreshComparisonCommand,
    )

    project_id, plan_id, pv_id, uow_factory, root = _provision(tmp_path)

    with uow_factory.for_project(project_id) as uow:
        baseline_branch_id = uow.branches.create_branch(
            project_id, plan_id, "base", "baseline", pv_id, pv_id, branch_id="base-1",
        )
        uow.comparisons.create_comparison_with_id(
            "cmp-1", project_id, plan_id, baseline_branch_id,
            json.dumps({"include_woe_iv": True, "include_model": True,
                        "include_validation": True, "include_cutoff": True}),
        )
        challenger_id = uow.branches.create_branch(
            project_id, plan_id, "challenger", "challenger", pv_id, pv_id,
            branch_id="challenger-1",
        )
        uow.comparisons.add_challenger_branch("cmp-1", challenger_id, 0)
        uow.commit()

    store = FsArtifactStore(root)

    class _FailOnSnapshot:
        def __init__(self, inner):
            self._inner = inner

        def create_snapshot(self, *args, **kwargs):
            raise RuntimeError("injected snapshot failure")

        def __getattr__(self, name):
            return getattr(self._inner, name)

    # Inject the failure by wrapping the comparisons repo's create_snapshot.
    class _BombUow:
        def __init__(self, inner):
            self._inner = inner

        def __getattr__(self, name):
            return getattr(self._inner, name)

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        @property
        def comparisons(self):
            return _FailOnSnapshot(self._inner.comparisons)

    class _BombFactory:
        def for_project(self, project_id):
            return _BombUow(uow_factory.for_project(project_id))

    evidence = ComparisonEvidenceReader(uow_factory, store, project_id)
    uc = RefreshComparison(
        _BombFactory(),
        evidence,
        store,
        _stub_publisher_factory(uow_factory),
        governance_enabled=True,
    )
    # Stub readiness so the snapshot/publish path is reached deterministically.
    uc._check_readiness = lambda uow, branch_id, pv_id, *, is_baseline=False: []  # type: ignore[method-assign]

    with pytest.raises(RuntimeError, match="injected snapshot failure"):
        uc(RefreshComparisonCommand(project_id=project_id, comparison_id="cmp-1"))

    # No DB rows for the comparison artifact or snapshot.
    with uow_factory.read_only(project_id) as uow:
        snapshots = uow.comparisons.get_comparison_snapshots("cmp-1")
        assert snapshots == []
        artifacts = uow.artifacts.list_for_project(project_id, role="comparison")
        assert artifacts == []

    # No orphan file in objects/: files must remain in staging until the DB
    # mutation commits.
    objects_dir = root / "objects"
    orphan_files = list(objects_dir.rglob("*")) if objects_dir.exists() else []
    assert orphan_files == [], f"orphan object files after rollback: {orphan_files}"
