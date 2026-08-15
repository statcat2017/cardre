"""Tests for the live EvidenceAdapter registry.

Verifies:
- Every EvidenceKind with a profile has a registered adapter.
- Each adapter carries its kind and profile.
- get_adapter raises on unknown kinds.
"""

from __future__ import annotations

import pytest

from cardre._evidence.profiles import EVIDENCE_PROFILES
from cardre.adapters.evidence.parsers import EVIDENCE_ADAPTERS, AdapterSpec, get_adapter
from cardre.domain.evidence.kinds import EvidenceKind, EvidenceParseError


def test_adapter_registry_covers_all_profiles() -> None:
    assert set(EVIDENCE_PROFILES).issubset(set(EVIDENCE_ADAPTERS))


def test_adapter_registry_covers_all_evidence_kinds() -> None:
    for kind in EvidenceKind:
        assert kind in EVIDENCE_ADAPTERS, f"{kind.name} missing from registry"


def test_get_adapter_returns_correct_profile() -> None:
    for kind in EVIDENCE_PROFILES:
        spec = get_adapter(kind)
        assert isinstance(spec, AdapterSpec)
        assert spec.profile is EVIDENCE_PROFILES[kind]


def test_get_adapter_unknown_kind_raises() -> None:
    class _FakeKind:
        value = "fake"

    with pytest.raises(EvidenceParseError):
        get_adapter(_FakeKind())  # type: ignore[arg-type]
