# Phase 5 Audit Pack Structure

## Overview

Phase 5 extends the existing Phase 4 branch audit pack by adding governance report outputs. The audit pack is produced by `export_service.py` and written to the project's `exports/` directory.

## Structure

```
audit_pack/
├── project.json                     # Project metadata (Phase 4)
├── branch.json                      # Branch metadata (Phase 4)
├── branch_step_map.json             # Branch step mapping (Phase 4)
├── plan_steps.json                  # Plan version step definitions (Phase 4)
├── runs.json                        # Run records (Phase 4)
├── run_steps.json                   # Run step records with execution fingerprints (Phase 4)
├── artifacts.json                   # Artefact index (Phase 4)
├── comparison_snapshot.json         # Comparison snapshot (Phase 4, optional)
├── champion_assignment.json         # Champion assignment (Phase 4, optional)
├── manifest/                        # Technical manifest (Phase 4)
├── artifacts/                       # Copied artefact files (Phase 4)
│   └── ...
├── report/                          # Phase 5 governance report
│   ├── report_bundle.json           # Canonical JSON report
│   └── report.html                  # Self-contained offline HTML report
└── report_artifacts/                # Supporting artefacts (Phase 5)
    ├── scorecard/
    ├── model/
    ├── validation/
    ├── binning/
    ├── pathway/
    └── branches/
```

## Phase 4 preservation

All existing Phase 4 files are preserved unchanged. Phase 5 only **adds** files under `report/` and `report_artifacts/`.

## report/report_bundle.json

The canonical governance report. Schema: `cardre.report_bundle.v1`. See [phase-5-report-schema.md](phase-5-report-schema.md).

## report/report.html

Self-contained offline HTML rendering of the report bundle. No external CSS, JS, or network dependencies. Table-first rendering.

## report_artifacts/

Supporting artefacts referenced by the report:

- `scorecard/final_scorecard.json` — final bin definitions
- `model/coefficients.json` — model coefficients
- `model/score_scaling.json` — scorecard scaling configuration
- `validation/metrics_by_role.json` — validation metrics
- `binning/woe_iv_evidence.json` — WOE/IV evidence artefact

## Checksums

The audit pack includes a `checksums.sha256` file covering all files including Phase 5 report outputs. The `artefact_index.json` also includes new report files.

## Export modes

The `export_branch_audit_pack` function supports an `include_report` parameter:

- `include_report=False` (default): Phase 4 behaviour, no report files
- `include_report=True`: Phase 4 files + Phase 5 report bundle and supporting artefacts

## Out of scope

- Raw datasets are not exported by default
- PDF export is explicitly out of scope for Phase 5
- No external JS or CSS is included in the HTML report
