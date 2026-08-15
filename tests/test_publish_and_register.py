"""Atomic publish-and-register — compensation tests.

A DB failure after the artifact file is moved into place must delete the
file, leaving no orphaned artifacts.
"""

from __future__ import annotations

from cardre.application.artifacts.publishing import compensate, publish_staged
from cardre.domain.evidence.kinds import EvidenceKind


class _FakeStore:
    def __init__(self, root):
        self._root = root

    def stage_json(self, role, kind, payload, metadata=None):
        import uuid

        from cardre.application.ports.artifact_store import StagedArtifact

        staging = self._root / "staging"
        staging.mkdir(exist_ok=True)
        path = staging / f"{uuid.uuid4().hex}.json"
        path.write_text("{}")
        return StagedArtifact(
            staging_path=path,
            provisional_artifact_id=f"art-{uuid.uuid4().hex[:8]}",
            physical_hash="phys",
            logical_hash="log",
            media_type="application/json",
            schema_version="v1",
            role=role,
            artifact_type=kind,
            metadata=metadata or {},
        )

    def publish(self, staged):
        dest = self._root / "objects" / staged.physical_hash
        dest.parent.mkdir(parents=True, exist_ok=True)
        staged.staging_path.replace(dest)
        return dest


def test_publish_staged_moves_file_to_final_location(tmp_path) -> None:
    store = _FakeStore(tmp_path)
    staged = store.stage_json("manifest", EvidenceKind.RUN_SUMMARY.value, {"a": 1})
    ref, path = publish_staged(store, staged)
    assert path.exists()
    assert ref.artifact_id == staged.provisional_artifact_id
    assert ref.physical_hash == "phys"


def test_compensate_deletes_published_files(tmp_path) -> None:
    store = _FakeStore(tmp_path)
    staged = store.stage_json("manifest", EvidenceKind.RUN_SUMMARY.value, {"a": 1})
    _, path = publish_staged(store, staged)
    assert path.exists()
    compensate([path])
    assert not path.exists()


def test_compensate_is_idempotent(tmp_path) -> None:
    store = _FakeStore(tmp_path)
    staged = store.stage_json("manifest", EvidenceKind.RUN_SUMMARY.value, {"a": 1})
    _, path = publish_staged(store, staged)
    compensate([path])
    compensate([path])  # no error on already-deleted file
