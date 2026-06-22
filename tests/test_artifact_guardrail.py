"""Guardrail: ban direct artifact file reads outside the evidence module."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

APPROVED_PATTERNS: set[str] = {
    "cardre/artifacts.py",
    "cardre/evidence.py",
    "cardre/_evidence/",
    "cardre/modeling/serialization.py",
}

ALLOWED_TEST_FILES: set[str] = {
    "tests/test_artifact_serialization.py",
    "tests/test_evidence_reader.py",
    "tests/test_legacy_artifact_compatibility.py",
}


def _load_audit_module():
    script_path = REPO_ROOT / "scripts" / "audit_artifact_reads.py"
    spec = importlib.util.spec_from_file_location("audit_artifact_reads", script_path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_no_direct_artifact_reads_in_production():
    module = _load_audit_module()
    matches = module.scan_repo(
        REPO_ROOT,
        include_production=True,
        include_tests=False,
        approved_modules=tuple(APPROVED_PATTERNS),
    )
    violations = [match for match in matches if match.classification == "production_violation"]

    assert violations == [], (
        "Production code must read artifacts via ArtifactEvidenceReader, not raw file reads.\n"
        + "\n".join(f"  {m.file}:{m.line_number}: {m.pattern_type}" for m in violations)
    )


def test_audit_script_classifies_test_reads():
    module = _load_audit_module()
    matches = module.scan_repo(
        REPO_ROOT,
        include_production=False,
        include_tests=True,
        approved_modules=tuple(APPROVED_PATTERNS),
    )
    assert matches
    assert any(match.classification == "test_violation" for match in matches)
