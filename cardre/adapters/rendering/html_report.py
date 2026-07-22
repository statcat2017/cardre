"""HTML report renderer — renders a ReportBundle into self-contained HTML.

Ports ``cardre.reporting.renderer_html`` to implement
``ReportRendererPort``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any


class HtmlReportRenderer:
    """Renders a report bundle dict into a self-contained HTML file.

    Delegates to the existing jinja2-based rendering pipeline.
    """

    def render(self, bundle: dict[str, Any], output_dir: Path) -> Path:
        """Render *bundle* to ``output_dir/report.html`` and return the path."""
        from cardre.reporting.renderer_html import render_report_bundle_to_html

        html = render_report_bundle_to_html(bundle)
        output_dir.mkdir(parents=True, exist_ok=True)
        path = output_dir / "report.html"
        path.write_text(html)
        return path

    @staticmethod
    def render_to_html(bundle: dict[str, Any]) -> str:
        """Return the HTML string without writing to disk."""
        from cardre.reporting.renderer_html import render_report_bundle_to_html

        return render_report_bundle_to_html(bundle)
