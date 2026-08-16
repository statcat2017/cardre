"""Shared node output helpers.

The ``publish_json(report) + add_metric(...) + build_result()`` tail repeats
across a dozen node modules.  ``publish_report`` collapses it into one call.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import polars as pl

from cardre.domain.evidence.kinds import EvidenceKind
from cardre.nodes.contracts import NodeContext

NUMERIC_DTYPES = (
    pl.Float64,
    pl.Float32,
    pl.Int64,
    pl.Int32,
    pl.Int16,
    pl.Int8,
    pl.UInt64,
    pl.UInt32,
    pl.UInt16,
    pl.UInt8,
)


def publish_report(
    context: NodeContext,
    *,
    kind: EvidenceKind,
    payload: dict[str, Any],
    schema_version: str,
    metrics: Mapping[str, float | int | str | bool] | None = None,
) -> None:
    """Publish a JSON report artifact and its metrics in one call."""
    context.outputs.publish_json(
        role="report",
        kind=kind,
        payload=payload,
        metadata={"schema_version": schema_version},
    )
    for name, value in (metrics or {}).items():
        context.outputs.add_metric(name, value)
