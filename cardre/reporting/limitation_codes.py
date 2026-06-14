"""Limitation, warning, and blocker code enumerations for the Cardre reporting module.

Centralises all codes used by readiness.py and collector.py into a StrEnum,
eliminating bare-string duplication and enabling exhaustiveness checks.
"""

from __future__ import annotations

from enum import StrEnum


class LimitationCode(StrEnum):
    """All recognised limitation/warning/blocker codes in one enum."""

    # --- Blockers ---
    TARGET_BRANCH_NOT_FOUND = "TARGET_BRANCH_NOT_FOUND"
    TARGET_BRANCH_INCOMPLETE = "TARGET_BRANCH_INCOMPLETE"
    CHAMPION_ASSIGNMENT_MISSING = "CHAMPION_ASSIGNMENT_MISSING"
    CHAMPION_BRANCH_INCOMPLETE = "CHAMPION_BRANCH_INCOMPLETE"
    MISSING_REQUIRED_CANONICAL_STEP = "MISSING_REQUIRED_CANONICAL_STEP"
    MISSING_WOE_IV_EVIDENCE_V1 = "MISSING_WOE_IV_EVIDENCE_V1"
    MISSING_FINAL_SCORECARD = "MISSING_FINAL_SCORECARD"
    MISSING_MODEL_COEFFICIENTS = "MISSING_MODEL_COEFFICIENTS"
    MISSING_SCORE_SCALING = "MISSING_SCORE_SCALING"
    MISSING_TRAIN_VALIDATION_METRICS = "MISSING_TRAIN_VALIDATION_METRICS"
    MISSING_RUN_MANIFEST = "MISSING_RUN_MANIFEST"
    MISSING_PATHWAY = "MISSING_PATHWAY"
    ARTIFACT_HASH_UNRESOLVED = "ARTIFACT_HASH_UNRESOLVED"

    # --- Warnings ---
    NO_OOT_SAMPLE = "NO_OOT_SAMPLE"
    NO_TEST_SAMPLE = "NO_TEST_SAMPLE"
    NO_CHAMPION_ASSIGNMENT = "NO_CHAMPION_ASSIGNMENT"
    MISSING_CHAMPION_RATIONALE = "MISSING_CHAMPION_RATIONALE"
    NO_CHALLENGER_COMPARISON = "NO_CHALLENGER_COMPARISON"
    TARGET_BRANCH_NOT_CHAMPION = "TARGET_BRANCH_NOT_CHAMPION"
    INHERITED_BRANCH_EVIDENCE = "INHERITED_BRANCH_EVIDENCE"
    NO_CUTOFF_ANALYSIS = "NO_CUTOFF_ANALYSIS"
    MISSING_MANUAL_INTERVENTION_REASON = "MISSING_MANUAL_INTERVENTION_REASON"
    SMOOTHING_APPLIED = "SMOOTHING_APPLIED"
    ZERO_CELL_POLICY_USED = "ZERO_CELL_POLICY_USED"
    LEGACY_WOE_SUMMARY_USED = "LEGACY_WOE_SUMMARY_USED"
    PDF_OUT_OF_SCOPE = "PDF_OUT_OF_SCOPE"

    # --- Collector block codes (not in readiness BLOCKER_CODES) ---
    MISSING_RUN_MANIFEST_COLLECTOR = "MISSING_RUN_MANIFEST"

    @classmethod
    def blocker_codes(cls) -> set[LimitationCode]:
        """Return the set of codes that represent blockers."""
        return {
            cls.TARGET_BRANCH_NOT_FOUND,
            cls.TARGET_BRANCH_INCOMPLETE,
            cls.CHAMPION_ASSIGNMENT_MISSING,
            cls.CHAMPION_BRANCH_INCOMPLETE,
            cls.MISSING_REQUIRED_CANONICAL_STEP,
            cls.MISSING_WOE_IV_EVIDENCE_V1,
            cls.MISSING_FINAL_SCORECARD,
            cls.MISSING_MODEL_COEFFICIENTS,
            cls.MISSING_SCORE_SCALING,
            cls.MISSING_TRAIN_VALIDATION_METRICS,
            cls.MISSING_RUN_MANIFEST,
            cls.MISSING_PATHWAY,
            cls.ARTIFACT_HASH_UNRESOLVED,
        }

    @classmethod
    def warning_codes(cls) -> set[LimitationCode]:
        """Return the set of codes that represent warnings."""
        return {
            cls.NO_OOT_SAMPLE,
            cls.NO_TEST_SAMPLE,
            cls.NO_CHAMPION_ASSIGNMENT,
            cls.MISSING_CHAMPION_RATIONALE,
            cls.NO_CHALLENGER_COMPARISON,
            cls.TARGET_BRANCH_NOT_CHAMPION,
            cls.INHERITED_BRANCH_EVIDENCE,
            cls.NO_CUTOFF_ANALYSIS,
            cls.MISSING_MANUAL_INTERVENTION_REASON,
            cls.SMOOTHING_APPLIED,
            cls.ZERO_CELL_POLICY_USED,
            cls.LEGACY_WOE_SUMMARY_USED,
            cls.PDF_OUT_OF_SCOPE,
        }
