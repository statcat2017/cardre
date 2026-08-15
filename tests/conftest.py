"""Shared pytest fixtures for Cardre v2 tests."""

from __future__ import annotations

import pytest

# ---------------------------------------------------------------------------
# Node test harness — run a node directly with fakes, no store required.
# The fakes live in tests/node_harness.py so tests can import them without
# depending on which conftest.py pytest resolves.
# ---------------------------------------------------------------------------
from node_harness import (  # noqa: E402
    FakeInputCollection,
    FakeOutputPublisher,
)


@pytest.fixture
def node_harness():
    """Run a node directly with fakes: node tests without a store.

    Usage::

        out = node_harness(
            ScoreScalingNode,
            frames={"model": df, "definition": df2, "report": df3},
            evidence={EvidenceKind.MODEL_ARTIFACT: typed_model, ...},
            params={...},
            target_metadata=TargetSpec(...),
        )
        assert out.metrics["attribute_count"] == 3
    """
    from cardre.domain.step import StepSpec
    from cardre.nodes.contracts import NodeContext, RuntimeMeta

    def run(node_cls, *, frames=None, evidence=None, params=None, target_metadata=None, roles=None, skip_validation=False):
        from cardre.nodes.parameters import normalize_node_params

        outputs = FakeOutputPublisher()
        node = node_cls()
        raw_params = params or {}
        schema = node.parameter_schema()
        normalized = normalize_node_params(schema, dict(raw_params)) if schema else dict(raw_params)
        if not skip_validation:
            errors = node.validate_params(normalized)
            assert errors == [], f"param validation failed: {errors}"
        step_spec = StepSpec(
            step_id="step-test",
            node_type=node_cls.node_type,
            node_version=node_cls.version,
            category=node_cls.category,
            params=normalized,
            params_hash="dummy",
            parent_step_ids=[],
        )
        node.run(NodeContext(
            run_id="run-test",
            plan_version_id="pv-test",
            step_spec=step_spec,
            inputs=FakeInputCollection(frames or {}, evidence or {}, target_metadata, roles),
            outputs=outputs,
            params=normalized,
            runtime=RuntimeMeta("run-test", "pv-test", "step-test", node_cls.node_type),
        ))
        return outputs

    return run


@pytest.fixture(autouse=True)
def _project_resolution_test_env(monkeypatch, tmp_path_factory):
    """Set up registry path for tests. Raw project path is disabled by default."""
    registry_dir = tmp_path_factory.mktemp("cardre-registry")
    monkeypatch.setenv("CARDRE_ALLOW_RAW_PROJECT_PATH", "0")
    monkeypatch.setenv("CARDRE_REGISTRY_PATH", str(registry_dir / "projects.json"))


@pytest.fixture
def raw_project_path(monkeypatch):
    """Opt-in fixture for tests that need CARDRE_ALLOW_RAW_PROJECT_PATH=1."""
    monkeypatch.setenv("CARDRE_ALLOW_RAW_PROJECT_PATH", "1")
