# Phase 4 — Close Evidence Writer `schema_version` Gaps

**Sprint:** `docs/plans/legacy-compat-removal-sprint.md`
**Phase goal:** Add `schema_version` to the artifact metadata (and payload,
where the profile expects it) of the 9 writers that currently omit it. Purely
additive — no consumer behaviour changes; this just lets
`ArtifactEvidenceReader` Phase-1 schema matching resolve these artifacts
instead of falling through to Phase-2/3 heuristics.

## Authority

The source report's safer-refactor guidance: *"first ensure all current
artifact writers emit schema versions consistently, then remove the fallback
branches one evidence kind at a time."* This phase is the "ensure writers
emit" half; Phase 5 is the "remove branches" half.

A pre-sprint audit identified 9 writers that omit `schema_version`. Each
evidence kind has a profile in `cardre/_evidence/profiles.py` declaring a
`schema_version` constant (imported from `cardre/_evidence/schemas.py`). The
reader's Phase 1 match (`cardre/_evidence/reader.py:268-278`) filters
artifacts by `a.metadata.get("schema_version") in {profile.schema_version}`.

## Files

### Read first (do not edit)
- `cardre/_evidence/schemas.py` — all `SCHEMA_*` constants (the values to
  emit). Notably `SCHEMA_WOE_TABLE`, `SCHEMA_SPLIT_SUMMARY`,
  `SCHEMA_PROFILE_SUMMARY`, `SCHEMA_EXCLUSION_SUMMARY`,
  `SCHEMA_WOE_TRANSFORM_EVIDENCE`, `SCHEMA_TECHNICAL_MANIFEST_INDEX`.
- `cardre/_evidence/profiles.py` — the profile for each kind, to see whether
  `schema_version` is checked against `metadata` or `payload`.
- `cardre/_evidence/reader.py:256-296` — the three-phase `_match()`. Phase 1
  checks `a.metadata.get("schema_version")`.
- `cardre/artifacts.py:25-55` (`write_json_artifact`) and `:58-100`
  (`write_parquet_artifact`) — both accept a `metadata` dict that is stored
  on the `ArtifactRef`.

### Modify (the 9 writers)

| # | Evidence kind | Writer | File:line | Constant to emit |
|---|---|---|---|---|
| 4.1 | `IV_TABLE` | `CalculateWoeIvNode` (IV parquet) | `cardre/nodes/build/features.py:316-321` | `SCHEMA_WOE_TABLE` |
| 4.2 | `SCORED_DATASET` | WOE-apply scored parquet | `cardre/nodes/validate/apply.py:189-194` | `SCHEMA_WOE_TABLE` *or the scored-dataset schema if one exists — check the profile* |
| 4.3 | `SCORED_DATASET` | adapters (3 sites) | `cardre/modeling/adapters.py:166-189, 280-289, 399-403` | (same as 4.2) |
| 4.4 | `SCORED_DATASET` | `DummyApplyNode` | `cardre/nodes/validate/apply.py:401-412` | (same as 4.2) |
| 4.5 | `SPLIT_SUMMARY` | `DevelopmentSampleDefinitionNode` | `cardre/nodes/prep.py:765-781` | `SCHEMA_SPLIT_SUMMARY` |
| 4.6 | `PROFILE_SUMMARY` | `ProfileDatasetNode` | `cardre/nodes/prep.py:462-468` | `SCHEMA_PROFILE_SUMMARY` |
| 4.7 | `EXCLUSION_SUMMARY` | `ApplyExclusionsNode` | `cardre/nodes/prep.py:988-992` | `SCHEMA_EXCLUSION_SUMMARY` |
| 4.8 | `WOE_TRANSFORM_EVIDENCE` | `CalculateWoeIvNode` (transform report) | `cardre/nodes/build/features.py:484-494` | `SCHEMA_WOE_TRANSFORM_EVIDENCE` |
| 4.9 | `TECHNICAL_MANIFEST_INDEX` | `TechnicalManifestExportNode` | `cardre/nodes/build/export.py:236-241` | `SCHEMA_TECHNICAL_MANIFEST_INDEX` |

> **Important — confirm the constant for `SCORED_DATASET` before editing.**
> The audit found the SCORED_DATASET profile has `schema_version=""` in some
> readings, meaning no schema constant is defined yet. Read the
> `SCORED_DATASET` profile in `cardre/_evidence/profiles.py` first. If its
> `schema_version` is empty, **this phase cannot fix SCORED_DATASET** — skip
> 4.2-4.4 and record SCORED_DATASET as "no schema constant defined; deferred".
> Only fix writers whose kind has a non-empty `schema_version` constant.

## Steps

For each writer, the change is the same pattern: add `"schema_version":
SCHEMA_X` to the `metadata` dict passed to `write_json_artifact` /
`write_parquet_artifact`. If the writer passes `metadata` as a literal dict,
add the key in place. If it builds metadata separately, add the key to that
dict.

### Pattern (JSON artifact)
```python
# before
write_json_artifact(
    store,
    artifact_type=...,
    role=...,
    stem=...,
    payload=payload,
    metadata={"purpose": ..., "zero_cell_policy": ...},   # no schema_version
)
# after
write_json_artifact(
    store,
    artifact_type=...,
    role=...,
    stem=...,
    payload=payload,
    metadata={"purpose": ..., "zero_cell_policy": ..., "schema_version": SCHEMA_WOE_TABLE},
)
```

### Pattern (parquet artifact)
`write_parquet_artifact` merges the passed `metadata` into `artifact_meta`
(`artifacts.py:82-88`). Add `"schema_version": SCHEMA_X` to the `metadata`
argument.

### Import the constant
Each writer file must import the relevant `SCHEMA_*` constant from
`cardre._evidence.schemas`. Prefer the canonical `cardre._evidence.schemas`
import path (consistent with the sprint's long-term direction) rather than
the `cardre.evidence` facade — but if the file already imports via
`cardre.evidence`, use the existing import to minimize churn. Do **not**
introduce a new `cardre.evidence` import in a file that doesn't already use it.

### Order
Work top-to-bottom through the table (4.1 → 4.9). After each writer, run its
focused test to confirm no regression:
```bash
. .venv/bin/activate
pytest tests/test_binning.py tests/test_optbinning.py tests/test_woe.py \
       tests/test_scorecard_model.py tests/test_reporting.py -q
```

## Verification commands

```bash
. .venv/bin/activate

# After all 9 writers: confirm schema_version is emitted.
# (Adjust the grep if you skipped SCORED_DATASET per the note above.)
pytest tests/test_evidence_reader.py tests/test_binning.py tests/test_woe.py \
       tests/test_optbinning.py tests/test_scorecard_model.py \
       tests/test_reporting.py tests/test_reporting_acceptance.py -q

# Lint + preflight.
ruff check --fix
make preflight
```

## Definition of done for this phase

- [ ] Every writer in the table whose kind has a non-empty `schema_version`
      constant now emits `"schema_version": SCHEMA_X` in artifact metadata.
- [ ] Each `SCHEMA_X` is imported from `cardre._evidence.schemas` (or the
      existing `cardre.evidence` import in that file, if already present).
- [ ] A test (new or existing) confirms each fixed writer's artifact carries
      `schema_version` in metadata — add a small assertion to the relevant
      existing test rather than a new file where possible.
- [ ] SCORED_DATASET is either fixed or explicitly recorded as deferred (if
      its profile has no schema constant).
- [ ] No existing test regresses.
- [ ] `ruff check` clean.
- [ ] `make preflight` green.
- [ ] PR raised via `scripts/pr-gate.sh`; CI green.

## Failure mode

- **`SCHEMA_X` not found in `cardre._evidence.schemas`:** the constant name in
  the table is a guess. Read `cardre/_evidence/schemas.py` and use the real
  name. If no constant exists for the kind, skip that writer and record it
  as deferred.
- **Profile's `schema_version` is empty string:** Phase 1 matching cannot
  resolve that kind no matter what the writer emits. Skip it; it's deferred
  until a schema constant is defined.
- **A test asserts the *absence* of `schema_version` in metadata:** that
  would be a test asserting the buggy state. Update it to assert presence.
- **Writer emits `schema_version` in payload but profile checks metadata
  (or vice versa):** Phase 1 checks `a.metadata.get("schema_version")`. Emit
  in metadata. If the profile also requires it in payload (check
  `required_keys`), emit there too.