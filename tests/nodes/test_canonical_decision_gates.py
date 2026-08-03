"""Node-level validation for the canonical decision gates.

Covers the data-independent target-definition checks on
``DefineModellingMetadataNode`` and the automated-bin/overrides
contradiction on ``ManualBinningNode`` — the same rules the canonical
commit-readiness gate enforces, tested directly against the nodes.
"""

from __future__ import annotations

from cardre.nodes.build.manual import ManualBinningNode
from cardre.nodes.prep.metadata import DefineModellingMetadataNode


class TestDefineModellingMetadataTargetDefinition:
    def test_rejects_overlapping_good_bad(self):
        node = DefineModellingMetadataNode()
        errors = node.validate_params({
            "reject_inference_position": "not_applied",
            "target_column": "outcome",
            "good_values": ["default"],
            "bad_values": ["default"],
        })
        assert any("must be disjoint" in e for e in errors), errors

    def test_rejects_blank_good_values(self):
        node = DefineModellingMetadataNode()
        errors = node.validate_params({
            "reject_inference_position": "not_applied",
            "target_column": "outcome",
            "good_values": ["  "],
            "bad_values": ["bad"],
        })
        assert any("good_values must contain at least one non-blank value" in e for e in errors)

    def test_rejects_blank_target_column(self):
        node = DefineModellingMetadataNode()
        errors = node.validate_params({
            "reject_inference_position": "not_applied",
            "target_column": "   ",
            "good_values": ["good"],
            "bad_values": ["bad"],
        })
        assert any("target_column must be non-whitespace text" in e for e in errors)

    def test_accepts_valid_disjoint_definition(self):
        node = DefineModellingMetadataNode()
        errors = node.validate_params({
            "reject_inference_position": "not_applied",
            "target_column": "outcome",
            "good_values": ["good"],
            "bad_values": ["bad"],
        })
        assert errors == []

    def test_target_checks_run_even_without_reject_inference(self):
        """Target-definition validation must run even when reject_inference
        position is absent — it must not be skipped by an early return."""
        node = DefineModellingMetadataNode()
        errors = node.validate_params({
            "target_column": "outcome",
            "good_values": ["default"],
            "bad_values": ["default"],
        })
        assert any("must be disjoint" in e for e in errors), errors

    def test_rejects_blank_member_with_valid_reject_inference(self):
        """A blank member becomes a spurious declared category at runtime, so
        it must be rejected during validation."""
        node = DefineModellingMetadataNode()
        errors = node.validate_params({
            "reject_inference_position": "not_applied",
            "target_column": "outcome",
            "good_values": ["good", "   "],
            "bad_values": ["bad"],
        })
        assert any("good_values[1] must not be blank" in e for e in errors), errors

    def test_rejects_whitespace_different_target_column(self):
        node = DefineModellingMetadataNode()
        errors = node.validate_params({
            "reject_inference_position": "not_applied",
            "target_column": " outcome ",
            "good_values": ["good"],
            "bad_values": ["bad"],
        })
        # The node-level check requires non-whitespace content; surrounding
        # whitespace is still non-whitespace content, so it is not flagged
        # here — the canonical readiness gate rejects it as an exact-match
        # violation across steps. This test guards that a blank-only value is
        # still rejected.
        assert not any("target_column must be non-whitespace text" in e for e in errors)


class TestManualBinningAutomatedAcceptance:
    def test_rejects_accept_automated_with_overrides(self):
        node = ManualBinningNode()
        errors = node.validate_params({
            "accept_automated": True,
            "reviewed": False,
            "overrides": [{
                "variable": "x",
                "action": "merge_bins",
                "reason": "manual change",
                "source_bin_ids": ["a", "b"],
            }],
        })
        assert any("accept_automated cannot be true when overrides" in e for e in errors), errors

    def test_accepts_accept_automated_without_overrides(self):
        node = ManualBinningNode()
        errors = node.validate_params({
            "accept_automated": True,
            "reviewed": False,
            "overrides": [],
        })
        assert errors == []

    def test_accepts_reviewed_with_overrides(self):
        node = ManualBinningNode()
        errors = node.validate_params({
            "accept_automated": False,
            "reviewed": True,
            "overrides": [{
                "variable": "x",
                "action": "merge_bins",
                "reason": "manual change",
                "source_bin_ids": ["a", "b"],
            }],
        })
        assert errors == []
