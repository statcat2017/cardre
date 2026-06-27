"""Artifact retrieval, summary, and preview logic.

Polars-based data inspection lives here, not in route handlers.
"""

from __future__ import annotations

from pathlib import Path

import polars as pl

from cardre.store import ProjectStore
from cardre.services.project_registry import load_registry


def scan_all_stores():
    registry = load_registry()
    for pid, entry in registry.items():
        store = ProjectStore(Path(entry["path"]))
        yield pid, store


def find_artifact(artifact_id: str):
    for pid, store in scan_all_stores():
        artifact = store.get_artifact(artifact_id)
        if artifact is not None:
            return artifact, store
    return None, None


def build_json_summary_preview(data) -> dict | None:
    """Build a summary preview dict from JSON artifact content."""
    if isinstance(data, dict):
        preview = {k: data[k] for k in list(data.keys())[:10]}
        preview["_key_count"] = len(data)
        return preview
    elif isinstance(data, list):
        return {"_item_count": len(data), "_first_items": data[:5]}
    elif data is not None:
        return {"_value": str(data)[:500]}
    return None


def build_parquet_preview(
    artifact_path: Path,
    offset: int = 0,
    limit: int = 100,
    total_rows: int | None = None,
) -> dict:
    """Read a slice of a Parquet file and return column info + rows."""
    if total_rows is None:
        total_rows = pl.scan_parquet(artifact_path).select(pl.len()).collect().item()
    df = pl.scan_parquet(artifact_path).slice(offset, limit).collect()
    return {
        "total_rows": total_rows,
        "columns": [{"name": c, "dtype": str(df.schema[c])} for c in df.columns],
        "rows": df.to_dicts(),
    }
