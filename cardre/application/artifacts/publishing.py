"""Atomic publish-and-register for run artifacts.

The publish-to-filesystem-then-register-in-DB flow appears in run execution
and run-summary publishing.  If the DB write fails after the file is moved
into place, the artifact is orphaned.  ``publish_staged`` returns the
published path so the caller can compensate (delete the file) when its
transaction rolls back.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from cardre.application.ports.artifact_store import StagedArtifact
from cardre.domain.artifacts import ArtifactRef


def publish_staged(artifact_store: Any, staged: StagedArtifact) -> tuple[ArtifactRef, Path]:
    """Publish a staged artifact to its final location.

    Returns ``(ref, published_path)``.  The caller registers *ref* inside its
    own transaction and deletes *published_path* if that transaction fails.
    """
    published_path = Path(artifact_store.publish(staged))
    ref = ArtifactRef(
        artifact_id=staged.provisional_artifact_id,
        artifact_type=staged.artifact_type,
        role=staged.role,
        path=str(published_path),
        physical_hash=staged.physical_hash,
        logical_hash=staged.logical_hash,
        media_type=staged.media_type,
        metadata=staged.metadata,
    )
    return ref, published_path


def compensate(published_paths: list[Path]) -> None:
    """Delete published files after a failed transaction (no orphans)."""
    for path in published_paths:
        path.unlink(missing_ok=True)
