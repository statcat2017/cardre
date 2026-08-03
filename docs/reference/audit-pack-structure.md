# Audit Pack Structure

The audit pack is an export format that bundles all evidence required for model
governance review. It is produced by the `ExportAuditPack` use case
(`cardre/application/reporting/export_audit_pack.py`) and written under the
project's `exports/` directory.

## Contents

The audit pack includes:

- Run manifest
- Step evidence for all steps in the selected run
- Artifact references and hashes
- Model definition artifacts
- Validation metrics
- Scorecard parameters
- Manual binning overrides and review state

The pack is written as a directory of JSON files (one per step/run) plus a
checksums file, published atomically.

## Listing Exports

`GET /projects/{project_id}/exports` lists the persisted export records
(optionally filtered by `run_id`). Each record describes an export produced for
a run; the route does not generate a new pack on demand.
