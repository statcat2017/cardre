"""Publication protocol — one post-commit finalize + mark seam.

After the DB transaction that enqueues a publication-outbox row commits, the
filesystem side of the publication must still run: a staged artifact is moved
to its content-addressed object path, or a manifest is written. This module
owns the protocol and the outbox-row state transition that follows it.

The seam is a single ``publish(outbox_id, writer)`` call. The caller supplies
the adapter operation that performs the filesystem write — it keeps ownership
of its writer (artifact store, manifest publisher, or a persisted-outbox
retry operation). ``PublicationPublisher`` owns only the protocol:

1. Run the caller's writer.
2. On success: open UoW → ``mark_published(outbox_id)`` → commit.
3. On failure: open UoW → ``mark_failed(outbox_id, error)`` → commit → re-raise.

The protocol is idempotent — finalizing an already-present file and marking an
already-published row are no-ops. Reconciliation (``ReconcilePublications``)
delegates here rather than re-implementing the dance.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any


class PublicationPublisher:
    """Owns the post-commit publication protocol for outbox rows.

    Depends only on a UoW factory: it performs no filesystem writes itself.
    Callers pass the writer operation that does the write.
    """

    def __init__(self, uow_factory: Callable[[], Any]) -> None:
        self._uow_factory = uow_factory

    def publish(self, outbox_id: str, writer: Callable[[], object]) -> None:
        """Run the caller's writer and transition the outbox row.

        On writer failure, marks the row ``failed`` with the error string and
        re-raises so the caller can decide whether to propagate or continue to
        the next publication. On success, marks the row ``published``.

        If recording the failure also errors (e.g. the mark transaction
        cannot open), the writer's exception is preserved as the primary
        failure with the recording error chained as its cause.
        """
        try:
            writer()
        except Exception as exc:
            try:
                self._mark(outbox_id, failed=True, error=str(exc))
            except Exception as mark_exc:
                raise exc from mark_exc
            raise
        self._mark(outbox_id, failed=False)

    def _mark(self, outbox_id: str, *, failed: bool, error: str = "") -> None:
        uow = self._uow_factory()
        try:
            if failed:
                uow.publications.mark_failed(outbox_id, error)
            else:
                uow.publications.mark_published(outbox_id)
            uow.commit()
        except Exception:
            uow.rollback()
            raise
        finally:
            uow.close()


__all__ = ["PublicationPublisher"]
