from __future__ import annotations

from pathlib import Path

import pytest

from cardre.application.reporting.generate_report import GenerateReport, GenerateReportCommand
from cardre.application.reporting.schema import ReportBundle
from cardre.domain.errors import CardreError


class _Context:
    class _Uow:
        artifacts = object()
        run_steps = object()

    def __enter__(self):
        return self._Uow()

    def __exit__(self, *args):
        return None


class _Factory:
    def read_only(self, project_id):
        return _Context()


class _Collector:
    def collect(self, uow, project_id, run_id, target_branch_id, report_mode):
        return ReportBundle(project_id=project_id, run_id=run_id, target_branch_id=target_branch_id, report_mode=report_mode)


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

    result = use_case(GenerateReportCommand("project", "run", "branch", output_dir=tmp_path))

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
        use_case(GenerateReportCommand("project", "run", "branch", output_dir=tmp_path))

    assert exc_info.value.code == "REPORT_BLOCKED"
    assert renderer.bundle is None
