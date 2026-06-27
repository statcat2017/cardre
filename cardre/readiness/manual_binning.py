"""Manual-binning readiness — blocker computation for the review gate.

The ``compute_manual_binning_blockers`` function is the single source
of truth for review-completion blockers, shared by the editor state
(Phase 1), the review-completion gate (Phase 3), and evidence/report
integration (Phase 4).
"""

from __future__ import annotations


from cardre.services.plan_dto import ManualBinningVariableSummary


def compute_manual_binning_blockers(
    selected_variables: list[str],
    variable_summaries: list[ManualBinningVariableSummary],
    current_overrides: list[dict],
    branch_id: str | None,
    step_id: str,
) -> list[dict]:
    """Compute blocking issues that prevent review completion.

    This is the single source of truth for the review-completion gate,
    shared by the editor state, the review endpoint, and evidence/report.
    """
    blockers: list[dict] = []

    if selected_variables and not variable_summaries:
        return [{
            "code": "VARIABLE_SUMMARY_UNREADABLE",
            "message": (
                f"Final WOE/IV evidence could not be loaded for "
                f"{len(selected_variables)} selected variable(s). "
                "Review cannot be completed while evidence is unreadable."
            ),
            "step_id": step_id,
        }]

    override_vars = {ov.get("variable") for ov in current_overrides}

    for vs in variable_summaries:
        if vs.review_required:
            blockers.append({
                "code": "UNREVIEWED_REQUIRED_VARIABLE",
                "message": f"Variable '{vs.variable}' requires review but has no covering override with a valid reason code.",
                "variable": vs.variable,
            })
        if vs.zero_cell_warning_count > 0 and vs.variable not in override_vars:
            blockers.append({
                "code": "UNRESOLVED_ZERO_CELL",
                "message": f"Variable '{vs.variable}' has {vs.zero_cell_warning_count} zero-cell bin(s) with no covering override.",
                "variable": vs.variable,
            })
        if vs.sparse_bin_warning_count > 0 and vs.variable not in override_vars:
            blockers.append({
                "code": "UNRESOLVED_SPARSE_BIN",
                "message": f"Variable '{vs.variable}' has {vs.sparse_bin_warning_count} sparse bin(s) with no covering override.",
                "variable": vs.variable,
            })

    # Check edits without reason_code
    for ov in current_overrides:
        if not ov.get("reason_code") or not ov.get("reason"):
            var = ov.get("variable", "?")
            blockers.append({
                "code": "EDIT_WITHOUT_REASON_CODE",
                "message": f"Override for '{var}' is missing a reason_code or reason.",
                "variable": var,
            })

    # Check unresolved missing handling
    for vs in variable_summaries:
        if (vs.missing_count or 0) > 0:
            covered = any(
                ov.get("variable") == vs.variable and ov.get("reason_code") == "missing_value_treatment"
                for ov in current_overrides
            )
            if not covered:
                blockers.append({
                    "code": "UNRESOLVED_MISSING_HANDLING",
                    "message": f"Variable '{vs.variable}' has missing bins with no covering 'missing_value_treatment' override.",
                    "variable": vs.variable,
                })

    # Check unresolved special handling
    for vs in variable_summaries:
        if (vs.special_bin_count or 0) > 0:
            covered = any(
                ov.get("variable") == vs.variable and ov.get("reason_code") == "special_value_treatment"
                for ov in current_overrides
            )
            if not covered:
                blockers.append({
                    "code": "UNRESOLVED_SPECIAL_HANDLING",
                    "message": f"Variable '{vs.variable}' has special bins with no covering 'special_value_treatment' override.",
                    "variable": vs.variable,
                })

    # Check branch mismatch
    if branch_id and step_id and "__" in step_id and branch_id not in step_id:
        blockers.append({
            "code": "BRANCH_MISMATCH",
            "message": f"Step '{step_id}' does not belong to branch '{branch_id}'.",
            "step_id": step_id,
        })

    return blockers
