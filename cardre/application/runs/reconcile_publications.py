"""ReconcilePublications — retry incomplete filesystem publications on startup.

Scans the publication outbox for ``pending``/``failed`` rows and completes
the filesystem side of each publication: artifact staging files are moved to
their content-addressed object path, and manifests are republished from the
stored canonical payload. Idempotent — republishing an already-written
manifest or finalizing an already-present object is a no-op.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class ReconcileResult:
    run_id: str
    kind: str
    outbox_id: str
    state: str
    error: str = ""


@dataclass
class ReconcileOutcome:
    results: list[ReconcileResult] = field(default_factory=list)

    @property
    def published(self) -> int:
        return sum(1 for r in self.results if r.state == "published")

    @property
    def failed(self) -> int:
        return sum(1 for r in self.results if r.state == "failed")


class ReconcilePublications:
    def __init__(
        self,
        uow_factory: Any,
        project_registry: Any,
        artifact_store_factory: Any,
        manifest_publisher_factory: Any,
    ) -> None:
        self._uow_factory = uow_factory
        self._project_registry = project_registry
        self._artifact_store_factory = artifact_store_factory
        self._manifest_publisher_factory = manifest_publisher_factory

    def __call__(self) -> ReconcileOutcome:
        outcome = ReconcileOutcome()
        for project_id, root in self._project_registry.list_all().items():
            if not (Path(root) / "project.sqlite").exists():
                continue
            try:
                with self._uow_factory.read_only(project_id) as uow:
                    pending = uow.publications.list_pending()
            except Exception:
                continue
            for row in pending:
                if row["kind"] == "artifact":
                    outcome.results.append(self._reconcile_artifact(project_id, row))
                elif row["kind"] == "manifest":
                    outcome.results.append(self._reconcile_manifest(project_id, row))
        return outcome

    def _reconcile_artifact(self, project_id: str, row: dict[str, Any]) -> ReconcileResult:
        outbox_id = row["outbox_id"]
        artifact_store = self._artifact_store_factory(project_id)
        try:
            artifact_store.finalize_staged_file(row["staging_source"], row["physical_hash"])
        except Exception as exc:
            self._mark(project_id, outbox_id, "failed", str(exc))
            return ReconcileResult(row["run_id"], "artifact", outbox_id, "failed", str(exc))
        self._mark(project_id, outbox_id, "published", "")
        return ReconcileResult(row["run_id"], "artifact", outbox_id, "published")

    def _reconcile_manifest(self, project_id: str, row: dict[str, Any]) -> ReconcileResult:
        outbox_id = row["outbox_id"]
        payload = row.get("manifest_payload")
        if payload is None:
            msg = "manifest outbox row has no stored payload"
            self._mark(project_id, outbox_id, "failed", msg)
            return ReconcileResult(row["run_id"], "manifest", outbox_id, "failed", msg)
        try:
            self._manifest_publisher_factory(project_id).publish(row["run_id"], payload)
        except Exception as exc:
            self._mark(project_id, outbox_id, "failed", str(exc))
            return ReconcileResult(row["run_id"], "manifest", outbox_id, "failed", str(exc))
        self._mark(project_id, outbox_id, "published", "")
        return ReconcileResult(row["run_id"], "manifest", outbox_id, "published")

    def _mark(self, project_id: str, outbox_id: str, state: str, error: str) -> None:
        with self._uow_factory.for_project(project_id) as uow:
            if state == "published":
                uow.publications.mark_published(outbox_id)
            else:
                uow.publications.mark_failed(outbox_id, error)
            uow.commit()


__all__ = ["ReconcilePublications", "ReconcileResult", "ReconcileOutcome"]
