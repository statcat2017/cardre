from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from cardre._evidence.kinds import EvidenceKind, EvidenceParseError
from cardre.adapters.evidence.comparison_reader import ComparisonEvidenceReader
from cardre.domain.artifacts import ArtifactRef


class _Context:
    def __init__(self, value):
        self._value = value

    def __enter__(self):
        return self._value

    def __exit__(self, *args):
        return None


class _Factory:
    def __init__(self, uow):
        self._uow = uow

    def read_only(self, project_id):
        return _Context(self._uow)


class _Reader:
    def __init__(self, path: Path):
        self._path = path

    def resolve_path(self, artifact):
        return self._path


def _reader(tmp_path):
    path = tmp_path / "evidence.json"
    path.write_text("{}", encoding="utf-8")
    artifact = ArtifactRef("artifact", "report", "report", str(path), "physical", "logical")
    uow = SimpleNamespace(
        run_steps=SimpleNamespace(get_latest_successful_step=lambda *args: SimpleNamespace(run_step_id="step-run")),
        artifacts=SimpleNamespace(
            output_artifact_ids_for_run_step=lambda run_step_id: [artifact.artifact_id],
            get=lambda artifact_id: artifact,
        ),
    )
    return ComparisonEvidenceReader(_Factory(uow), _Reader(path), "project"), artifact


def test_comparison_reader_uses_canonical_parser_and_returns_raw_payload(tmp_path, monkeypatch):
    reader, artifact = _reader(tmp_path)
    parsed = SimpleNamespace(_raw={"validated": True})
    parser_calls = []
    spec = SimpleNamespace(
        profile=object(),
        parse=lambda path, art, artifact_reader: parser_calls.append((path, art)) or parsed,
    )
    monkeypatch.setattr("cardre.adapters.evidence.comparison_reader.get_adapter", lambda kind: spec)
    monkeypatch.setattr("cardre.adapters.evidence.comparison_reader.match", lambda *args: [artifact])

    result = reader.find_typed(
        [{"canonical_step_id": "model-fit", "step_id": "model-fit"}],
        "model-fit", "pv", None, (EvidenceKind.MODEL_ARTIFACT,),
    )

    assert result == {"validated": True}
    assert parser_calls == [(tmp_path / "evidence.json", artifact)]


def test_comparison_reader_rejects_canonical_parser_failure(tmp_path, monkeypatch):
    reader, artifact = _reader(tmp_path)
    spec = SimpleNamespace(
        profile=object(),
        parse=lambda path, art, artifact_reader: (_ for _ in ()).throw(ValueError("invalid evidence")),
    )
    monkeypatch.setattr("cardre.adapters.evidence.comparison_reader.get_adapter", lambda kind: spec)
    monkeypatch.setattr("cardre.adapters.evidence.comparison_reader.match", lambda *args: [artifact])

    with pytest.raises(EvidenceParseError, match="could not be parsed"):
        reader.find_typed(
            [{"canonical_step_id": "model-fit", "step_id": "model-fit"}],
            "model-fit", "pv", None, (EvidenceKind.MODEL_ARTIFACT,),
        )
