"""Tests for the manual-binning review gate — blocker computation."""

from cardre.readiness.manual_binning import compute_manual_binning_blockers


def test_blocker_when_evidence_unreadable():
    blockers = compute_manual_binning_blockers(
        selected_variables=["x", "y"],
        variable_summaries=[],
        current_overrides=[],
        branch_id=None,
        step_id="manual-binning",
    )
    codes = [b["code"] for b in blockers]
    assert "VARIABLE_SUMMARY_UNREADABLE" in codes, f"Expected VARIABLE_SUMMARY_UNREADABLE, got {codes}"
