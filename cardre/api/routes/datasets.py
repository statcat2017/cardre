"""Project-scoped dataset import endpoints."""

from __future__ import annotations

from tempfile import SpooledTemporaryFile
from urllib.parse import unquote

from fastapi import APIRouter, Depends, Header, Request

from cardre.api.dependencies import get_container
from cardre.api.errors import CardreApiError, ErrorCode
from cardre.api.schemas import DatasetImportResponse, ErrorResponse
from cardre.application.datasets.constants import MAX_DATASET_BYTES
from cardre.application.datasets.import_dataset import ImportDataset, ImportDatasetCommand
from cardre.bootstrap.container import Container

router = APIRouter(prefix="/projects/{project_id}/datasets", tags=["datasets"])


@router.post(
    "",
    response_model=DatasetImportResponse,
    status_code=201,
    responses={
        413: {"model": ErrorResponse, "description": "Dataset exceeds the upload limit."},
        415: {"model": ErrorResponse, "description": "Unsupported upload content type."},
    },
    openapi_extra={
        "requestBody": {
            "required": True,
            "content": {
                "application/octet-stream": {
                    "schema": {"type": "string", "format": "binary"}
                },
                "application/vnd.apache.parquet": {
                    "schema": {"type": "string", "format": "binary"}
                },
            },
        }
    },
)
async def import_dataset(
    project_id: str,
    request: Request,
    file_name: str = Header(alias="X-File-Name", min_length=1, max_length=1024),
    container: Container = Depends(get_container),
) -> DatasetImportResponse:
    """Import a Parquet file without accepting a client-controlled path."""
    content_type = request.headers.get("content-type", "").split(";", maxsplit=1)[0].strip().lower()
    if content_type not in {"application/octet-stream", "application/vnd.apache.parquet"}:
        raise CardreApiError(
            code=ErrorCode.DATASET_INVALID,
            message="Upload the selected file as Parquet binary data.",
            status_code=415,
        )
    display_name = unquote(file_name)
    if not display_name.replace("\\", "/").rsplit("/", maxsplit=1)[-1].lower().endswith(
        ".parquet"
    ):
        raise CardreApiError(
            code=ErrorCode.DATASET_INVALID,
            message="Choose a Parquet file with a .parquet extension.",
            status_code=422,
        )

    declared_size = request.headers.get("content-length")
    if declared_size is not None:
        try:
            if int(declared_size) > MAX_DATASET_BYTES:
                raise _upload_too_large()
        except ValueError as exc:
            raise CardreApiError(
                code=ErrorCode.BAD_REQUEST,
                message="The upload size header is invalid.",
                status_code=400,
            ) from exc

    total_size = 0
    with SpooledTemporaryFile(max_size=8 * 1024 * 1024, mode="w+b") as content:
        async for chunk in request.stream():
            total_size += len(chunk)
            if total_size > MAX_DATASET_BYTES:
                raise _upload_too_large()
            content.write(chunk)
        content.seek(0)
        imported = ImportDataset(container.dataset_store_factory)(
            ImportDatasetCommand(
                project_id=project_id,
                file_name=display_name,
                content=content,
            )
        )

    return DatasetImportResponse(
        source_ref=imported.source_ref,
        file_name=imported.file_name,
        size_bytes=imported.size_bytes,
    )


def _upload_too_large() -> CardreApiError:
    return CardreApiError(
        code=ErrorCode.UPLOAD_TOO_LARGE,
        message="The selected dataset exceeds the 1 GiB upload limit.",
        status_code=413,
        context={"max_bytes": MAX_DATASET_BYTES},
    )
