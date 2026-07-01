# Phase 5 — Retire `ArtifactEvidenceReader._legacy_match()` Branches

**Sprint:** `docs/plans/legacy-compat-removal-sprint.md`
**Phase goal:** Remove the `_legacy_match()` branches for the evidence kinds
whose writers now emit `schema_version` (Phase 4), so the reader resolves
those artifacts via Phase 1 schema matching alone. Leave branches for
not-yet-audited kinds untouched.

## Authority

The source report: *"remove the fallback branches one evidence kind at a
time."* The safer refactor is incremental — each removal is gated on the
writer fix (Phase 4) and a Phase-1 regression test.

**Depends on Phase 4 being merged.** Do not start this phase until Phase 4 is
green on `main`.

## Files

### Read first (do not edit)
- `cardre/_evidence/reader.py:256-296` — `_match()` three phases. Phase 1
  (268-278) returns if schema-version candidates exist; Phase 2 (280-291)
  role/type/media fallback; Phase 3 (293-296) calls `_legacy_match`.
- `cardre/_evidence/reader.py:349-420` — `_legacy_match()`, with a branch per
  `EvidenceKind`.
- `cardre/_evidence/profiles.py` — each kind's `schema_version` (must be
  non-empty for Phase 1 to resolve).
- `tests/test_evidence_reader.py` — existing reader tests.

### Modify
- `cardre/_evidence/reader.py` — remove the specified branches from
  `_legacy_match()`.
- `tests/test_evidence_reader.py` — add Phase-1 regression tests.

## Scope — which branches to remove

Remove the branch for a kind **only if all** of the following hold:
1. Its writer(s) emit `schema_version` (Phase 4, merged).
2. Its profile's `schema_version` constant is non-empty.
3. A regression test asserts Phase 1 resolves it.

Based on the Phase 4 audit, the candidate kinds are:

| Evidence kind | Writer(s) fixed in Phase 4 | Remove branch? |
|---|---|---|
| `IV_TABLE` | `CalculateWoeIvNode` (IV parquet) | Yes, if 4.1 landed |
| `SPLIT_SUMMARY` | `DevelopmentSampleDefinitionNode` | Yes, if 4.5 landed |
| `PROFILE_SUMMARY` | `ProfileDatasetNode` | Yes, if 4.6 landed |
| `EXCLUSION_SUMMARY` | `ApplyExclusionsNode` | Yes, if 4.7 landed |
| `WOE_TRANSFORM_EVIDENCE` | `CalculateWoeIvNode` (transform) | Yes, if 4.8 landed |
| `TECHNICAL_MANIFEST_INDEX` | `TechnicalManifestExportNode` | Yes, if 4.9 landed |
| `SCORED_DATASET` | adapters + apply nodes | **Only if 4.2-4.4 landed** (may be deferred if the profile had no schema constant) |

**Do NOT remove** branches for: `MODELLING_METADATA`, `SAMPLE_DEFINITION`,
`WOE_TABLE` (the evidence kind, distinct from IV_TABLE), `SELECTION_DEFINITION`,
`BIN_DEFINITION`, `MODEL_ARTIFACT`, `SCORE_SCALING`, `VARIABLE_CLUSTERING_EVIDENCE`,
`FROZEN_SCORECARD_BUNDLE`, `WOE_IV_EVIDENCE`, `APPLY_WOE_EVIDENCE`,
`APPLY_MODEL_EVIDENCE`, `VALIDATION_EVIDENCE`, `CALIBRATION_REPORT`,
`VALIDATION_METRICS`, `CUTOFF_ANALYSIS`, `REJECT_POPULATION_CONFIG`,
`REJECT_INFERENCE_RESULT`, `REPORT_BUNDLE`, `RUN_MANIFEST` (handled in Phase 3
via the profile, not here), `COMPARISON_ARTIFACT`, `FEATURE_SELECTION_EVIDENCE`,
`RESAMPLING_EVIDENCE`, `HYPERPARAMETER_TUNING_EVIDENCE`, `ENSEMBLE_MODEL_ARTIFACT`,
`EXPLAINABILITY_REPORT`, `FAIRNESS_REPORT`, `PROXY_RISK_REPORT`,
`MANUAL_BINNING_OVERRIDES`. These either already emit `schema_version` (so
Phase 1 already resolves them and the branch is dead-but-leave-it) or are
deferred-tier kinds not audited this sprint.

> **Note:** several of the "do not remove" kinds already emit `schema_version`
> (per the Phase-4 audit's ✓ list) — their `_legacy_match` branches are already
> unreachable. Removing them is safe but out of scope for this phase's
> incremental discipline. Leave them; a future cleanup can sweep unreachable
> branches once a coverage test proves Phase 1 covers every writer.

## Steps

Work one kind at a time. Each is a small, independently testable change. You
may batch a few related kinds per commit, but keep each kind's removal gated
on its regression test.

### Per-kind pattern

#### Step A — Add a Phase-1 regression test

In `tests/test_evidence_reader.py`, add (or extend) a test that writes an
artifact of the kind with `schema_version` in metadata and asserts the reader
resolves it via Phase 1 — i.e. `_match()` returns the artifact without
falling through to `_legacy_match()`. A simple shape:

```python
def test_<kind>_resolved_by_schema_version(self, ...):
    # write artifact with metadata={"schema_version": SCHEMA_X, ...}
    # reader.read_<kind>() succeeds and returns the artifact
    # optionally: monkeypatch _legacy_match to raise, proving it's not called
```

Run it; it must pass against the Phase-4-merged code (writer emits
`schema_version`, profile matches).

#### Step B — Remove the `_legacy_match()` branch

In `cardre/_evidence/reader.py:349-420`, delete the
`if kind == EvidenceKind.<KIND>:` block for that kind. If the kind's branch
is the last in a chain, also clean up the surrounding control flow.

#### Step C — Verify

```bash
. .venv/bin/activate
pytest tests/test_evidence_reader.py -q
pytest tests/test_binning.py tests/test_woe.py tests/test_optbinning.py \
       tests/test_scorecard_model.py tests/test_reporting.py -q
```

### Recommended order

1. `IV_TABLE` (4.1) — isolated, single writer.
2. `SPLIT_SUMMARY` (4.5), `PROFILE_SUMMARY` (4.6), `EXCLUSION_SUMMARY` (4.7) —
   all in `cardre/nodes/prep.py`, batchable.
3. `WOE_TRANSFORM_EVIDENCE` (4.8) — in `features.py`.
4. `TECHNICAL_MANIFEST_INDEX` (4.9) — in `export.py`.
5. `SCORED_DATASET` (4.2-4.4) — only if Phase 4 fixed it; otherwise skip and
   note as deferred.

## Verification commands

```bash
. .venv/bin/activate

# Focused reader tests (including new regression tests).
pytest tests/test_evidence_reader.py -q

# Broader suite to catch any consumer that relied on the heuristic.
pytest tests/test_binning.py tests/test_woe.py tests/test_optbinning.py \
       tests/test_scorecard_model.py tests/test_reporting.py \
       tests/test_reporting_acceptance.py tests/test_ml_scorecard_methods.py -q

# Lint + preflight.
ruff check --fix
make preflight
```

## Definition of done for this phase

- [ ] For each removable kind (per the table), a Phase-1 regression test
      exists and passes.
- [ ] The corresponding `if kind == EvidenceKind.<KIND>:` branch is deleted
      from `_legacy_match()`.
- [ ] `_legacy_match()` retains branches only for kinds not fixed this sprint
      (deferred-tier or already-Phase-1-resolving kinds left in place).
- [ ] No broader-suite test regresses.
- [ ] `ruff check` clean.
- [ ] `make preflight` green.
- [ ] PR raised via `scripts/pr-gate.sh`; CI green.

## Failure mode

- **A regression test fails after branch removal:** the writer for that kind
  does not actually emit `schema_version` (Phase 4 incomplete for that kind),
  or the profile's `schema_version` is empty. Re-check Phase 4's status for
  that kind; if it was deferred, **restore the branch** and leave that kind
  for a later sprint.
- **Phase 1 returns multiple candidates (ambiguous):** more than one artifact
  of the kind exists in the store with the same `schema_version`. Phase 1
  returns the list and the caller must disambiguate. This is a pre-existing
  ambiguity, not caused by this phase — but if a test relied on
  `_legacy_match` picking a specific one, restore the branch and investigate.
- **`_legacy_match` is still called for the kind after removal:** Phase 1
  didn't match. Confirm the artifact's `metadata["schema_version"]` equals
  the profile's `schema_version` exactly (string match, not substring).