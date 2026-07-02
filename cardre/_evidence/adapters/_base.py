"""Shared matching helpers for evidence adapters."""

from __future__ import annotations

import json

from cardre.domain.artifacts import ArtifactRef
from cardre._evidence.profiles import _Profile
from cardre.store import ProjectStore


def match_by_schema_version(artifacts: list[ArtifactRef], profile: _Profile) -> list[ArtifactRef]:
    """Phase 1 match: schema_version exact match (including legacy versions)."""
    schema_versions = {profile.schema_version} if profile.schema_version else set()
    if hasattr(profile, 'legacy_schema_versions') and profile.legacy_schema_versions:
        schema_versions.update(profile.legacy_schema_versions)
    if not schema_versions:
        return []
    return [a for a in artifacts if a.metadata.get("schema_version") in schema_versions]


def match_by_role_type_media(artifacts: list[ArtifactRef], profile: _Profile) -> list[ArtifactRef]:
    """Phase 2 match: role + artifact_type + media_type + exclude_key filter."""
    return [
        a for a in artifacts
        if a.role in profile.expected_roles
        and a.artifact_type in profile.expected_artifact_types
        and a.media_type in profile.expected_media_types
        and (profile.exclude_key is None or profile.exclude_key not in a.metadata)
    ]


def match_by_payload_key(artifacts: list[ArtifactRef], required_keys: set[str], store: ProjectStore, exclude_key: str | None = None) -> list[ArtifactRef]:
    """Phase 3 match: payload key heuristics. Reads each artifact's JSON payload."""
    result: list[ArtifactRef] = []
    for a in artifacts:
        try:
            payload = json.loads(store.artifact_path(a).read_text())
        except Exception:
            continue
        if required_keys.issubset(payload.keys()):
            if exclude_key is None or exclude_key not in payload:
                result.append(a)
    return result


def parquet_has_columns(art: ArtifactRef, columns: set[str], store: ProjectStore) -> bool:
    """Check whether the parquet artifact contains all required columns."""
    try:
        import polars as pl
        cols = pl.scan_parquet(store.artifact_path(art)).collect_schema().names()
        return columns.issubset(cols)
    except Exception:
        return False


def candidate_passes_payload_check(art: ArtifactRef, profile: _Profile, store: ProjectStore) -> bool:
    """Check that a candidate's payload matches the profile requirements."""
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
            if profile.required_keys.issubset(keys):
                return True
            return False
        except (json.JSONDecodeError, UnicodeDecodeError):
            return False
    return True
