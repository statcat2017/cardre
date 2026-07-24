"""Filesystem run-manifest publisher.

Writes the canonical manifest to ``exports/manifest-{run_id}/manifest.json``
using the shared domain serialization and hashing. This is the only adapter
that should publish canonical manifests.
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any

from cardre.domain.diagnostics import JsonDict
from cardre.domain.manifest import (
    MANIFEST_VERSION,
    compute_manifest_hash,
    compute_pathway_hash,
    serialize_manifest,
)


class FsManifestPublisher:
    """Publish a canonical run manifest to the filesystem.

    The manifest is written atomically: a temp file is created, written,
    and then renamed to the final path. The manifest_hash is computed
    using the shared domain function before writing.

    The caller supplies a ``payload`` dict containing the raw manifest
    fields. This adapter completes the manifest by computing
    ``pathway_hash`` and ``manifest_hash``, then writes the result.
    """

    def __init__(self, root: Path) -> None:
        self._root = root

    @property
    def root(self) -> Path:
        return self._root

    def manifest_path(self, run_id: str) -> Path:
        return self._root / "exports" / f"manifest-{run_id}" / "manifest.json"

    def publish(self, run_id: str, payload: JsonDict) -> Path:
        manifest_path = self.manifest_path(run_id)
        manifest_path.parent.mkdir(parents=True, exist_ok=True)

        steps = payload.get("steps", [])
        if "pathway_hash" not in payload or not payload["pathway_hash"]:
            payload["pathway_hash"] = compute_pathway_hash(steps)
        payload["manifest_version"] = MANIFEST_VERSION
        payload["manifest_hash"] = compute_manifest_hash(payload)

        text = serialize_manifest(payload)
        tmp = manifest_path.parent / f".manifest.json.tmp.{uuid.uuid4().hex[:8]}"
        tmp.write_text(text, encoding="utf-8")
        tmp.replace(manifest_path)
        return manifest_path

    def read(self, run_id: str) -> JsonDict | None:
        """Read and parse a canonical manifest, returning None if missing."""
        path = self.manifest_path(run_id)
        if not path.exists():
            return None
        return json.loads(path.read_text(encoding="utf-8"))

    def verify(self, run_id: str) -> dict[str, Any]:
        """Verify a manifest's self-hash. Returns a result dict.

        Keys:
          - ``valid``: bool
          - ``manifest``: the parsed dict or None
          - ``error``: error message or None
        """
        data = self.read(run_id)
        if data is None:
            return {"valid": False, "manifest": None, "error": "CANONICAL_MANIFEST_MISSING"}
        recorded = data.get("manifest_hash", "")
        if not recorded:
            return {"valid": False, "manifest": data, "error": "CANONICAL_MANIFEST_MISSING"}
        expected = compute_manifest_hash(data)
        if recorded != expected:
            return {"valid": False, "manifest": data, "error": "ARTIFACT_HASH_UNRESOLVED"}
        return {"valid": True, "manifest": data, "error": None}


__all__ = ["FsManifestPublisher"]
