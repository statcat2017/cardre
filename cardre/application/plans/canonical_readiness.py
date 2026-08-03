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

# Business metadata a real project must supply before an auditable scorecard
# can be committed. The production template deliberately leaves these empty.
_ESSENTIAL_METADATA_KEYS = (
    "product",
    "segment",
    "observation_window",
    "performance_window",
    "reject_inference_position",
)


def _normalize_target_values(values: Any) -> list[str]:
    """Strip, drop blanks, and dedupe a target value list."""
    if not isinstance(values, list):
        return []
    seen: list[str] = []
    for value in values:
        text = str(value).strip()
        if text and text not in seen:
            seen.append(text)
    return seen


def _target_definition_errors(params: dict[str, Any]) -> list[str]:
    errors: list[str] = []

    target_column = params.get("target_column")
    if not isinstance(target_column, str) or not target_column.strip():
        errors.append("target_column must be non-whitespace text")

    good_values = _normalize_target_values(params.get("good_values"))
    bad_values = _normalize_target_values(params.get("bad_values"))
    indeterminate_values = _normalize_target_values(params.get("indeterminate_values"))

    if not good_values:
        errors.append("good_values must contain at least one non-blank value")
    if not bad_values:
        errors.append("bad_values must contain at least one non-blank value")

    good_set = set(good_values)
    bad_set = set(bad_values)
    indeterminate_set = set(indeterminate_values)

    overlap_gb = good_set & bad_set
    if overlap_gb:
        errors.append(f"good_values and bad_values must be disjoint; overlap: {sorted(overlap_gb)}")
    overlap_gi = good_set & indeterminate_set
    if overlap_gi:
        errors.append(
            f"good_values and indeterminate_values must be disjoint; overlap: {sorted(overlap_gi)}"
        )
    overlap_bi = bad_set & indeterminate_set
    if overlap_bi:
        errors.append(
            f"bad_values and indeterminate_values must be disjoint; overlap: {sorted(overlap_bi)}"
        )

    return errors


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
        if not meta_params.get(key):
            meta_errors.append(f"{key} is required before commit")
    meta_errors.extend(_target_definition_errors(meta_params))
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
    # carry the same stripped, non-empty target column.
    missing_target_steps = [cid for cid in TARGET_DEPENDENT_STEP_IDS if cid not in by_canonical]
    if missing_target_steps:
        errors_by_step.append({
            "step_id": meta.step_id,
            "canonical_step_id": "target",
            "errors": [
                f"canonical target steps are missing: {', '.join(missing_target_steps)}"
            ],
        })

    targets = {
        cid: params_for(by_canonical[cid]).get("target_column")
        for cid in TARGET_DEPENDENT_STEP_IDS
        if cid in by_canonical
    }
    stripped = {cid: str(value).strip() for cid, value in targets.items()}
    nonempty = {value for value in stripped.values() if value}
    if len(nonempty) > 1:
        errors_by_step.append({
            "step_id": meta.step_id,
            "canonical_step_id": "target",
            "errors": [
                "target_column must agree across define-metadata, validate-target "
                f"and split; got {stripped}"
            ],
        })

    return errors_by_step


__all__ = ["validate_canonical_readiness"]
