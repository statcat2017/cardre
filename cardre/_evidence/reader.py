"""ArtifactEvidenceReader — typed evidence access from immutable artifacts.

The reader is a thin dispatcher over the EvidenceAdapter registry
(``cardre._evidence.adapters``). Each ``EvidenceKind`` has an adapter that
owns matching and parsing; the reader resolves artifacts via ``ProjectStore``
and delegates to the adapter.
"""

from __future__ import annotations

from typing import Any

from cardre._evidence.adapters import get_adapter
from cardre._evidence.kinds import (
    AmbiguousEvidenceError,
    EvidenceKind,
    EvidenceNotFoundError,
    EvidenceParseError,
)
from cardre._evidence.profiles import EVIDENCE_PROFILES
from cardre.domain.artifacts import ArtifactRef
from cardre.store import ProjectStore


class ArtifactEvidenceReader:
    """Reads typed evidence from immutable Artifacts through a ProjectStore.

    Two usage patterns::

        # 1) Find evidence within a mixed list (Node input_artifacts):
        reader.find(artifacts, EvidenceKind.BIN_DEFINITION)

        # 2) Read a known artifact by ID (reporting/comparison):
        reader.read(artifact_id, EvidenceKind.WOE_IV_EVIDENCE)
    """

    def __init__(self, store: ProjectStore) -> None:
        self._store = store

    # ------------------------------------------------------------------
    # Public: find
    # ------------------------------------------------------------------

    def find(self, artifacts: list[ArtifactRef], kind: EvidenceKind) -> Any:
        """Return typed evidence from the single matching Artifact.

        Raises ``EvidenceNotFoundError`` or ``AmbiguousEvidenceError``.
        """
        candidates = self._match(artifacts, kind)
        if not candidates:
            profile = EVIDENCE_PROFILES.get(kind)
            raise EvidenceNotFoundError(
                kind,
                candidate_artifact_ids=[a.artifact_id for a in artifacts],
                expected_schema=profile.schema_version if profile else None,
                expected_role=",".join(sorted(profile.expected_roles)) if profile else None,
                expected_artifact_type=",".join(sorted(profile.expected_artifact_types)) if profile else None,
                expected_media_type=",".join(sorted(profile.expected_media_types)) if profile else None,
            )
        if len(candidates) > 1:
            profile = EVIDENCE_PROFILES.get(kind)
            raise AmbiguousEvidenceError(
                kind,
                candidates,
                expected_schema=profile.schema_version if profile else None,
                expected_role=",".join(sorted(profile.expected_roles)) if profile else None,
                expected_artifact_type=",".join(sorted(profile.expected_artifact_types)) if profile else None,
                expected_media_type=",".join(sorted(profile.expected_media_types)) if profile else None,
            )
        return self._parse(candidates[0], kind)

    def find_optional(self, artifacts: list[ArtifactRef], kind: EvidenceKind) -> Any | None:
        """Like ``find`` but returns ``None`` when no match or ambiguity."""
        try:
            return self.find(artifacts, kind)
        except (EvidenceNotFoundError, AmbiguousEvidenceError):
            return None

    # ------------------------------------------------------------------
    # Public: read by artifact ID
    # ------------------------------------------------------------------

    def read(self, artifact_id: str, kind: EvidenceKind) -> Any:
        """Read typed evidence from a known artifact ID.

        Raises ``EvidenceNotFoundError`` if the artifact does not exist
        or does not match the expected profile.
        """
        art = self._store.get_artifact(artifact_id)
        if art is None:
            profile = EVIDENCE_PROFILES.get(kind)
            raise EvidenceNotFoundError(
                kind,
                artifact_id=artifact_id,
                expected_schema=profile.schema_version if profile else None,
                expected_role=",".join(sorted(profile.expected_roles)) if profile else None,
                expected_artifact_type=",".join(sorted(profile.expected_artifact_types)) if profile else None,
                expected_media_type=",".join(sorted(profile.expected_media_types)) if profile else None,
            )
        matched = self._match([art], kind)
        if not matched:
            profile = EVIDENCE_PROFILES.get(kind)
            raise EvidenceNotFoundError(
                kind,
                artifact_id=artifact_id,
                expected_schema=profile.schema_version if profile else None,
                actual_schema=art.metadata.get("schema_version", ""),
                expected_role=",".join(sorted(profile.expected_roles)) if profile else None,
                expected_artifact_type=",".join(sorted(profile.expected_artifact_types)) if profile else None,
                expected_media_type=",".join(sorted(profile.expected_media_types)) if profile else None,
            )
        return self._parse(matched[0], kind)

    def read_optional(self, artifact_id: str, kind: EvidenceKind) -> Any | None:
        """Like ``read`` but returns ``None`` when no match exists."""
        try:
            return self.read(artifact_id, kind)
        except EvidenceNotFoundError:
            return None

    def read_step_output_optional(
        self,
        run_step_id: str,
        kind: EvidenceKind,
    ) -> Any | None:
        """Resolve output artifact IDs via artifact_lineage and scan for the given kind."""
        rows = self._store.execute(
            "SELECT artifact_id FROM artifact_lineage WHERE run_step_id = ? AND direction = 'output'",
            (run_step_id,),
        ).fetchall()
        for row in rows:
            result = self.read_optional(row["artifact_id"], kind)
            if result is not None:
                return result
        return None

    # ------------------------------------------------------------------
    # Internal: delegate to adapter registry
    # ------------------------------------------------------------------

    def _match(self, artifacts: list[ArtifactRef], kind: EvidenceKind) -> list[ArtifactRef]:
        """Delegate matching to the adapter for this evidence kind."""
        return get_adapter(kind).match(artifacts, self._store)

    def _parse(self, art: ArtifactRef, kind: EvidenceKind) -> Any:
        """Delegate parsing to the adapter for this evidence kind."""
        path = self._store.artifact_path(art)
        if not path.exists():
            raise EvidenceParseError(f"Artifact file not found: {path}")
        return get_adapter(kind).parse(path, art, self._store)
