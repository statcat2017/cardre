"""Shared types for the reporting layer."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Literal, Protocol

if TYPE_CHECKING:
    from cardre._evidence.kinds import EvidenceKind
    from cardre._evidence.reader import ArtifactEvidenceReader
    from cardre.branch_step_resolver import ResolvedStepRef
    from cardre.reporting.schema import Limitation, ReportBundle
    from cardre.store import ProjectStore

ReportMode = Literal["branch", "champion"]


@dataclass(frozen=True)
class ManifestDigest:
    """Immutable digest of the canonical run manifest."""

    manifest_hash: str | None = None
    pathway_hash: str | None = None
    execution_mode: str | None = None
    target_step_id: str | None = None
    in_scope_step_ids: list[str] = field(default_factory=list)
    limitations: list[Limitation] = field(default_factory=list)
    source_run_manifest_path: str | None = None
    artifact_root: str | None = None


@dataclass(frozen=True)
class SectionContext:
    """Everything a section collector needs to build its part of the report.

    Carried as a single argument so the protocol has a uniform signature
    regardless of whether a section consumes one ref, multiple refs, or
    no ref at all.
    """

    bundle: ReportBundle
    resolved: dict[str, ResolvedStepRef]
    run: dict[str, Any]
    manifest_digest: ManifestDigest
    plan_version_id: str
    report_mode: ReportMode
    store: ProjectStore
    reader: ArtifactEvidenceReader
    add_limitation: Callable[[Limitation], None]


class SectionCollector(Protocol):
    """Protocol for a single report section collector.

    Sections that are driven by a canonical step pull their ref from
    ``ctx.resolved[self.canonical_step_id]``. Sections that are not
    step-driven (champion, dataset_roles, artifacts, run_status,
    reproducibility) set ``canonical_step_id = None`` and ignore
    ``ctx.resolved``.
    """

    canonical_step_id: str | None
    kinds: tuple[EvidenceKind, ...]

    def build(self, ctx: SectionContext) -> None: ...
