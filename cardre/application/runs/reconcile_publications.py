"""ReconcilePublications — retry incomplete filesystem publications on startup.

Scans the publication outbox for ``pending``/``failed`` rows and completes
the filesystem side of each publication: artifact staging files are moved to
their content-addressed object path, and manifests are republished from the
stored canonical payload. Idempotent — republishing an already-written
manifest or finalizing an already-present object is a no-op.

The per-publication protocol (finalize + mark_published / mark_failed) is
owned by ``PublicationPublisher``; this module is the thin startup driver
that lists pending rows, dispatches each by kind, and collects outcomes.
"""

from __future__ import annotations

from collections.abc import Callable
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
        publication_publisher_factory: Callable[[str], Any],
        artifact_store_factory: Callable[[str], Any],
        manifest_publisher_factory: Callable[[str], Any],
    ) -> None:
        self._uow_factory = uow_factory
        self._project_registry = project_registry
        self._publication_publisher_factory = publication_publisher_factory
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
            publisher = self._publication_publisher_factory(project_id)
            for row in pending:
                if row["kind"] == "artifact":
                    outcome.results.append(self._reconcile_artifact(project_id, publisher, row))
                elif row["kind"] == "manifest":
                    outcome.results.append(self._reconcile_manifest(project_id, publisher, row))
        return outcome

    def _reconcile_artifact(
        self, project_id: str, publisher: Any, row: dict[str, Any]
    ) -> ReconcileResult:
        outbox_id = row["outbox_id"]
        try:
            store = self._artifact_store_factory(project_id)
            publisher.publish(
                outbox_id,
                lambda: store.finalize_staged_file(
                    row["staging_source"],
                    row["physical_hash"],
                ),
            )
            return ReconcileResult(row["run_id"], "artifact", outbox_id, "published")
        except Exception as exc:
            return ReconcileResult(row["run_id"], "artifact", outbox_id, "failed", str(exc))

    def _reconcile_manifest(
        self, project_id: str, publisher: Any, row: dict[str, Any]
    ) -> ReconcileResult:
        outbox_id = row["outbox_id"]
        payload = row.get("manifest_payload")
        if payload is None:
            msg = "manifest outbox row has no stored payload"
            self._mark_failed(project_id, outbox_id, msg)
            return ReconcileResult(row["run_id"], "manifest", outbox_id, "failed", msg)
        try:
            manifest_publisher = self._manifest_publisher_factory(project_id)
            publisher.publish(
                outbox_id,
                lambda: manifest_publisher.publish(row["run_id"], payload),
            )
            return ReconcileResult(row["run_id"], "manifest", outbox_id, "published")
        except Exception as exc:
            return ReconcileResult(row["run_id"], "manifest", outbox_id, "failed", str(exc))

    def _mark_failed(self, project_id: str, outbox_id: str, error: str) -> None:
        """Mark a row failed directly for a data-integrity guard (no payload).

        This is not a publish attempt, so the publisher's failure protocol
        does not apply — there is nothing to finalize.
        """
        with self._uow_factory.for_project(project_id) as uow:
            uow.publications.mark_failed(outbox_id, error)
            uow.commit()


__all__ = ["ReconcilePublications", "ReconcileResult", "ReconcileOutcome"]
