"""HTML report renderer for the port-native reporting pipeline."""

from __future__ import annotations

import html
from pathlib import Path

from cardre.application.reporting.schema import ReportBundle


class HtmlReportRenderer:
    """Render a report bundle as a self-contained offline HTML document."""

    def render(self, bundle: ReportBundle, output_dir: Path) -> Path:
        output_dir.mkdir(parents=True, exist_ok=True)
        path = output_dir / "report.html"
        path.write_text(self.render_to_html(bundle), encoding="utf-8")
        return path

    @staticmethod
    def render_to_html(bundle: ReportBundle) -> str:
        data = bundle.model_dump(mode="json")
        title = html.escape(data["summary"].get("model_name") or "Cardre governance report")
        rows = "".join(
            "<tr>"
            f"<td>{html.escape(step['canonical_step_id'])}</td>"
            f"<td>{html.escape(step['status'])}</td>"
            f"<td>{html.escape(step['resolution'])}</td>"
            "</tr>"
            for step in data["pathway"]["steps"]
        ) or "<tr><td colspan=\"3\">No pathway evidence</td></tr>"
        limitations = "".join(
            f"<li>{html.escape(item['severity'])}: {html.escape(item['code'])} - {html.escape(item['message'])}</li>"
            for item in data["limitations"]
        ) or "<li>None</li>"
        return (
            "<!doctype html><html><head><meta charset=\"utf-8\">"
            f"<title>{title}</title><style>body{{font-family:system-ui;margin:2rem}}"
            "table{border-collapse:collapse}th,td{border:1px solid #ddd;padding:.5rem;text-align:left}"
            "</style></head>"
            f"<body><h1>{title}</h1><p>Run: {html.escape(data['run_id'])}</p>"
            f"<p>Status: {html.escape(data['report_status'])}</p><h2>Pathway</h2>"
            f"<table><tr><th>Step</th><th>Status</th><th>Resolution</th></tr>{rows}</table>"
            f"<h2>Limitations</h2><ul>{limitations}</ul></body></html>"
        )
