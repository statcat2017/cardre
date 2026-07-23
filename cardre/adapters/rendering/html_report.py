"""HTML report renderer for the port-native reporting pipeline.

Renders every section of the ReportBundle as a self-contained offline HTML
document, preserving the full report structure from the legacy renderer.
"""

from __future__ import annotations

import html
from pathlib import Path
from typing import Any

from cardre.application.reporting.schema import ReportBundle


def _esc(value: Any) -> str:
    return html.escape(str(value) if value is not None else "")


def _fmt(value: Any, ndigits: int = 4) -> str:
    if value is None:
        return "N/A"
    if isinstance(value, float):
        return f"{value:.{ndigits}f}"
    return _esc(value)


def _section(title: str, body: str) -> str:
    return f"<h2>{html.escape(title)}</h2>{body}"


def _table(headers: list[str], rows: list[list[str]]) -> str:
    head = "".join(f"<th>{html.escape(h)}</th>" for h in headers)
    body = "".join(
        "<tr>" + "".join(f"<td>{cell}</td>" for cell in row) + "</tr>"
        for row in rows
    )
    if not body:
        body = "<tr><td colspan='" + str(len(headers)) + "'>No data</td></tr>"
    return f"<table><tr>{head}</tr>{body}</table>"


def _kv_list(items: list[tuple[str, str]]) -> str:
    return "".join(f"<p><strong>{html.escape(k)}:</strong> {_esc(v)}</p>" for k, v in items)


def _render_pathway(data: dict[str, Any]) -> str:
    rows = [
        [_esc(step["canonical_step_id"]), _esc(step["status"]), _esc(step["resolution"])]
        for step in data["pathway"]["steps"]
    ]
    return _table(["Step", "Status", "Resolution"], rows)


def _render_dataset_roles(data: dict[str, Any]) -> str:
    roles = data["dataset_roles"]
    if not roles:
        return "<p>No dataset role evidence</p>"
    rows = [
        [_esc(r["role"]), _esc(r["dataset_id"]), str(r["row_count"]), str(r["column_count"]),
         f"{r['target']['good_count']} / {r['target']['bad_count']}", _fmt(r["target"]["bad_rate"])]
        for r in roles
    ]
    return _table(["Role", "Dataset ID", "Rows", "Cols", "Good/Bad", "Bad Rate"], rows)


def _render_branches(data: dict[str, Any]) -> str:
    branches = data["branches"]["branches"]
    if not branches:
        return "<p>No branch evidence</p>"
    rows = [
        [_esc(b["branch_id"]), _esc(b["name"]), _esc(b.get("parent_branch_id") or "—"),
         "yes" if b["is_target_branch"] else "no", "yes" if b["is_champion"] else "no",
         _esc(b["status"])]
        for b in branches
    ]
    return _table(["Branch ID", "Name", "Parent", "Target", "Champion", "Status"], rows)


def _render_champion(data: dict[str, Any]) -> str:
    c = data["champion"]
    if c["champion_status"] == "not_available":
        return "<p>No champion assigned</p>"
    return _kv_list([
        ("Status", c["champion_status"]),
        ("Champion branch", c.get("champion_branch_id") or "—"),
        ("Assignment ID", c.get("assignment_id") or "—"),
        ("Rationale", c.get("rationale") or "—"),
        ("Selected at", c.get("selected_at") or "—"),
        ("Target is champion", "yes" if c["target_branch_is_champion"] else "no"),
    ])


def _render_variables(data: dict[str, Any]) -> str:
    rows = [
        [_esc(v["variable_name"]), _esc(v["role"]), _fmt(v["iv"]), str(v["final_bin_count"]),
         _esc(v.get("monotonicity_status") or "—"), "yes" if v.get("manual_edits") else "no"]
        for v in data["variables"]
    ]
    return _table(["Variable", "Role", "IV", "Bins", "Monotonicity", "Manual edits"], rows)


def _render_model(data: dict[str, Any]) -> str:
    m = data["model"]
    parts = [_kv_list([
        ("Type", m["model_type"]), ("Target", m["target"]),
        ("Intercept", _fmt(m["intercept"])),
        ("Fit dataset", m["fit_dataset_role"]),
    ])]
    rows = [
        [_esc(f["variable_name"]), _fmt(f["coefficient"]),
         _fmt(f.get("standard_error")), _fmt(f.get("p_value")),
         "yes" if f.get("included", True) else "no"]
        for f in m["features"]
    ]
    parts.append(_table(["Feature", "Coefficient", "Std Error", "P-value", "Included"], rows))
    return "".join(parts)


def _render_score_scaling(data: dict[str, Any]) -> str:
    s = data["score_scaling"]
    return _kv_list([
        ("Base score", str(s["base_score"])),
        ("Base odds", s["base_odds"]),
        ("PDO", str(s["points_to_double_odds"])),
        ("Factor", _fmt(s["factor"])),
        ("Offset", _fmt(s["offset"])),
        ("Direction", s["score_direction"]),
        ("Rounding", s["rounding"]),
        ("Min score", str(s["min_score"])),
        ("Max score", str(s["max_score"])),
    ])


def _render_validation(data: dict[str, Any]) -> str:
    v = data["validation"]
    rows = [
        [_esc(m["role"]), str(m["row_count"]), _fmt(m["auc"]), _fmt(m["gini"]),
         _fmt(m["ks"]), _fmt(m.get("bad_rate"))]
        for m in v["metrics_by_role"]
    ]
    parts = [_table(["Role", "Rows", "AUC", "Gini", "KS", "Bad Rate"], rows)]
    if v["stability"]["psi_by_role"]:
        psi_rows = [[_esc(p["comparison"]), _fmt(p["score_psi"])] for p in v["stability"]["psi_by_role"]]
        parts.append(f"<h3>Stability (PSI)</h3>{_table(['Comparison', 'Score PSI'], psi_rows)}")
    return "".join(parts)


def _render_cutoffs(data: dict[str, Any]) -> str:
    c = data["cutoffs"]
    parts: list[str] = []
    for table in c["cutoff_tables"]:
        rows = [
            [_fmt(r["score_cutoff"]), _fmt(r["approval_rate"]), _fmt(r["bad_rate"]), _fmt(r["capture_rate"])]
            for r in table["rows"]
        ]
        parts.append(f"<h3>{html.escape(table['role'])}</h3>{_table(['Cutoff', 'Approval Rate', 'Bad Rate', 'Capture Rate'], rows)}")
    sc = c.get("selected_cutoff") or {}
    if sc.get("score") is not None:
        parts.append(f"<p><strong>Selected cutoff:</strong> {sc['score']} ({_esc(sc.get('selection_reason', ''))})</p>")
    return "".join(parts) or "<p>No cutoff evidence</p>"


def _render_manual_interventions(data: dict[str, Any]) -> str:
    rows = [
        [_esc(i["intervention_id"]), _esc(i["canonical_step_id"]), _esc(i["variable_name"]),
         _esc(i["type"]), _esc(i["reason"]), _esc(i["created_at"])]
        for i in data["manual_interventions"]
    ]
    return _table(["ID", "Step", "Variable", "Type", "Reason", "Created"], rows)


def _render_manual_binning_review(data: dict[str, Any]) -> str:
    r = data["manual_binning_review"]
    return _kv_list([
        ("Review status", r["review_status"]),
        ("Accepted automated", "yes" if r["accepted_automated"] else "no"),
        ("Edited variable count", str(r["edited_variable_count"])),
        ("Variables edited", ", ".join(r["variables_edited"]) or "—"),
        ("Reasons", "; ".join(r["reasons"]) or "—"),
        ("Reviewed at", r.get("reviewed_at") or "—"),
        ("Reviewed by", r.get("reviewed_by") or "—"),
        ("Review reason", r.get("review_reason") or "—"),
    ])


def _render_redundancy_review(data: dict[str, Any]) -> str:
    r = data["redundancy_review"]
    parts = [_kv_list([
        ("Method", r["method"]), ("Similarity metric", r["similarity_metric"]),
        ("Threshold", _fmt(r["threshold"]) if r["threshold"] is not None else "—"),
        ("Cluster count", str(r["cluster_count"])),
        ("Singleton count", str(r["singleton_count"])),
    ])]
    if r["clusters"]:
        rows = [
            [_esc(c["cluster_id"]), ", ".join(m["variable"] for m in c["variables"]),
             _esc(c.get("representative_suggestion") or "—")]
            for c in r["clusters"]
        ]
        parts.append(_table(["Cluster", "Variables", "Representative"], rows))
    if r["singleton_variables"]:
        parts.append(f"<p><strong>Singletons:</strong> {html.escape(', '.join(r['singleton_variables']))}</p>")
    return "".join(parts) or "<p>No redundancy review</p>"


def _render_limitations(data: dict[str, Any]) -> str:
    items = "".join(
        f"<li class='{html.escape(i['severity'])}'>"
        f"<strong>{html.escape(i['severity'])}</strong>: "
        f"{html.escape(i['code'])} — {html.escape(i['message'])}</li>"
        for i in data["limitations"]
    )
    return f"<ul>{items or '<li>None</li>'}</ul>"


def _render_reproducibility(data: dict[str, Any]) -> str:
    r = data["reproducibility"]
    parts = [_kv_list([
        ("Run ID", r["run_id"]),
        ("Manifest hash", r.get("manifest_hash") or "—"),
        ("Pathway hash", r.get("pathway_hash") or "—"),
    ])]
    if r.get("execution_fingerprints"):
        rows = [
            [_esc(f["step_id"]), _esc(f.get("canonical_step_id", "")),
             _esc(f.get("python_version", "")), _esc(f.get("platform", ""))]
            for f in r["execution_fingerprints"]
        ]
        parts.append(_table(["Step", "Canonical", "Python", "Platform"], rows))
    rg = r.get("report_generation") or {}
    parts.append(_kv_list([
        ("Generated at", rg.get("generated_at", "")),
        ("Cardre version", rg.get("cardre_version", "")),
    ]))
    return "".join(parts)


def _render_artifacts(data: dict[str, Any]) -> str:
    rows = [
        [_esc(a["artifact_id"]), _esc(a["artifact_type"]), _esc(a["role"]),
         _esc(a.get("logical_hash", "")), _esc(a.get("physical_hash", "")), _esc(a.get("path", ""))]
        for a in data["artifacts"]
    ]
    return _table(["Artifact ID", "Type", "Role", "Logical Hash", "Physical Hash", "Path"], rows)


def _render_run_status(data: dict[str, Any]) -> str:
    r = data["run_status"]
    parts = [_kv_list([
        ("Run ID", r["run_id"]), ("Status", r["status"]),
        ("Started at", r.get("started_at") or "—"),
        ("Finished at", r.get("finished_at") or "—"),
        ("Execution mode", r.get("execution_mode", "—")),
    ])]
    if r.get("diagnostics"):
        rows = [
            [_esc(d["code"]), _esc(d["severity"]), _esc(d["message"]), _esc(d.get("created_at", ""))]
            for d in r["diagnostics"]
        ]
        parts.append(_table(["Code", "Severity", "Message", "Created"], rows))
    return "".join(parts)


def _render_modelling_metadata(data: dict[str, Any]) -> str:
    meta = data.get("modelling_metadata") or {}
    if not meta:
        return "<p>No modelling metadata</p>"
    rows = [[_esc(k), _esc(str(v)[:200])] for k, v in sorted(meta.items())]
    return _table(["Step", "Metadata (truncated)"], rows)


def _render_exclusion_summary(data: dict[str, Any]) -> str:
    e = data["exclusion_summary"]
    parts = [_kv_list([
        ("Rows before", str(e.get("rows_before", 0))),
        ("Rows after", str(e.get("rows_after", 0))),
    ])]
    if e.get("rules"):
        rows = [[_esc(r.get("rule_id", "")), _esc(r.get("reason", "")), str(r.get("rows_removed", 0))] for r in e["rules"]]
        parts.append(_table(["Rule ID", "Reason", "Rows removed"], rows))
    return "".join(parts) or "<p>No exclusion summary</p>"


def _render_sample_definition(data: dict[str, Any]) -> str:
    s = data["sample_definition"]
    return _kv_list([
        ("Sample method", s.get("sample_method", "")),
        ("Sample domain", s.get("sample_domain", "")),
        ("Description", s.get("sample_description", "")),
    ])


def _render_variable_selection(data: dict[str, Any]) -> str:
    v = data["variable_selection"]
    parts = [_kv_list([("Min IV", _fmt(v.get("min_iv", 0)))])]
    if v.get("selected_variables"):
        parts.append(f"<p><strong>Selected:</strong> {html.escape(', '.join(v['selected_variables']))}</p>")
    if v.get("rejected_variables"):
        parts.append(f"<p><strong>Rejected:</strong> {html.escape(', '.join(v['rejected_variables']))}</p>")
    return "".join(parts)


def _render_model_diagnostics(data: dict[str, Any]) -> str:
    d = data["model_diagnostics"]
    parts: list[str] = []
    if d.get("coefficient_sign_check"):
        rows = [[_esc(e["variable_name"]), _esc(e["coefficient_sign"]), _esc(e.get("expected_sign", "")), _esc(e["status"])] for e in d["coefficient_sign_check"]]
        parts.append(f"<h3>Coefficient sign check</h3>{_table(['Variable', 'Sign', 'Expected', 'Status'], rows)}")
    if d.get("separation_diagnostics"):
        rows = [[_esc(e["feature_name"]), _fmt(e["coefficient"]), _esc(e["status"]), _esc(e.get("reason", ""))] for e in d["separation_diagnostics"]]
        parts.append(f"<h3>Separation diagnostics</h3>{_table(['Feature', 'Coefficient', 'Status', 'Reason'], rows)}")
    if d.get("vif_diagnostics"):
        rows = [[_esc(e["feature_name"]), _fmt(e.get("vif")), _fmt(e.get("r_squared")), _esc(e["status"])] for e in d["vif_diagnostics"]]
        parts.append(f"<h3>VIF diagnostics</h3>{_table(['Feature', 'VIF', 'R²', 'Status'], rows)}")
    if d.get("calibration_diagnostics"):
        for role, c in d["calibration_diagnostics"].items():
            rows = [[str(b["bin"]), str(b["count"]), str(b["observed_events"]), _fmt(b["expected_events"]),
                     _fmt(b["observed_event_rate"]), _fmt(b["predicted_event_rate"])] for b in c.get("decile_bins", [])]
            parts.append(f"<h3>Calibration — {html.escape(role)}</h3>{_table(['Bin', 'Count', 'Obs events', 'Exp events', 'Obs rate', 'Pred rate'], rows)}")
    return "".join(parts) or "<p>No model diagnostics</p>"


def _render_implementation_artifacts(data: dict[str, Any]) -> str:
    i = data["implementation_artifacts"]
    parts: list[str] = []
    for label, key in [("Scorecard table", "scorecard_table"), ("Scoring export (Python)", "scoring_export_python"), ("Scoring export (SQL)", "scoring_export_sql")]:
        art = i.get(key)
        if art:
            parts.append(_kv_list([(label, art.get("description") or art.get("artifact_id", "")), ("Schema", art.get("schema_version", ""))]))
    return "".join(parts) or "<p>No implementation artifacts</p>"


class HtmlReportRenderer:
    """Render a report bundle as a self-contained offline HTML document.

    Emits every section of the ReportBundle, preserving the full report
    structure from the legacy renderer (artifacts, champion status, cutoffs,
    diagnostics, exclusions, exports, manual interventions, reproducibility,
    sample definition, selection, and other governance content).
    """

    def render(self, bundle: ReportBundle, output_dir: Path) -> Path:
        output_dir.mkdir(parents=True, exist_ok=True)
        path = output_dir / "report.html"
        path.write_text(self.render_to_html(bundle), encoding="utf-8")
        return path

    @staticmethod
    def render_to_html(bundle: ReportBundle) -> str:
        data = bundle.model_dump(mode="json")
        title = _esc(data["summary"].get("model_name") or "Cardre governance report")
        sections = [
            _section("Pathway", _render_pathway(data)),
            _section("Dataset Roles", _render_dataset_roles(data)),
            _section("Branches", _render_branches(data)),
            _section("Champion", _render_champion(data)),
            _section("Variables", _render_variables(data)),
            _section("Model", _render_model(data)),
            _section("Score Scaling", _render_score_scaling(data)),
            _section("Validation", _render_validation(data)),
            _section("Cutoffs", _render_cutoffs(data)),
            _section("Manual Interventions", _render_manual_interventions(data)),
            _section("Manual Binning Review", _render_manual_binning_review(data)),
            _section("Redundancy Review", _render_redundancy_review(data)),
            _section("Model Diagnostics", _render_model_diagnostics(data)),
            _section("Implementation Artifacts", _render_implementation_artifacts(data)),
            _section("Sample Definition", _render_sample_definition(data)),
            _section("Variable Selection", _render_variable_selection(data)),
            _section("Exclusion Summary", _render_exclusion_summary(data)),
            _section("Run Status", _render_run_status(data)),
            _section("Reproducibility", _render_reproducibility(data)),
            _section("Artifacts", _render_artifacts(data)),
            _section("Modelling Metadata", _render_modelling_metadata(data)),
            _section("Limitations", _render_limitations(data)),
        ]
        return (
            "<!doctype html><html><head><meta charset=\"utf-8\">"
            f"<title>{title}</title><style>"
            "body{font-family:system-ui;margin:2rem;max-width:1200px}"
            "table{border-collapse:collapse;margin:1rem 0}th,td{border:1px solid #ddd;padding:.5rem;text-align:left}"
            "th{background:#f5f5f5} .blocker{color:#b00} .warning{color:#b80} h2{border-bottom:1px solid #ccc;padding-bottom:.3rem}"
            "</style></head>"
            f"<body><h1>{title}</h1><p>Run: {_esc(data['run_id'])} | "
            f"Status: {_esc(data['report_status'])} | "
            f"Mode: {_esc(data['report_mode'])}</p>"
            + "".join(sections)
            + "</body></html>"
        )


__all__ = ["HtmlReportRenderer"]
