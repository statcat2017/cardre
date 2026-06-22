# Step 07 — Migrate Reporting and Technical Manifest

Files:
- `cardre/reporting/collector.py`
- `cardre/nodes/build/export.py` (TechnicalManifestExportNode specifically —
  note S3b already cleaned raw reads in this file; this step is about
  *aligning interpretation*)

## Pre-req: S2, S3 done.

## Direct reads (from survey)

### `cardre/reporting/collector.py`
- L77 `path = store.artifact_path(art)` — `ReportCollector` reads
  many evidence kinds (modelling metadata, selected variables, model,
  scorecard, validation, cutoff). Replace every read not already
  going through `ArtifactEvidenceReader` with typed reader calls.

### `cardre/nodes/build/export.py` (TechnicalManifestExportNode)
Already migrated in S3b. Confirm there is no `_get_artifact_json`
helper remaining (spec §9 PR7). If found, remove or move into
`cardre/_evidence/` as approved compatibility code. After this step,
this node must NOT maintain a separate artifact interpretation from
`ReportCollector`.

## Required behaviour (spec §9 PR7)

1. `ReportCollector` consumes only typed evidence.
2. `TechnicalManifestExportNode` does not independently parse
   modelling metadata, selected variables, model, scorecard,
   validation, or cutoff JSON.
3. The technical manifest becomes a renderer/index of the canonical
   REPORT_BUNDLE, OR uses the same evidence collector as the report.
   The design choice: prefer the manifest as an *index* over the
   existing REPORT_BUNDLE artifact ids (so no second interpretation
   is created); if the node has no report bundle input upstream, fall
   back to collecting the same typed evidence `ReportCollector`
   uses. In both cases, both consumers must call the same `reader
   .find(...)` / `reader.read(...)` calls — no bespoke per-consumer
   parse path.

## How to share interpretation

Add a small internal module — NOT a new public API — if it reduces
duplication: e.g. `cardre/reporting/evidence_views.py` exposing a
function `collect_report_view(reader, artifacts) -> ReportView` that
both `ReportCollector` and `TechnicalManifestExportNode` call.
`ReportView` is a thin typed aggregate (dataclass), not a raw dict.
Do not introduce a parallel hierarchy of evidence models.

## Remove `_get_artifact_json`

If `cardre/reporting/collector.py` (or supporting reporting modules)
contains any `_get_artifact_json(store, ...)` or similarly-named
helper, either:
- delete it and use `reader.read(...)`, OR
- move it into `cardre/_evidence/legacy.py` as an approved
  low-level compatibility helper AND add an inline suppression
  `# cardre-allow-artifact-read: low-level-evidence-parser` plus a
  comment explaining why it's low-level.

## Acceptance criteria

- Report and technical manifest agree on model, variables, score
  scaling, validation, and cutoff data (add a parity test if one
  doesn't exist: build a run, render both, assert shared fields
  match).
- No direct artifact reads remain in `reporting/collector.py` or in
  the `TechnicalManifestExportNode` portion of `export.py`.
- `tests/test_reporting_acceptance.py` continues to pass.

## Do NOT do

- Do not change artifact formats on disk.
- Do not modify the guardrail test.
- Do not delete `reporting/limitation_codes.py` or any reporting
  template — only the reader access pattern.

## Verify

```
python scripts/audit_artifact_reads.py --production --json | grep reporting
pytest tests/test_reporting_acceptance.py tests/test_reporting.py
```