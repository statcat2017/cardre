"""Canonical pathway commit-readiness validation.

Generic node schema validation checks that parameters are syntactically
valid. A canonical scorecard pathway additionally requires explicit modelling
decisions before it may become immutable:

- essential business metadata (product, segment, observation/performance
  windows, reject-inference position) must be supplied;
- the manual-binning step must record exactly one outcome — reviewed manual
  overrides *or* explicit automated-bin acceptance (never neither);
- the target column must agree across every target-dependent step
  (define-metadata, validate-target, split).

These rules are canonical-pathway specific: they only apply when the version
contains the canonical ``define-metadata`` step. Custom plans are governed by
generic node validation alone.
"""

from __future__ import annotations

from typing import Any

from cardre.domain.plans.scorecard_pathway import TARGET_DEPENDENT_STEP_IDS

# Business metadata a real project must supply before an auditable scorecard
# can be committed. The production template deliberately leaves these empty.
_ESSENTIAL_METADATA_KEYS = (
    "product",
    "segment",
    "observation_window",
    "performance_window",
    "reject_inference_position",
)


def validate_canonical_readiness(
    steps: list[Any],
) -> list[dict[str, Any]]:
    """Return structured readiness errors for a canonical pathway.

    Returns a list of ``{"step_id", "canonical_step_id", "errors": [...]}``
    entries (empty when the version is ready, or when it is not a canonical
    pathway — i.e. it has no ``define-metadata`` step).
    """
    by_canonical = {s.canonical_step_id: s for s in steps if s.canonical_step_id}
    if "define-metadata" not in by_canonical:
        return []

    errors_by_step: list[dict[str, Any]] = []

    meta = by_canonical["define-metadata"]
    meta_errors: list[str] = []
    for key in _ESSENTIAL_METADATA_KEYS:
        if not meta.params.get(key):
            meta_errors.append(f"{key} is required before commit")
    if not meta.params.get("target_column"):
        meta_errors.append("target_column is required before commit")
    if not meta.params.get("good_values"):
        meta_errors.append("good_values are required before commit")
    if not meta.params.get("bad_values"):
        meta_errors.append("bad_values are required before commit")
    if meta_errors:
        errors_by_step.append({
            "step_id": meta.step_id,
            "canonical_step_id": "define-metadata",
            "errors": meta_errors,
        })

    manual = by_canonical.get("manual-binning")
    if manual is not None:
        reviewed = bool(manual.params.get("reviewed"))
        accept_automated = bool(manual.params.get("accept_automated"))
        if reviewed and accept_automated:
            errors_by_step.append({
                "step_id": manual.step_id,
                "canonical_step_id": "manual-binning",
                "errors": ["reviewed and accept_automated cannot both be true"],
            })
        elif not reviewed and not accept_automated:
            errors_by_step.append({
                "step_id": manual.step_id,
                "canonical_step_id": "manual-binning",
                "errors": [
                    "manual-binning requires an explicit outcome: "
                    "set reviewed=true for manual overrides or "
                    "accept_automated=true to accept automated bins"
                ],
            })

    # Target consistency: every target-dependent step must carry the same
    # target column, otherwise the pathway indexes a different column than
    # the one it validates/splits on.
    targets = {
        cid: by_canonical[cid].params.get("target_column")
        for cid in TARGET_DEPENDENT_STEP_IDS
        if cid in by_canonical
    }
    nonempty = {v for v in targets.values() if v}
    if len(nonempty) > 1 or (len(targets) >= 2 and "" in targets.values() and nonempty):
        errors_by_step.append({
            "step_id": meta.step_id,
            "canonical_step_id": "target",
            "errors": [
                "target_column must agree across define-metadata, validate-target "
                f"and split; got {targets}"
            ],
        })

    return errors_by_step


__all__ = ["validate_canonical_readiness"]
