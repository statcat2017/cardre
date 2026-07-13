"""Report collector — builds ReportBundle from immutable run artifacts.

Phase 5 rule: the collector is a read-only artifact consumer.
It must not become a second modelling execution path.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from json import JSONDecodeError, loads

from cardre._evidence.reader import ArtifactEvidenceReader
from cardre.branch_step_resolver import ResolvedStepRef as _ResolvedStepRef
from cardre.branch_step_resolver import resolve_required_steps
from cardre.domain.artifacts import (
    json_logical_hash,
)
from cardre.domain.run import RunStep
from cardre.readiness.limitation_codes import LimitationCode
from cardre.reporting.evidence_contract import REQUIRED_STEPS_COLLECTOR
from cardre.reporting.schema import (
    GeneratedBy,
    Limitation,
    ReportBundle,
    RunManifest,
)
from cardre.reporting.sections import SECTION_COLLECTORS
from cardre.reporting.types import ManifestDigest, ReportMode, SectionContext
from cardre.store import ProjectStore

CARDRE_VERSION = "0.1.0"


def _utc_now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def _resolve_run_step(
    store: ProjectStore, ref: _ResolvedStepRef, plan_version_id: str,
    add_limitation: Callable[[Limitation], None] | None = None,
) -> RunStep | None:
    from cardre.evidence_locator import EvidenceLocator
    branch_id = ref.resolved_branch_id if ref.resolution == "ancestor" else None
    resolved = EvidenceLocator(store).resolve(
        plan_version_id, ref.step_id, branch_id=branch_id,
    )
    rs = resolved.run_step if resolved is not None else None
    if rs is not None and ref.resolution == "ancestor" and add_limitation is not None:
        add_limitation(Limitation(
            severity="warning", code=LimitationCode.INHERITED_BRANCH_EVIDENCE,
            message=f"Step {ref.canonical_step_id} inherited from branch "
            f"{ref.resolved_branch_id} (ancestor resolution).",
        ))
    return rs


def resolve_run_step(ctx: SectionContext, ref: _ResolvedStepRef) -> RunStep | None:
    """Convenience wrapper that passes ctx.add_limitation to _resolve_run_step."""
    return _resolve_run_step(ctx.store, ref, ctx.plan_version_id, ctx.add_limitation)


class ReportCollector:
    """Collects evidence from immutable run artifacts and builds a ReportBundle."""

    def __init__(
        self,
        store: ProjectStore,
        project_id: str,
        run_id: str,
        target_branch_id: str,
        report_mode: ReportMode = "branch",
    ) -> None:
        self.store = store
        self.project_id = project_id
        self.run_id = run_id
        self.target_branch_id = target_branch_id
        self.report_mode = report_mode
        self.reader = ArtifactEvidenceReader(store)
        self.limitations: list[Limitation] = []

    def collect(self) -> ReportBundle:
        bundle = ReportBundle(
            schema_version="cardre.report_bundle.v1",
            project_id=self.project_id,
            run_id=self.run_id,
            target_branch_id=self.target_branch_id,
            report_mode=self.report_mode,
            generated_at=_utc_now(),
            generated_by=GeneratedBy(cardre_version=CARDRE_VERSION),
        )

        project = self.store.get_project(self.project_id)
        run = self.store.get_run(self.run_id)

        if project:
            bundle.summary.model_name = project.get("name", "")

        if run is None:
            self.limitations.append(Limitation(severity="blocker", code=LimitationCode.MISSING_RUN_MANIFEST, message="Run not found."))
            bundle.limitations = self.limitations
            return bundle

        plan_version_id = run["plan_version_id"]
        bundle.source.run_manifest_path = ""

        branch = self.store.get_branch(self.target_branch_id)
        if branch is None:
            self.limitations.append(Limitation(severity="blocker", code=LimitationCode.TARGET_BRANCH_NOT_FOUND, message=f"Branch {self.target_branch_id!r} not found."))
            bundle.limitations = self.limitations
            return bundle

        branch_head_pv = branch["head_plan_version_id"]
        bundle.summary.target_branch_id = self.target_branch_id

        step_map = self.store.get_branch_step_map(self.target_branch_id, plan_version_id)
        if not step_map and branch_head_pv:
            step_map = self.store.get_branch_step_map(self.target_branch_id, branch_head_pv)

        resolved = resolve_required_steps(
            branch_id=self.target_branch_id,
            canonical_step_ids=REQUIRED_STEPS_COLLECTOR,
            branch_step_map=step_map,
        )

        # Read canonical manifest before the section loop so SectionContext
        # can carry manifest_digest.
        manifest_digest = self._read_canonical_manifest()
        self.limitations.extend(manifest_digest.limitations)
        bundle.source.run_manifest_path = manifest_digest.source_run_manifest_path or ""
        bundle.source.run_manifest_hash = manifest_digest.manifest_hash or ""
        bundle.source.pathway_hash = manifest_digest.pathway_hash or ""
        bundle.source.artifact_root = manifest_digest.artifact_root or ""

        ctx = SectionContext(
            bundle=bundle,
            resolved=resolved,
            run=run,
            manifest_digest=manifest_digest,
            plan_version_id=plan_version_id,
            report_mode=self.report_mode,
            store=self.store,
            reader=self.reader,
            add_limitation=self.limitations.append,
        )

        for section in SECTION_COLLECTORS:
            section.build(ctx)

        bundle.limitations = self.limitations
        return bundle

    def _read_canonical_manifest(self) -> ManifestDigest:
        """Try to read the canonical manifest.json and return its validated digest.

        Validates the manifest payload against the RunManifest model and
        recomputes the self-referential hash (from the raw dict) to detect
        corruption or tampering.
        """
        manifest_path = self.store.root / "exports" / f"manifest-{self.run_id}" / "manifest.json"
        if not manifest_path.exists():
            return ManifestDigest(
                limitations=[Limitation(
                    severity="warning",
                    code=LimitationCode.CANONICAL_MANIFEST_MISSING,
                    message=f"No canonical manifest at {manifest_path}. "
                    "Manifest hash and pathway hash will be empty in the report.",
                )]
            )
        try:
            raw = manifest_path.read_text()
            manifest_data = loads(raw)

            # Validate schema — extra fields are rejected if present
            RunManifest.model_validate(manifest_data)

            # Hash the raw parsed dict, not the Pydantic model, so that
            # extra or unexpected fields are caught by the hash check.
            payload_for_hash = dict(manifest_data)
            payload_for_hash["manifest_hash"] = ""
            expected_hash = json_logical_hash(payload_for_hash)
            actual_hash = manifest_data.get("manifest_hash", "")

            if actual_hash != expected_hash:
                return ManifestDigest(
                    limitations=[Limitation(
                        severity="blocker",
                        code=LimitationCode.ARTIFACT_HASH_UNRESOLVED,
                        message=f"Canonical manifest hash mismatch at {manifest_path}: "
                        f"expected {expected_hash}, got {actual_hash}.",
                    )]
                )

            return ManifestDigest(
                manifest_hash=actual_hash,
                pathway_hash=manifest_data.get("pathway_hash") or None,
                execution_mode=str(manifest_data.get("execution_mode", "unknown")),
                target_step_id=manifest_data.get("target_step_id"),
                in_scope_step_ids=list(manifest_data.get("in_scope_step_ids", [])),
                source_run_manifest_path=str(manifest_path),
                artifact_root=str(manifest_data.get("artifact_root", "")) or None,
            )

        except JSONDecodeError as exc:
            return ManifestDigest(
                limitations=[Limitation(
                    severity="blocker",
                    code=LimitationCode.CANONICAL_MANIFEST_UNREADABLE,
                    message=f"Invalid JSON in canonical manifest at {manifest_path}: {exc}",
                )]
            )
        except Exception as exc:
            return ManifestDigest(
                limitations=[Limitation(
                    severity="blocker",
                    code=LimitationCode.CANONICAL_MANIFEST_UNREADABLE,
                    message=f"Could not read or validate canonical manifest at {manifest_path}: {exc}",
                )]
            )


def generate_report_bundle(
    store: ProjectStore,
    project_id: str,
    run_id: str,
    target_branch_id: str,
    report_mode: ReportMode = "branch",
) -> ReportBundle:
    """Generate a complete ReportBundle for the given branch and run."""
    collector = ReportCollector(
        store=store,
        project_id=project_id,
        run_id=run_id,
        target_branch_id=target_branch_id,
        report_mode=report_mode,
    )
    return collector.collect()
