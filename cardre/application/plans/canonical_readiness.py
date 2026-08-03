"""Canonical pathway commit-readiness validation.

Generic node schema validation checks that parameters are syntactically
valid. A canonical scorecard pathway additionally requires explicit modelling
decisions before it may become immutable:

- essential business metadata (product, segment, observation/performance
  windows, reject-inference position) must be supplied;
- the target definition must be self-consistent: a non-blank target column,
  non-blank disjoint good/bad/indeterminate value sets;
- the manual-binning step must record exactly one outcome — reviewed manual
  overrides *or* explicit automated-bin acceptance (never neither, and never
  ``accept_automated=True`` combined with overrides);
- the target column must agree across every target-dependent step
  (define-metadata, validate-target, split).

These rules are canonical-pathway specific: they only apply when the version
contains the canonical ``define-metadata`` step. Custom plans are governed by
generic node validation alone.

Validation runs against *normalized* parameter sets (schema defaults applied,
types coerced) so an absent or null target key cannot slip past the check.
"""

from __future__ import annotations

from typing import Any

from cardre.domain.plans.scorecard_pathway import TARGET_DEPENDENT_STEP_IDS
from cardre.domain.plans.target_definition import validate_target_definition

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
    *,
    normalized_params: dict[str, dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Return structured readiness errors for a canonical pathway.

    ``normalized_params`` maps ``step_id`` → schema-normalized params (the
    values ``CommitPlanVersion`` validated). When provided, readiness
    validates those rather than the raw persisted params, so an absent/null
    target key — which schema normalization would default — is caught.

    Returns a list of ``{"step_id", "canonical_step_id", "errors": [...]}``
    entries (empty when the version is ready, or when it is not a canonical
    pathway — i.e. it has no ``define-metadata`` step).
    """
    by_canonical = {s.canonical_step_id: s for s in steps if s.canonical_step_id}
    if "define-metadata" not in by_canonical:
        return []

    def params_for(step: Any) -> dict[str, Any]:
        if normalized_params is not None:
            normalized = normalized_params.get(step.step_id)
            if normalized is not None:
                return normalized
        return dict(step.params)

    errors_by_step: list[dict[str, Any]] = []

    meta = by_canonical["define-metadata"]
    meta_params = params_for(meta)
    meta_errors: list[str] = []
    for key in _ESSENTIAL_METADATA_KEYS:
        value = meta_params.get(key)
        if not isinstance(value, str) or not value.strip():
            meta_errors.append(f"{key} must be non-whitespace text")
    meta_errors.extend(validate_target_definition(meta_params))
    if meta_errors:
        errors_by_step.append({
            "step_id": meta.step_id,
            "canonical_step_id": "define-metadata",
            "errors": meta_errors,
        })

    manual = by_canonical.get("manual-binning")
    if manual is not None:
        manual_params = params_for(manual)
        reviewed = bool(manual_params.get("reviewed"))
        accept_automated = bool(manual_params.get("accept_automated"))
        overrides = manual_params.get("overrides") or []
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
        elif accept_automated and overrides:
            errors_by_step.append({
                "step_id": manual.step_id,
                "canonical_step_id": "manual-binning",
                "errors": [
                    "accept_automated cannot be true when overrides are present: "
                    "accepting automated bins discards manual overrides"
                ],
            })

    # Target consistency: every target-dependent canonical step must exist and
    # carry the same, non-empty, non-whitespace target column — matched exactly
    # as persisted (execution does not strip or coerce).
    target_errors: list[str] = []
    raw_targets: dict[str, str] = {}
    for cid in TARGET_DEPENDENT_STEP_IDS:
        step = by_canonical.get(cid)
        if step is None:
            target_errors.append(f"canonical target step {cid!r} is missing")
            continue
        value = params_for(step).get("target_column")
        if not isinstance(value, str) or not value.strip():
            target_errors.append(f"{cid}.target_column must be non-whitespace text")
            continue
        raw_targets[cid] = value

    if len(set(raw_targets.values())) > 1:
        target_errors.append(
            "target_column must match exactly across define-metadata, validate-target "
            f"and split; got {raw_targets}"
        )
    if target_errors:
        errors_by_step.append({
            "step_id": meta.step_id,
            "canonical_step_id": "target",
            "errors": target_errors,
        })

    return errors_by_step


__all__ = ["validate_canonical_readiness"]
