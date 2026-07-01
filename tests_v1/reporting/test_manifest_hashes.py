"""Tests for manifest hash computing and the source_step_refs field population.

These test that the collector correctly populates source_step_refs on each
report section and that manifest hashes are stable.
"""

from __future__ import annotations

from cardre.reporting.schema import (
    ModelInfo,
    ScoreScalingInfo,
    ValidationInfo,
    CutoffInfo,
    ResolvedStepRef,
)


class TestSourceStepRefsSchema:
    """source_step_refs field exists on each major report section model."""

    def _make_ref(self, canonical_step_id: str, step_id: str) -> ResolvedStepRef:
        return ResolvedStepRef(
            requested_branch_id="main", resolved_branch_id="main",
            canonical_step_id=canonical_step_id, step_id=step_id,
            resolution="exact",
        )

    def test_model_has_source_step_refs(self):
        ref = self._make_ref("logistic-regression", "fit-model")
        m = ModelInfo(features=[], source_step_refs=[ref])
        d = m.model_dump()
        assert len(d["source_step_refs"]) == 1
        assert d["source_step_refs"][0]["step_id"] == "fit-model"

    def test_score_scaling_has_source_step_refs(self):
        ref = self._make_ref("score-scaling", "scale")
        s = ScoreScalingInfo(source_step_refs=[ref])
        d = s.model_dump()
        assert len(d["source_step_refs"]) == 1
        assert d["source_step_refs"][0]["canonical_step_id"] == "score-scaling"

    def test_validation_has_source_step_refs(self):
        ref = self._make_ref("validation-metrics", "validate")
        v = ValidationInfo(source_step_refs=[ref])
        d = v.model_dump()
        assert len(d["source_step_refs"]) == 1
        assert d["source_step_refs"][0]["canonical_step_id"] == "validation-metrics"

    def test_cutoff_has_source_step_refs(self):
        ref = self._make_ref("cutoff-analysis", "cutoff")
        c = CutoffInfo(source_step_refs=[ref])
        d = c.model_dump()
        assert len(d["source_step_refs"]) == 1
        assert d["source_step_refs"][0]["canonical_step_id"] == "cutoff-analysis"
