# Phase 5A Implementation Plan

## Governance Report Evidence Model

Phase 5A builds the structured JSON report model and section manifest.
It does not render HTML/PDF — that comes in 5C/5F.

## Scope

1. **Report data model** — `GovernanceReport`, `ReportSection`, `EvidenceRef`
2. **Section manifest** — 13 sections listed in `SECTION_MANIFEST`
3. **Evidence collector** — reads from:
   - Project/branch metadata
   - Branch step map (`branch_step_map`)
   - Run-step records (`run_steps`)
   - Artifact records and files (`artifacts` + JSON/Parquet reads)
   - Comparison snapshots (`branch_comparison_snapshots`)
   - Champion assignments (`champion_assignments`)
4. **Technical manifest integration** — already exists as JSON artifact
5. **Missing-evidence diagnostics** — warns when required sources are absent

## Files

| File | Action | Content |
|---|---|---|
| `cardre/services/report_service.py` | Created (scaffold) | Data model, section manifest, `create_empty_report()` |
| `cardre/services/report_service.py` | Extend | Evidence collector methods: `collect_branch_info`, `collect_run_evidence`, `collect_woe_iv`, `collect_model`, `collect_validation`, `collect_cutoff`, `collect_comparison`, `collect_champion` |
| `cardre/services/report_service.py` | Extend | `build_report(store, project_id, branch_id)` that assembles a fully populated `GovernanceReport` |
| `docs/plans/phase-5-starting-point.md` | Updated | Points to the scaffold |

## Acceptance Criteria

- `build_report()` returns a fully typed `GovernanceReport` with all 13 sections
- Every section has at least one `EvidenceRef` (or a diagnostic warning if missing)
- No modelling execution during report assembly
- No run records created during report assembly
- Report content is structurally JSON-serialisable via dataclasses
- `EvidenceRef.source_type` is always one of the 5 allowed types
