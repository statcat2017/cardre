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
        variables = "".join(
            "<tr>"
            f"<td>{html.escape(variable['variable_name'])}</td>"
            f"<td>{html.escape(variable['role'])}</td>"
            f"<td>{variable['iv']:.4f}</td>"
            f"<td>{variable['final_bin_count']}</td>"
            "</tr>"
            for variable in data["variables"]
        ) or "<tr><td colspan=\"4\">No WOE/IV evidence</td></tr>"
        metrics = "".join(
            "<tr>"
            f"<td>{html.escape(metric['role'])}</td>"
            f"<td>{metric['auc'] if metric['auc'] is not None else 'N/A'}</td>"
            f"<td>{metric['gini'] if metric['gini'] is not None else 'N/A'}</td>"
            f"<td>{metric['ks'] if metric['ks'] is not None else 'N/A'}</td>"
            "</tr>"
            for metric in data["validation"]["metrics_by_role"]
        ) or "<tr><td colspan=\"4\">No validation evidence</td></tr>"
        model = data["model"]
        scaling = data["score_scaling"]
        return (
            "<!doctype html><html><head><meta charset=\"utf-8\">"
            f"<title>{title}</title><style>body{{font-family:system-ui;margin:2rem}}"
            "table{border-collapse:collapse}th,td{border:1px solid #ddd;padding:.5rem;text-align:left}"
            "</style></head>"
            f"<body><h1>{title}</h1><p>Run: {html.escape(data['run_id'])}</p>"
            f"<p>Status: {html.escape(data['report_status'])}</p><h2>Pathway</h2>"
            f"<table><tr><th>Step</th><th>Status</th><th>Resolution</th></tr>{rows}</table>"
            "<h2>Variables</h2><table><tr><th>Variable</th><th>Role</th><th>IV</th><th>Bins</th></tr>"
            f"{variables}</table><h2>Model</h2><p>Type: {html.escape(model['model_type'])}; "
            f"intercept: {model['intercept']}</p><h2>Score Scaling</h2><p>Base score: {scaling['base_score']}; "
            f"PDO: {scaling['points_to_double_odds']}</p><h2>Validation</h2>"
            f"<table><tr><th>Role</th><th>AUC</th><th>Gini</th><th>KS</th></tr>{metrics}</table>"
            f"<h2>Limitations</h2><ul>{limitations}</ul></body></html>"
        )
