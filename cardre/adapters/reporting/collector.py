"""Report collector adapter — currently requires a ProjectStore.

Port-native report generation is not yet implemented.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from cardre.reporting.schema import ReportBundle
from cardre.reporting.types import ReportMode


def generate_report_bundle(
    project_root: Path,
    project_id: str,
    run_id: str,
    target_branch_id: str,
    report_mode: ReportMode = "branch",
    *,
    store: Any = None,
) -> ReportBundle:
    if store is None:
        raise NotImplementedError(
            "Port-only report generation is not yet implemented. "
            "Call generate_report_bundle with a store= argument."
        )
    from cardre.reporting.collector import generate_report_bundle as _old
    return _old(
        store=store,
        project_id=project_id,
        run_id=run_id,
        target_branch_id=target_branch_id,
        report_mode=report_mode,
    )
