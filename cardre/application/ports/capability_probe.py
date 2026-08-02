"""Capability probe port — injectable environment-capability checker."""

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class CapabilityProbePort(Protocol):
    """Injectable capability probe.

    Use cases depend on this protocol to check whether the
    runtime environment supports certain features (e.g. optional
    dependencies, filesystem paths, external services) rather
    than probing directly.
    """

    def project_root_exists(self, root: str) -> bool:
        """Return whether a project root directory exists."""
        ...
