# Audit Pack Structure

The audit pack is an export format produced by the report generation service. It bundles all evidence required for model governance review. The audit pack and the report bundle are the same output — the report generation service produces both `report_bundle.json` (structured data) and `report.html` (rendered view), which together form the audit pack.

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

1. User selects report mode (`"champion"` or `"branch"`) and target branch in the frontend `ExportPanel.tsx`
2. Frontend checks readiness via the API
3. Frontend calls `api.generateReport` with JSON and HTML output formats
4. Backend generates the report bundle and writes it as artifacts
5. Frontend renders the audit-pack export UI and readiness panel
