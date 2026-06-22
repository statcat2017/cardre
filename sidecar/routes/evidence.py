"""Evidence summary routes — wraps ArtifactEvidenceReader for the frontend.

Reserved by ADR 0008 §6 and Phase 4.
Routes are registered in ``sidecar/main.py`` by Phase 4.
See ``docs/architecture/artifact-evidence-access.md`` for the approved
read path.
"""

from __future__ import annotations

from fastapi import APIRouter

router = APIRouter(prefix="/runs", tags=["evidence"])
