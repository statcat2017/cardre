"""Node test harness — run a node directly with fakes, no store required.

The one adapter at the ``NodeContext`` seam. Tests build a context through
``make_context``, supply role-tagged artifacts, frames and evidence to
``FakeInputCollection``, and inspect published outputs through
``FakeOutputPublisher`` (recorded per role/kind, with payloads and bytes
retrievable for assertions).

Tier-1 tests (pure fakes) pin ordering, refs and publish shapes. Tier-2
round-trips — publish, finalize to a store, read back, deserialise — use the
real ``FsArtifactStore`` + ``EvidenceReader`` + ``StagingOutputPublisher``,
not this fake. See tests for the deep model-Artifact contract tests.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any

from cardre.domain.step import StepSpec
from cardre.nodes._params import NodeParams
from cardre.nodes.contracts import NodeContext, NodeResult, RuntimeMeta


@dataclass
class HarnessStaged:
    """A recorded publish call, retrievable by role/kind for assertions."""

    role: str
    kind: Any
    payload: Any
    metadata: dict[str, Any]
    media_type: str
    artifact_type: str | None = None
    data: bytes | None = None
    logical_hash: str = "log"
    physical_hash: str = "phys"
    artifact_id: str = field(default_factory=lambda: f"art-{uuid.uuid4().hex[:8]}")
    provisional_artifact_id: str = ""

    def __post_init__(self) -> None:
        if not self.provisional_artifact_id:
            self.provisional_artifact_id = self.artifact_id


class FakeOutputPublisher:
    """Implements the ``OutputPublisher`` protocol, collecting staged outputs.

    ``publish_bytes`` records the raw bytes so byte-level assertions (e.g. that
    the staged estimator is the joblib serialisation of the fitted estimator)
    work without a store.
    """

    def __init__(self) -> None:
        self.staged: list[HarnessStaged] = []
        self.metrics: dict = {}
        self.warnings: list[dict] = []
        self.fingerprint: dict | None = None

    def publish_json(self, *, role, kind, payload, metadata=None):
        staged = HarnessStaged(
            role=role, kind=kind, payload=payload,
            metadata=metadata or {}, media_type="application/json",
        )
        self.staged.append(staged)
        return staged

    def publish_table(self, *, role, kind, frame, metadata=None, artifact_type=None):
        staged = HarnessStaged(
            role=role, kind=kind, payload=frame,
            metadata=metadata or {}, media_type="application/vnd.apache.parquet",
            artifact_type=artifact_type,
        )
        self.staged.append(staged)
        return staged

    def publish_bytes(self, *, role, kind, data, media_type, logical_hash, metadata=None):
        staged = HarnessStaged(
            role=role, kind=kind, payload=None,
            metadata=metadata or {}, media_type=media_type,
            data=data, logical_hash=logical_hash,
        )
        # Mirror the store's descriptor-id assignment so the staged artifact's
        # provisional id is truthful for estimator bytes — the invariant that
        # lets a model JSON cite the binary before it is staged.
        if role == "estimator":
            from cardre.nodes._model_artifacts import estimator_descriptor_id

            staged.provisional_artifact_id = estimator_descriptor_id(
                data, logical_hash, metadata or {},
            )
        self.staged.append(staged)
        return staged

    def add_metric(self, name, value):
        self.metrics[name] = value

    def add_warning(self, warning):
        self.warnings.append(warning)

    def set_execution_fingerprint(self, fp):
        self.fingerprint = fp

    def build_result(self):
        return NodeResult(
            staged_artifacts=list(self.staged),
            metrics=dict(self.metrics),
            execution_fingerprint=dict(self.fingerprint) if self.fingerprint else None,
            warnings=list(self.warnings),
        )

    # -- Assertion helpers -------------------------------------------------
    def by_role(self, role: str) -> list[HarnessStaged]:
        return [s for s in self.staged if s.role == role]

    def by_kind(self, kind: Any) -> list[HarnessStaged]:
        return [s for s in self.staged if s.kind == kind]

    def payload_for(self, role: str) -> Any:
        matched = self.by_role(role)
        return matched[0].payload if matched else None


class FakeArtifact:
    """Minimal artifact object with role + metadata, for role-based input resolution."""

    def __init__(self, role, metadata=None, artifact_id=None, frame=None, data=None):
        self.role = role
        self.metadata = metadata or {}
        self.artifact_id = artifact_id or f"art-{uuid.uuid4().hex[:8]}"
        self.provisional_artifact_id = self.artifact_id
        self.physical_hash = "phys"
        self.logical_hash = "log"
        self._frame = frame
        self._data = data

    def read_dataframe(self):
        return self._frame


class FakeInputCollection:
    """Implements the ``InputCollection`` protocol with in-memory frames/evidence."""

    def __init__(self, frames=None, evidence=None, target_metadata=None, roles=None,
                 bytes_by_id=None):
        self._frames = frames or {}
        self._evidence = evidence or {}
        self._target_metadata = target_metadata
        self._roles = roles or {}
        self._bytes_by_id = bytes_by_id or {}

    def by_role(self, role):
        if role in self._roles:
            return list(self._roles[role])
        if role in self._frames:
            return [FakeArtifact(role, frame=self._frames[role])]
        return []

    def by_kind(self, kind):
        return [v for k, v in self._evidence.items() if k == kind]

    def first(self, role):
        matched = self.by_role(role)
        return matched[0] if matched else None

    def require(self, role, node_type):
        art = self.first(role)
        if art is None:
            raise ValueError(f"{node_type} requires a '{role}' artifact")
        return art

    def require_kind(self, kind, node_type):
        arts = self.by_kind(kind)
        if not arts:
            raise ValueError(f"{node_type}: no input artifact of kind {kind.value}")
        return arts[0]

    def read(self, artifact, kind):
        return self._evidence.get(kind)

    def read_optional(self, artifact, kind):
        return self._evidence.get(kind)

    def read_dataframe(self, artifact):
        if hasattr(artifact, "_frame") and artifact._frame is not None:
            return artifact._frame
        return self._frames[artifact]

    def read_bytes(self, artifact):
        return self._bytes_by_id.get(getattr(artifact, "artifact_id", artifact), b"")

    def target_metadata(self):
        return self._target_metadata

    def find_frozen_bundle(self):
        return None

    def artifact_ref(self, artifact_id, *, physical_hash=None):
        # Mirror production StepInputCollection.artifact_ref: resolve by ID
        # first, then fall back to the physical hash (deduplicated artifacts
        # may carry a different canonical ID than the embedded provisional one).
        for arts in self._roles.values():
            for a in arts:
                if getattr(a, "artifact_id", None) == artifact_id:
                    return a
        if physical_hash:
            for arts in self._roles.values():
                for a in arts:
                    if getattr(a, "physical_hash", None) == physical_hash:
                        return a
        return None


def make_context(
    inputs: Any,
    outputs: Any,
    params: dict[str, Any] | None = None,
    *,
    node_type: str = "test.node",
    step_id: str = "step",
    run_id: str = "run-1",
    plan_version_id: str = "plan-1",
    category: str = "test",
) -> NodeContext:
    """Build a ``NodeContext`` with sensible defaults, so tests supply only
    the parts they vary (inputs, outputs, params)."""
    params = params or {}
    spec = StepSpec(
        step_id=step_id,
        node_type=node_type,
        node_version="1",
        category=category,
        params=NodeParams(params),
        params_hash="hash",
        parent_step_ids=[],
        canonical_step_id=step_id,
    )
    return NodeContext(
        run_id=run_id,
        plan_version_id=plan_version_id,
        step_spec=spec,
        inputs=inputs,
        outputs=outputs,
        params=NodeParams(params),
        runtime=RuntimeMeta(run_id, plan_version_id, step_id, node_type),
    )
