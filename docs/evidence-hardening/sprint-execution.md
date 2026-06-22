# Sprint Execution — How to Run the Hardening Sprint in Parallelised Batches

The original spec serialises PRs 1→10, but most of the migration work is
file-isolated. Use the batches below to overlap work safely. Within each
batch, launch independent subagents in parallel; merge a batch before
starting the next so that downstream agents can rely on the new typed
readers and removed violations.

## Batches

### Batch A (foundations, parallel — 2 agents)
- S1 — audit script (`scripts/audit_artifact_reads.py`)
- S2 — evidence profiles + typed models for launch-critical kinds

Gate: both merged. CI green. Audit script can emit current violators,
which feeds the migration steps.

### Batch B (production migration, parallel — up to 5 agents)
Run in parallel; each agent owns a disjoint file set, so merge conflicts
are minimal:

- S3a — `cardre/nodes/build/models.py` (one agent)
- S3b — `cardre/nodes/build/selection.py` + `freeze.py` + `export.py` (one agent)
- S4 — `cardre/nodes/validate/apply.py`
- S5a — `cardre/nodes/explainability.py` + `fairness.py` (advanced/experimental, more coupled)
- S5b — `cardre/nodes/ensembles.py` + `feature_selection.py`
- S6 — services + sidecar routes (`manual_binning_service.py`, `comparison_service.py`, `sidecar/routes/artifacts.py`, `method_summary.py`, `runs.py`)

Gate: each agent's file count in the audit report's `production_violation` class
is 0 (excluding dataset-frame-input parquet reads where the spec allows them —
e.g. `LogisticRegressionNode` reading WOE-transformed training Parquet). CI green.
Do not start Batch C until the audit script shows zero production violators in
the migrated files.

### Batch C (reporting convergence — sequential, 1 agent)
- S7 — `reporting/collector.py` + `TechnicalManifestExportNode` in `nodes/build/export.py`.

This depends on S3 (export node already migrated by S3b); here it's about aligning
the report collector + manifest generation to *also* go through `ArtifactEvidenceReader`
and share interpretation with the build nodes. Must not introduce a second
interpreter. Verify: `reporting/collector.py` 0 production violations.

### Batch D (tests — parallel — 2 agents)
- S8a — `tests/helpers/evidence_assertions.py` + `test_scorecard_model.py`, `test_frozen_scorecard_bundle.py`, `test_reporting_acceptance.py`
- S8b — `test_woe.py`, `test_binning.py`, `golden_scorecard/`, `test_sidecar_api.py`, `test_ml_ensembles.py`, `test_boosting_fairness.py`

Gate: `test_violation` count in audit script materially reduced. Raw assertions
remain only in `test_artifact_serialization.py`, `test_evidence_reader.py`,
`test_legacy_artifact_compatibility.py`.

### Batch E (lock-down — sequential, 1 agent)
- S9 — strict guardrail (`tests/test_artifact_guardrail.py`): delete
  `_EXISTING_VIOLATORS`, narrow `APPROVED_PATTERNS` to
  `cardre/artifacts.py`, `cardre/evidence.py`, `cardre/_evidence/`,
  `cardre/modeling/serialization.py`. Add inline-suppression support
  with `# cardre-allow-artifact-read: <reason>` and the four allowed
  reasons. Add CI jobs: `make test-evidence`, `make audit-artifact-reads`,
  `make test-launch-core`.

Gate: `tests/test_artifact_guardrail.py` passes with zero allowlist; new
production direct reads fail CI.

### Batch F (documentation — parallel with E review — 1 agent)
- S10 — `docs/architecture/artifact-evidence-access.md` covering the
  artifact/evidence distinction, approved read paths, forbidden patterns,
  how to add an evidence kind, how to write a node, report collector,
  sidecar preview, test, and legacy-compat policy. Update the guardrail
  failure message to link to this doc.

## Operating rules for the batches

1. **One step = one PR.** Each batch's steps merge as small PRs; do not
   batch unrelated steps into a single PR.
2. **Before merging a migration step**, run `python
   scripts/audit_artifact_reads.py --production --json` and include the
   before/after delta in the PR description.
3. **The audit script is the source of truth** for violation counts, not
   the guardrail test. The guardrail becomes strict only in Batch E.
4. **Do not delete or extend `_EXISTING_VIOLATORS` during Batches B/C/D.**
   Migration steps must remove violations by rewriting code, not by
   allowlisting. `_EXISTING_VIOLATORS` shrinks naturally as files are
   cleaned; the guardrail test stays green via the existing allowlist.
5. **Subagent scope**: each agent receives exactly the per-step
   instruction file plus this batch map. They are NOT given the whole
   spec. They edit only their assigned files.
6. **Dataset-frame-input exception**: `pl.read_parquet(store.artifact_path(...))`
   reading WOE-transformed training data for `LogisticRegressionNode`
   and downstream model fitting is allowed per spec §9 PR3. Use the
   inline suppression `# cardre-allow-artifact-read: dataset-frame-input`
   so the audit classifies it correctly.
7. **Byte download routes**: `sidecar/routes/artifacts.py` streaming
   artifact bytes (without interpreting content) is allowed per spec
   §9 PR6. Use `# cardre-allow-artifact-read: artifact-byte-download`.
8. **`cardre/modeling/serialization.py`** is approved for binary
   estimator IO. Keep it in the narrowed `APPROVED_PATTERNS`.
9. **No new raw JSON parsing** in product code even "temporarily". If a
   typed reader is missing, expand `cardre/_evidence/` (S2 work) instead.
10. **Legacy compatibility goes in `_evidence/` only** (spec §12).

## Critical path (fallback if parallelism is limited)

If only one agent is available, run in this order:
S1, S2, S3, S4, S5, S6, S7, S8, S9, S10 — the original PR sequence.
Critical path target: Batches B is the longest (6 agents reduced to 1).
Expect ~60% of total sprint effort in Batch B.