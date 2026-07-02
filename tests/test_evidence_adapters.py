"""Tests for the EvidenceAdapter registry and independence.

Verifies that:
- Every EvidenceKind with a profile has a registered adapter.
- Each adapter carries its kind and profile.
- No adapter module imports ArtifactEvidenceReader (dependency direction).
"""

from __future__ import annotations

import ast
from pathlib import Path

from cardre._evidence.adapters import EVIDENCE_ADAPTERS, EvidenceAdapter, get_adapter
from cardre._evidence.kinds import EvidenceKind
from cardre._evidence.profiles import EVIDENCE_PROFILES


def test_adapter_registry_covers_all_profiles() -> None:
    assert set(EVIDENCE_PROFILES).issubset(set(EVIDENCE_ADAPTERS))


def test_adapter_registry_covers_all_evidence_kinds() -> None:
    for kind in EvidenceKind:
        assert kind in EVIDENCE_ADAPTERS, f"{kind.name} missing from registry"


def test_get_adapter_returns_correct_kind_and_profile() -> None:
    for kind in EVIDENCE_PROFILES:
        adapter = get_adapter(kind)
        assert isinstance(adapter, EvidenceAdapter)
        assert adapter.kind == kind
        assert adapter.profile is EVIDENCE_PROFILES[kind]


def test_get_adapter_unknown_kind_raises() -> None:
    from cardre._evidence.kinds import EvidenceParseError

    class _FakeKind:
        value = "fake"

    try:
        get_adapter(_FakeKind())  # type: ignore[arg-type]
    except EvidenceParseError:
        pass
    else:
        raise AssertionError("expected EvidenceParseError for unknown kind")


def test_adapters_do_not_import_artifact_evidence_reader() -> None:
    """Adapters must not depend on ArtifactEvidenceReader — that would invert
    the dependency direction (reader should depend on adapters, not the reverse)."""
    adapters_dir = Path(__file__).resolve().parent.parent / "cardre" / "_evidence" / "adapters"
    banned = "ArtifactEvidenceReader"
    for py in sorted(adapters_dir.glob("*.py")):
        tree = ast.parse(py.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                for alias in node.names:
                    assert banned not in alias.name, f"{py.name} imports {banned}"
                    if alias.asname:
                        assert banned not in alias.asname, f"{py.name} imports {banned} as {alias.asname}"
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    assert banned not in alias.name, f"{py.name} imports {banned}"
