# Audit Pack Structure

The audit pack is an export format produced by the export service (`sidecar/routes/exports.py`). It bundles all evidence required for model governance review.

## Contents

The audit pack includes:
- Run manifest
- Step evidence for all steps in the selected run
- Artifact references and hashes
- Model definition artifacts
- Validation metrics
- Scorecard parameters
- Manual binning overrides and review state

## Export Flow

1. User selects report mode and target branch in the frontend `ExportPanel.tsx`
2. Frontend checks readiness via the API
3. Frontend calls `api.generateReport` with JSON and HTML output formats
4. Backend generates the report bundle and writes it as artifacts
5. Frontend renders the audit-pack export UI and readiness panel
