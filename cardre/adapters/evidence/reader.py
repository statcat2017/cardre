"""EvidenceReader — typed evidence access via ArtifactReader.

Replaces the legacy ``ArtifactEvidenceReader`` with a
port-based reader that depends on ``ArtifactReader``, ``ArtifactRepoPort``,
and ``RunStepRepoPort`` instead of ``ProjectStore``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import polars as pl

from cardre.adapters.evidence.parsers import get_adapter, match
from cardre.adapters.evidence.profiles import EVIDENCE_PROFILES
from cardre.application.ports.artifact_store import ArtifactReader
from cardre.application.ports.unit_of_work import ArtifactRepoPort, RunStepRepoPort
from cardre.domain.artifacts import ArtifactRef
from cardre.domain.evidence.kinds import (
    AmbiguousEvidenceError,
    EvidenceKind,
    EvidenceNotFoundError,
    EvidenceParseError,
)
from cardre.store.artifact_repo import ArtifactRepository
from cardre.store.run_step_repo import RunStepRepository


class EvidenceReader:
    """Reads typed evidence from immutable Artifacts through an ArtifactReader.

    Two usage patterns::

        # 1) Find evidence within a mixed list (Node input_artifacts):
        reader.find(artifacts, EvidenceKind.BIN_DEFINITION)

        # 2) Read a known artifact by ID (reporting/comparison):
        reader.read(artifact_id, EvidenceKind.WOE_IV_EVIDENCE)
    """

    def __init__(
        self,
        artifact_reader: ArtifactReader,
        artifact_repo: ArtifactRepoPort,
        run_step_repo: RunStepRepoPort,
    ) -> None:
        self._reader = artifact_reader
        self._artifact_repo = artifact_repo
        self._run_step_repo = run_step_repo

    # ------------------------------------------------------------------
    # Public: find
    # ------------------------------------------------------------------

    def find(self, artifacts: list[ArtifactRef], kind: EvidenceKind) -> Any:
        spec = get_adapter(kind)
        candidates = match(artifacts, spec.profile, self._reader)
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
        """Like ``find`` but returns ``None`` on not-found.

        ``AmbiguousEvidenceError`` is NOT caught — ambiguity is always an error
        and must be surfaced to the caller.
        """
        try:
            return self.find(artifacts, kind)
        except EvidenceNotFoundError:
            return None

    # ------------------------------------------------------------------
    # Public: read by artifact ID
    # ------------------------------------------------------------------

    def read(self, artifact_id: str, kind: EvidenceKind) -> Any:
        art = self._artifact_repo.get(artifact_id)
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
        spec = get_adapter(kind)
        matched = match([art], spec.profile, self._reader)
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
        try:
            return self.read(artifact_id, kind)
        except EvidenceNotFoundError:
            return None

    def require_model(self, model_art: ArtifactRef, node_type: str) -> Any:
        try:
            model_typed = self.read_optional(model_art.artifact_id, EvidenceKind.MODEL_ARTIFACT)
        except EvidenceParseError as exc:
            raise ValueError(
                f"{node_type} requires model artifact {model_art.artifact_id!r} to be readable as MODEL_ARTIFACT evidence"
            ) from exc
        if model_typed is None or not model_typed.model_family:
            raise ValueError(
                f"{node_type} requires model artifact {model_art.artifact_id!r} to be readable as MODEL_ARTIFACT evidence"
            )
        return model_typed

    def read_dataframe(self, art: ArtifactRef) -> pl.DataFrame:
        return pl.read_parquet(self._reader.resolve_path(art))

    def read_bytes(self, art: ArtifactRef) -> bytes:
        return self._reader.read_bytes(art)

    def read_step_output_optional(
        self,
        run_step_id: str,
        kind: EvidenceKind,
    ) -> Any | None:
        for aid in self._artifact_repo.output_artifact_ids_for_run_step(run_step_id):
            result = self.read_optional(aid, kind)
            if result is not None:
                return result
        return None

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _parse(self, art: ArtifactRef, kind: EvidenceKind) -> Any:
        path = self._reader.resolve_path(art)
        if not path.exists():
            raise EvidenceParseError(f"Artifact file not found: {path}")
        return get_adapter(kind).parse(path, art, self._reader)


class _StoreArtifactReader:
    """Adapt a ProjectStore to the ArtifactReader port for deferred nodes."""

    def __init__(self, store: Any) -> None:
        self._store = store

    @property
    def root(self) -> Path:
        return self._store.root  # type: ignore[no-any-return]

    def read_bytes(self, artifact: object) -> bytes:
        return self.resolve_path(artifact).read_bytes()

    def resolve_path(self, artifact: object) -> Path:
        return self._store.artifact_path(artifact)  # type: ignore[no-any-return]  # cardre-allow-artifact-read: low-level-evidence-parser


class ArtifactEvidenceReader:
    """ProjectStore-backed evidence reader retained for deferred-tier nodes.

    Launch-path code uses ``EvidenceReader`` directly through ports. This
    adapter preserves the legacy node contract until the 07f context migration.
    """

    def __init__(self, store: Any) -> None:
        self._store = store
        self._inner = EvidenceReader(
            artifact_reader=_StoreArtifactReader(store),
            artifact_repo=ArtifactRepository(store),  # type: ignore[arg-type]
            run_step_repo=RunStepRepository(store),  # type: ignore[arg-type]
        )

    def find(self, artifacts: list[ArtifactRef], kind: EvidenceKind) -> Any:
        return self._inner.find(artifacts, kind)

    def find_optional(self, artifacts: list[ArtifactRef], kind: EvidenceKind) -> Any | None:
        return self._inner.find_optional(artifacts, kind)

    def read(self, artifact_id: str, kind: EvidenceKind) -> Any:
        return self._inner.read(artifact_id, kind)

    def read_optional(self, artifact_id: str, kind: EvidenceKind) -> Any | None:
        return self._inner.read_optional(artifact_id, kind)

    def require_model(self, model_art: ArtifactRef, node_type: str) -> Any:
        return self._inner.require_model(model_art, node_type)

    def read_dataframe(self, art: ArtifactRef) -> pl.DataFrame:
        return self._inner.read_dataframe(art)

    def read_step_output_optional(self, run_step_id: str, kind: EvidenceKind) -> Any | None:
        return self._inner.read_step_output_optional(run_step_id, kind)

    def _match(self, artifacts: list[ArtifactRef], kind: EvidenceKind) -> list[ArtifactRef]:
        spec = get_adapter(kind)
        return match(artifacts, spec.profile, self._inner._reader)

    def _parse(self, art: ArtifactRef, kind: EvidenceKind) -> Any:
        path = self._inner._reader.resolve_path(art)
        if not path.exists():
            raise EvidenceParseError(f"Artifact file not found: {path}")
        return get_adapter(kind).parse(path, art, self._inner._reader)


__all__ = ["ArtifactEvidenceReader", "EvidenceReader"]
