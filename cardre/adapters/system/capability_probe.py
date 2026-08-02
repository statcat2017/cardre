"""Filesystem capability probe — concrete CapabilityProbePort."""

from __future__ import annotations

from pathlib import Path


class FilesystemCapabilityProbe:
    """Concrete CapabilityProbePort that checks filesystem paths."""

    def project_root_exists(self, root: str) -> bool:
        return (Path(root) / "project.sqlite").exists()
