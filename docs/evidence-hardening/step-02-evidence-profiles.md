# Step 02 — Expand Evidence Profiles and Typed Models

Target: every launch-critical EvidenceKind from spec §7 has a profile +
typed model + reader dispatch + test fixture.

## Launch-critical kinds (must all be covered)

```
MODELLING_METADATA          ← exists
SAMPLE_DEFINITION           ← exists
SPLIT_SUMMARY               ← MISSING
PROFILE_SUMMARY             ← MISSING
EXCLUSION_SUMMARY           ← MISSING
BIN_DEFINITION              ← exists
SELECTION_DEFINITION        ← exists
WOE_TABLE                   ← exists
IV_TABLE                   ← exists
WOE_IV_EVIDENCE             ← exists
VARIABLE_CLUSTERING        ← exists
MANUAL_BINNING_OVERRIDES    ← exists (kind)
WOE_TRANSFORM_EVIDENCE      ← MISSING (or alias to current WOE_APPLICATION_EVIDENCE?)
MODEL_ARTIFACT              ← exists
SCORE_SCALING               ← exists
FROZEN_SCORECARD_BUNDLE     ← exists (kind)
SCORED_DATASET              ← exists
APPLY_WOE_EVIDENCE          ← MISSING kind (current WOE_APPLICATION_EVIDENCE)
APPLY_MODEL_EVIDENCE        ← MISSING kind (current SCORE_APPLICATION_EVIDENCE)
VALIDATION_METRICS          ← exists
VALIDATION_EVIDENCE         ← exists
CUTOFF_ANALYSIS             ← exists
REPORT_BUNDLE               ← MISSING kind
RUN_MANIFEST                ← MISSING kind
TECHNICAL_MANIFEST_INDEX    ← MISSING kind
COMPARISON_ARTIFACT         ← MISSING kind
```

Note: the existing enum uses `WOE_APPLICATION_EVIDENCE` /
`SCORE_APPLICATION_EVIDENCE` names; the spec uses `APPLY_WOE_EVIDENCE` /
`APPLY_MODEL_EVIDENCE`. **Add aliases or add new enum members with
the spec names and deprecate the old ones in a comment.** Keep one
canonical name per concept; do NOT duplicate models. Prefer adding the
spec-named kinds and mapping old names as deprecated aliases in a
constants section.

## Advanced kinds (add enum members with empty/minimal models)

```
REJECT_POPULATION_CONFIG         ← exists
REJECT_INFERENCE_RESULT         ← exists
FEATURE_SELECTION_EVIDENCE      ← MISSING
RESAMPLING_EVIDENCE             ← MISSING
HYPERPARAMETER_TUNING_EVIDENCE  ← MISSING
ENSEMBLE_MODEL_ARTIFACT          ← MISSING
EXPLAINABILITY_REPORT            ← MISSING
FAIRNESS_REPORT                 ← MISSING
PROXY_RISK_REPORT                ← MISSING
```

Advanced kinds may have an experimental `from_json` that returns a
generic `ExperimentalEvidence` placeholder, with a comment that the
typed model will be promoted when launch-grade. Product code must still
go through the reader for them.

## Files to edit

- `cardre/_evidence/kinds.py` — add missing enum members + deprecation
  aliases for the old names if you rename.
- `cardre/_evidence/models.py` — add dataclasses for missing kinds.
  Use `from_json` factories that validate required keys.
- `cardre/_evidence/profiles.py` — add `_Profile` entries for every
  new kind with `expected_roles`, `expected_artifact_types`,
  `schema_version`, `expected_media_types`, `required_keys` (JSON) or
  `required_columns` (Parquet).
- `cardre/_evidence/schemas.py` — add `SCHEMA_<KIND>` version
  constants of the form `cardre.<snake_kind>.v1`.
- `cardre/_evidence/reader.py` — extend `_to_typed` dispatch and add
  per-kind parse methods where the parse is non-trivial (e.g. parquet
  with column selection). Add error handling per spec §11.

## Required dataclass fields for every typed model

- `source_artifact_id: str` — every evidence instance must know which
  artifact produced it (for diagnostics + governance).
- A `from_json(data: dict, artifact_id: str) -> Self` classmethod that
  validates `required_keys` and raises `EvidenceSchemaError` on mismatch.
- Use the existing patterns in `models.py` (e.g.
  `BinDefinition.from_json`) as the canonical style. Do not invent a
  different validation style.

## New error types (spec §11)

Add to `cardre/_evidence/kinds.py` if not present:
- `EvidenceSchemaError(EvidenceError)` — includes expected/actual
  schema version, expected role/type/media, candidate artifact IDs,
  step id.
- `LegacyEvidenceCompatibilityError(EvidenceError)`.
Make sure `EvidenceNotFoundError`, `AmbiguousEvidenceError`,
`EvidenceParseError` already carry the fields spec §11 lists
(evidence kind, artifact ID, candidate IDs, step ID). Augment their
constructors with optional kwargs and keep backwards compat with
existing call sites.

## Convenience methods (spec §8.2, §8.3, §8.4)

Add to `ArtifactEvidenceReader` in this step (so later migrations can use them):

- `find_model_artifact(artifacts)`, `find_bin_definition(artifacts)`,
  `find_selection_definition(artifacts)`,
  `find_woe_iv_evidence(artifacts)`, `find_score_scaling(artifacts)`,
  `find_validation_evidence(artifacts)`, `find_cutoff_analysis(artifacts)`,
  `read_report_bundle(artifact_id)`, `read_run_manifest(artifact_id)`
  — thin wrappers over `find`/`read`.
- `read_required_step_output(run_step, kind)` — raises typed
  `EvidenceNotFoundError` enriched with step id + candidate IDs if
  missing.
- `read_optional_step_output` (probably already exists as
  `read_step_output_optional`; keep both names as aliases).
- `read_all_step_outputs(run_step, kind)` — returns list (possibly
  empty) of evidence from all output artifact IDs of the step.
- `summarise_artifact(artifact_id)`,
  `summarise_step_outputs(run_step)`,
  `summarise_run_artifacts(run_id)` — return safe metadata dicts
  (artifact id, type, role, media_type, schema_version, size, hashes,
  and any high-level fields declared in the profile as
  "summary_safe_keys") without dumping raw JSON. These power sidecar
  previews in S6.

## Tests to add

`tests/test_evidence_profiles.py`:
- one parametrised test per launch-critical kind that asserts the
  profile exists with non-empty `schema_version`, expected role/type,
  and required keys/columns.
- one fixture per kind in `tests/fixtures/evidence/<kind>.json` (or
  `.parquet` for parquet kinds) and a parser round-trip test.

`tests/test_evidence_reader.py`:
- tests for the convenience methods + step output helpers.
- tests for `summarise_*` helpers returning safe metadata only (no
  raw payload leakage).

Do NOT add business tests that read real artifacts here — that's the
behavioural tests' job.

## Do not do in this step

- Do NOT modify any node in `cardre/nodes/` or `sidecar/routes/`.
- Do NOT delete or update `_evidence/schemas.py` constants already in
  use; only add.
- Do NOT change the guardrail test or audit script.

## Verify

```
pytest tests/test_evidence_profiles.py tests/test_evidence_reader.py
python scripts/audit_artifact_reads.py --production --json  # should still pass, no new violations in non-_evidence files
```