"""Shared matching helpers for evidence adapters.

These helpers reproduce the exact matching logic of
``ArtifactEvidenceReader._match`` and ``_candidate_passes_payload_check``.
They are intentionally independent of the reader so adapters can be tested
and wired into the reader without creating a circular dependency.

The helpers implement two-phase matching: schema-version match followed by
role/type/media + payload check.  Legacy payload-key heuristics are not
included in the adapter path.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from cardre._evidence.profiles import _Profile
from cardre.domain.artifacts import ArtifactRef
from cardre.store import ProjectStore


def match_by_schema_version(artifacts: list[ArtifactRef], profile: _Profile) -> list[ArtifactRef]:
    """Phase 1: exact ``schema_version`` match against the profile.

    Matches on ``ArtifactRef.metadata["schema_version"]``, not on the
    JSON payload.
    """
    if not profile.schema_version:
        return []
    return [a for a in artifacts if a.metadata.get("schema_version") == profile.schema_version]


def match_by_role_type_media(artifacts: list[ArtifactRef], profile: _Profile) -> list[ArtifactRef]:
    """Phase 2: role + artifact_type + media_type + exclude_key filter."""
    return [
        a for a in artifacts
        if a.role in profile.expected_roles
        and a.artifact_type in profile.expected_artifact_types
        and a.media_type in profile.expected_media_types
        and (profile.exclude_key is None or profile.exclude_key not in a.metadata)
    ]


def parquet_has_columns(art: ArtifactRef, columns: set[str], store: ProjectStore) -> bool:
    """Check whether the parquet artifact contains all required columns."""
    try:
        import polars as pl
        cols = pl.scan_parquet(store.artifact_path(art)).collect_schema().names()
        return columns.issubset(cols)
    except Exception:
        return False


def candidate_passes_payload_check(art: ArtifactRef, profile: _Profile, store: ProjectStore) -> bool:
    """Check that a candidate's payload matches the profile requirements.

    Reproduces ``ArtifactEvidenceReader._candidate_passes_payload_check``
    exactly: checks ``required_columns`` for parquet artifacts and
    ``required_keys`` for JSON artifacts. Does NOT check
    ``legacy_required_keys`` (the reader's version does not).
    """
    if profile.required_columns is not None:
        if art.media_type == "application/json":
            return False
        return parquet_has_columns(art, profile.required_columns, store)
    if profile.required_keys:
        path = store.artifact_path(art)
        if not path.exists():
            return False
        try:
            data = json.loads(path.read_text())
            keys = set(data.keys())
            return profile.required_keys.issubset(keys)
        except (json.JSONDecodeError, UnicodeDecodeError):
            return False
    return True


def match(artifacts: list[ArtifactRef], profile: _Profile, store: ProjectStore) -> list[ArtifactRef]:
    """Two-phase matching: schema version first, then role/type/media + payload check."""
    schema_matches = match_by_schema_version(artifacts, profile)
    if schema_matches:
        validated = [
            a for a in schema_matches
            if a.role in profile.expected_roles
            and a.artifact_type in profile.expected_artifact_types
            and a.media_type in profile.expected_media_types
            and (profile.exclude_key is None or profile.exclude_key not in a.metadata)
            and candidate_passes_payload_check(a, profile, store)
        ]
        if validated:
            return validated
        return []
    candidates = match_by_role_type_media(artifacts, profile)
    if len(candidates) == 1:
        if candidate_passes_payload_check(candidates[0], profile, store):
            return candidates
        candidates = []
    return candidates


def _passes_format_check(art: ArtifactRef, profile: _Profile) -> bool:
    """Format-only check for schema-matched artifacts.

    Schema version is a strong signal; only reject when a parquet file is
    matched against a JSON-only profile.
    """
    if art.media_type != "application/vnd.apache.parquet":
        return True
    return profile.required_columns is not None


def read_json_payload(path: Path) -> dict[str, Any]:
    """Read and parse a JSON artifact payload, returning a dict."""
    return json.loads(path.read_text())  # type: ignore[no-any-return]  # json.loads returns Any


def scan_parquet(path: Path) -> Any:
    """Scan a parquet artifact, returning a polars LazyFrame."""
    import polars as pl
    return pl.scan_parquet(path)
