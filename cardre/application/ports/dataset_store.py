"""Project-scoped storage for user-imported datasets."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO, Protocol


@dataclass(frozen=True)
class ImportedDataset:
    source_ref: str
    file_name: str
    size_bytes: int


class DatasetStorePort(Protocol):
    """Stores imported Parquet files under a single Project root."""

    def import_parquet(self, source: BinaryIO, file_name: str) -> ImportedDataset: ...

    def resolve_source(self, source_ref: str) -> Path: ...
