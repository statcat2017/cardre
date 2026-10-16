"""Import a Parquet dataset into its owning Project."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import BinaryIO

from cardre.application.ports.dataset_store import DatasetStorePort, ImportedDataset


@dataclass(frozen=True)
class ImportDatasetCommand:
    project_id: str
    file_name: str
    content: BinaryIO


class ImportDataset:
    def __init__(self, store_factory: Callable[[str], DatasetStorePort]) -> None:
        self._store_factory = store_factory

    def __call__(self, command: ImportDatasetCommand) -> ImportedDataset:
        return self._store_factory(command.project_id).import_parquet(
            command.content, command.file_name
        )


@dataclass(frozen=True)
class ResolveDatasetSourceCommand:
    project_id: str
    source_ref: str


class ResolveDatasetSource:
    def __init__(self, store_factory: Callable[[str], DatasetStorePort]) -> None:
        self._store_factory = store_factory

    def __call__(self, command: ResolveDatasetSourceCommand):
        return self._store_factory(command.project_id).resolve_source(command.source_ref)
