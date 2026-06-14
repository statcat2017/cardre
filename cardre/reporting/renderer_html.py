"""Table-first offline HTML renderer for Cardre governance reports.

Renders a ReportBundle into self-contained offline HTML with embedded
CSS and no external dependencies. Table-first, no charts, no JS.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import jinja2
from jinja2 import Environment, FileSystemLoader

_TEMPLATE_PATH = Path(__file__).parent / "templates" / "report.html.j2"


def render_report_bundle_to_html(bundle: dict[str, Any]) -> str:
    """Render a report bundle dict into self-contained offline HTML.

    The bundle is the JSON-serialized form of``ReportBundle``
    (model_dump(mode='json')).
    """
    env = Environment(
        loader=FileSystemLoader(str(_TEMPLATE_PATH.parent)),
        autoescape=True,
        trim_blocks=True,
        lstrip_blocks=True,
    )

    def fmt(value: Any, spec: str = ".4f") -> str:
        """Safely format a number. Returns 'N/A' for None/missing/undefined."""
        if value is None:
            return "N/A"
        try:
            return format(float(value), spec)
        except (TypeError, ValueError, jinja2.UndefinedError):
            return "N/A"

    env.filters["fmt"] = fmt
    template = env.get_template(_TEMPLATE_PATH.name)

    summary = bundle.get("summary", {}) or {}
    limitations = bundle.get("limitations", []) or []
    variables = bundle.get("variables", []) or []
    model = bundle.get("model", {}) or {}
    score_scaling = bundle.get("score_scaling", {}) or {}
    validation = bundle.get("validation", {}) or {}
    cutoffs = bundle.get("cutoffs", {}) or {}
    champion = bundle.get("champion", {}) or {}
    branches = bundle.get("branches", {}) or {}
    reproducibility = bundle.get("reproducibility", {}) or {}
    artifacts = bundle.get("artifacts", []) or []
    manual_interventions = bundle.get("manual_interventions", []) or []
    pathway = bundle.get("pathway", {}) or {}

    html = template.render(
        project_name=summary.get("model_name", ""),
        run_id=bundle.get("run_id", ""),
        target_branch_id=bundle.get("target_branch_id", ""),
        report_mode=bundle.get("report_mode", "branch"),
        report_status=summary.get("report_status", ""),
        generated_at=bundle.get("generated_at", ""),
        summary=summary,
        limitations=limitations,
        variables=variables,
        model=model,
        score_scaling=score_scaling,
        validation=validation,
        cutoffs=cutoffs,
        champion=champion,
        branches=branches,
        reproducibility=reproducibility,
        artifacts=artifacts,
        manual_interventions=manual_interventions,
        pathway=pathway,
    )
    return html


def write_html_report(path: Path, bundle: dict[str, Any]) -> None:
    """Render and write the HTML report to *path*."""
    html = render_report_bundle_to_html(bundle)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(html)
