from __future__ import annotations

from pathlib import Path

import pytest

from cardre.application.reporting.generate_report import GenerateReport, GenerateReportCommand
from cardre.application.reporting.schema import ReportBundle
from cardre.domain.errors import CardreError


class _Context:
    class _ReportRepository:
        def __init__(self, registered_reports):
            self.registered_reports = registered_reports

        def register(self, **report):
            self.registered_reports.append(report)

    class _Uow:
        artifacts = object()
        run_steps = object()

        def __init__(self, registered_reports):
            self.reports = _Context._ReportRepository(registered_reports)

        def commit(self):
            pass

    def __init__(self, registered_reports):
        self.registered_reports = registered_reports

    def __enter__(self):
        return self._Uow(self.registered_reports)

    def __exit__(self, *args):
        return None


class _Factory:
    def __init__(self):
        self.registered_reports = []

    def read_only(self, project_id):
        return _Context(self.registered_reports)

    def for_project(self, project_id):
        return _Context(self.registered_reports)


class _Collector:
    def collect(self, uow, project_id, run_id):
        return ReportBundle(project_id=project_id, run_id=run_id)


class _Renderer:
    def __init__(self):
        self.bundle = None

    def render(self, bundle, output_dir):
        self.bundle = bundle
        output_dir.mkdir(parents=True, exist_ok=True)
        path = output_dir / "report.html"
        path.write_text("report")
        return path


def test_generate_report_collects_and_renders_through_ports(tmp_path: Path, monkeypatch):
    renderer = _Renderer()
    use_case = GenerateReport(
        _Factory(),
        lambda project_id: object(),
        lambda reader, artifacts, run_steps: object(),
        lambda evidence_reader, artifact_reader: _Collector(),
        renderer,
    )
    monkeypatch.setattr("cardre.application.reporting.generate_report.check_report_readiness", lambda *args: type("Ready", (), {"ready": True, "blockers": [], "warnings": []})())

    result = use_case(GenerateReportCommand("project", "run", output_dir=tmp_path))

    assert result.html_path == str(tmp_path / "report.html")
    assert renderer.bundle is result.bundle


def test_generate_report_rejects_readiness_blockers(tmp_path: Path, monkeypatch):
    renderer = _Renderer()
    use_case = GenerateReport(
        _Factory(),
        lambda project_id: object(),
        lambda reader, artifacts, run_steps: object(),
        lambda evidence_reader, artifact_reader: _Collector(),
        renderer,
    )
    monkeypatch.setattr(
        "cardre.application.reporting.generate_report.check_report_readiness",
        lambda *args: type("Blocked", (), {"ready": False, "blockers": [type("Finding", (), {"code": "MISSING", "message": "Missing evidence"})()], "warnings": []})(),
    )

    with pytest.raises(CardreError) as exc_info:
        use_case(GenerateReportCommand("project", "run", output_dir=tmp_path))

    assert exc_info.value.code == "REPORT_BLOCKED"
    assert renderer.bundle is None


def test_regenerated_reports_keep_independent_paths_and_contents(tmp_path: Path, monkeypatch):
    factory = _Factory()
    artifact_reader = type("ArtifactReader", (), {"root": tmp_path})()
    report_contents = iter(("first report", "second report"))

    class _ChangingCollector:
        def collect(self, uow, project_id, run_id):
            bundle = ReportBundle(project_id=project_id, run_id=run_id)
            bundle.summary.model_name = next(report_contents)
            return bundle

    class _ContentRenderer:
        def render(self, bundle, output_dir):
            output_dir.mkdir(parents=True, exist_ok=True)
            path = output_dir / "report.html"
            path.write_text(bundle.summary.model_name, encoding="utf-8")
            return path

    use_case = GenerateReport(
        factory,
        lambda project_id: artifact_reader,
        lambda reader, artifacts, run_steps: object(),
        lambda evidence_reader, reader: _ChangingCollector(),
        _ContentRenderer(),
    )
    monkeypatch.setattr(
        "cardre.application.reporting.generate_report.check_report_readiness",
        lambda *args: type("Ready", (), {"ready": True, "blockers": [], "warnings": []})(),
    )

    first = use_case(GenerateReportCommand("project", "run"))
    second = use_case(GenerateReportCommand("project", "run"))

    assert first.report_id != second.report_id
    assert first.html_path != second.html_path
    assert Path(first.html_path).read_text(encoding="utf-8") == "first report"
    assert Path(second.html_path).read_text(encoding="utf-8") == "second report"
    assert [report["path"] for report in factory.registered_reports] == [
        f"reports/run/{first.report_id}/report.html",
        f"reports/run/{second.report_id}/report.html",
    ]
