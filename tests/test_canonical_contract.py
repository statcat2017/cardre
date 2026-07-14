"""Canonical contract tests — enforce the canonical architecture.

These tests guard against regression to legacy node identities, aliases,
and compatibility mechanisms that have been removed.
"""

from __future__ import annotations

from cardre.nodes.registry import NodeRegistry
from cardre.workflows.scorecard import build_canonical_scorecard_steps


def test_only_one_automatic_binning_node_registered():
    reg = NodeRegistry.with_defaults()
    assert reg.has("cardre.automatic_binning")
    assert not reg.has("cardre.fine_classing")
    assert not reg.has("cardre.auto_binning_fit")
    assert not reg.has("cardre.binning")


def test_manual_binning_distinct_node():
    reg = NodeRegistry.with_defaults()
    manual = reg.resolve("cardre.manual_binning")
    assert manual.category == "refinement"
    assert manual.node_type == "cardre.manual_binning"


def test_canonical_automatic_binning_has_explicit_method():
    steps = build_canonical_scorecard_steps("dummy.csv")
    auto_step = next(s for s in steps if s.step_id == "automatic-binning")
    assert "method" in auto_step.params, (
        "automatic-binning step must have an explicit method param"
    )
    assert auto_step.params["method"] == "fine_classing"
    assert auto_step.params_hash, "params_hash must be non-empty"
    from cardre.domain.artifacts import json_logical_hash
    expected_hash = json_logical_hash(auto_step.params)
    assert auto_step.params_hash == expected_hash, (
        "params_hash must be based on the explicit params"
    )


def test_no_compat_evidence_aliases_in_source():
    import subprocess
    banned = [
        "WOE_APPLICATION_EVIDENCE", "SCORE_APPLICATION_EVIDENCE",
        "SCHEMA_WOE_APPLICATION_EVIDENCE", "SCHEMA_SCORE_APPLICATION_EVIDENCE",
        "LegacyEvidenceCompatibilityError", "SCHEMA_RUN_MANIFEST",
        "EvidenceKind.RUN_MANIFEST", "RunManifestEvidence",
    ]
    result = subprocess.run(
        ["rg", "-n", "|".join(banned), "cardre/"],
        capture_output=True, text=True,
    )
    assert result.returncode != 0, f"Banned compat identifiers still in source:\n{result.stdout}"
