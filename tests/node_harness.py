"""Node test harness — run a node directly with fakes, no store required.

Importable from any test file (``from node_harness import FakeArtifact``) so
tests don't depend on which ``conftest.py`` pytest happens to resolve.
"""

from __future__ import annotations

import uuid

from cardre.nodes.contracts import NodeResult


class HarnessStaged:
    def __init__(self, kind, role, payload, metadata=None):
        self.kind = kind
        self.role = role
        self.payload = payload
        self.metadata = metadata or {}
        self.provisional_artifact_id = f"art-{uuid.uuid4().hex[:8]}"
        self.artifact_id = self.provisional_artifact_id
        self.logical_hash = "log"
        self.physical_hash = "phys"


class FakeOutputPublisher:
    """Implements the OutputPublisher protocol, collecting staged outputs."""

    def __init__(self):
        self.staged: list[HarnessStaged] = []
        self.metrics: dict = {}
        self.warnings: list[dict] = []
        self.fingerprint: dict | None = None

    def publish_json(self, *, role, kind, payload, metadata=None):
        self.staged.append(HarnessStaged(kind, role, payload, metadata))
        return self.staged[-1]

    def publish_table(self, *, role, kind, frame, metadata=None):
        self.staged.append(HarnessStaged(kind, role, frame, metadata))
        return self.staged[-1]

    def publish_bytes(self, *, role, kind, data, media_type, logical_hash, metadata=None):
        self.staged.append(HarnessStaged(kind, role, data, metadata))
        return self.staged[-1]

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


class FakeArtifact:
    """Minimal artifact object with role + metadata, for role-based input resolution."""

    def __init__(self, role, metadata=None, artifact_id=None, frame=None):
        self.role = role
        self.metadata = metadata or {}
        self.artifact_id = artifact_id or f"art-{uuid.uuid4().hex[:8]}"
        self.provisional_artifact_id = self.artifact_id
        self.physical_hash = "phys"
        self.logical_hash = "log"
        self._frame = frame

    def read_dataframe(self):
        return self._frame


class FakeInputCollection:
    """Implements the InputCollection protocol with in-memory frames/evidence."""

    def __init__(self, frames=None, evidence=None, target_metadata=None, roles=None):
        self._frames = frames or {}
        self._evidence = evidence or {}
        self._target_metadata = target_metadata
        self._roles = roles or {}

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
        return b""

    def target_metadata(self):
        return self._target_metadata

    def find_frozen_bundle(self):
        return None

    def artifact_ref(self, artifact_id):
        for arts in self._roles.values():
            for a in arts:
                if getattr(a, "artifact_id", None) == artifact_id:
                    return a
        return None
