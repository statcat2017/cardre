"""Read immutable scoring outputs and render downloadable presentations."""

from __future__ import annotations

import io
import json
from collections.abc import Callable
from dataclasses import dataclass

import polars as pl

from cardre.application.ports.artifact_store import ArtifactReader
from cardre.application.ports.unit_of_work import UnitOfWorkFactory
from cardre.application.reporting.report_queries import SCORING_EXPORT_FORMATS
from cardre.domain.artifacts import ArtifactRef
from cardre.domain.errors import CardreError, ErrorCode
from cardre.domain.evidence.schemas import SCHEMA_SCORING_EXPORT_PYTHON, SCHEMA_SCORING_EXPORT_SQL


@dataclass(frozen=True)
class DownloadableScoringExport:
    artifact_id: str
    run_id: str
    export_type: str
    file_name: str
    media_type: str
    content: bytes


class DownloadScoringExport:
    """Download only recognized output artifacts linked to a successful run."""

    def __init__(
        self,
        uow_factory: UnitOfWorkFactory,
        artifact_reader_factory: Callable[[str], ArtifactReader],
    ) -> None:
        self._uow_factory = uow_factory
        self._artifact_reader_factory = artifact_reader_factory

    def __call__(self, project_id: str, run_id: str, artifact_id: str) -> DownloadableScoringExport:
        with self._uow_factory.read_only(project_id) as uow:
            run = uow.runs.get(run_id)
            if run is None:
                raise CardreError(
                    f"Run {run_id!r} not found.",
                    code=ErrorCode.RUN_NOT_FOUND,
                    context={"run_id": run_id},
                )
            if run.status != "succeeded":
                raise CardreError(
                    f"Scoring exports are unavailable until run {run_id!r} succeeds.",
                    code=ErrorCode.EXPORT_RUN_NOT_FOUND,
                    context={"run_id": run_id, "status": run.status},
                )

            if artifact_id not in set(uow.artifacts.output_artifact_ids_for_run(run_id)):
                raise _artifact_not_found(artifact_id)
            artifact = uow.artifacts.get(artifact_id)
            if artifact is None:
                raise _artifact_not_found(artifact_id)
            export_format = SCORING_EXPORT_FORMATS.get(artifact.artifact_type)
            if export_format is None:
                raise _artifact_not_found(artifact_id)

            try:
                raw = self._artifact_reader_factory(project_id).read_bytes(artifact)
                content = _render_export(artifact, raw)
            except (
                OSError,
                UnicodeDecodeError,
                ValueError,
                TypeError,
                pl.exceptions.PolarsError,
            ) as exc:
                raise CardreError(
                    "Persisted scoring export is unreadable or does not match its expected schema.",
                    code=ErrorCode.ARTIFACT_INVALID,
                    context={"artifact_id": artifact_id, "artifact_type": artifact.artifact_type},
                ) from exc

        return DownloadableScoringExport(
            artifact_id=artifact.artifact_id,
            run_id=run_id,
            export_type=export_format.export_type,
            file_name=export_format.file_name,
            media_type=export_format.media_type,
            content=content,
        )


def _artifact_not_found(artifact_id: str) -> CardreError:
    return CardreError(
        f"Scoring export artifact {artifact_id!r} not found for this run.",
        code=ErrorCode.ARTIFACT_NOT_FOUND,
        context={"artifact_id": artifact_id},
    )


def _render_export(artifact: ArtifactRef, raw: bytes) -> bytes:
    if artifact.artifact_type == "scorecard_table":
        table = pl.read_parquet(io.BytesIO(raw))
        expected_columns = {"variable", "bin_id", "label", "woe", "coefficient", "points"}
        if not expected_columns.issubset(table.columns):
            raise ValueError("Persisted scorecard table is missing required export columns.")
        return table.write_csv().encode("utf-8")

    payload = json.loads(raw.decode("utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("Persisted scoring source must be a JSON object.")
    expected_schema = {
        "scoring_export_python": SCHEMA_SCORING_EXPORT_PYTHON,
        "scoring_export_sql": SCHEMA_SCORING_EXPORT_SQL,
    }[artifact.artifact_type]
    if payload.get("schema_version") != expected_schema:
        raise ValueError("Persisted scoring source has an unexpected schema version.")
    source = payload.get("source")
    if not isinstance(source, str) or not source.strip():
        raise ValueError("Persisted scoring source is empty or malformed.")
    return source.encode("utf-8")
