# PR2 — Complete typed evidence coverage

**Findings:** T1a, T1b, T1c (typed properties only), T2, T7, K2
**Batch:** C (sequential, after Batch B)
**Depends on:** PR1 (needs T6 resolver and the adapter table ready)
**Behaviour change:** No (additive — new types and properties, no consumer
changes yet)

## Goal

Complete the typed-evidence layer so that every launch-critical artifact
has a typed model + `EvidenceKind` + adapter, and `ModelArtifactV1` has
typed read-only properties for every field currently accessed via
`_raw.get(...)`. **This PR does NOT migrate consumers off `_raw`** — that
happens in PR3a/3b/3c, one vertical slice at a time. This avoids the
"150 call sites changed at once" trap.

This is the **highest-leverage and largest single step** in the sprint.

## Tasks

### T1a — Add 4 diagnostics evidence kinds + models + adapters

1. In `cardre/_evidence/kinds.py`, add enum members:
   - `COEFFICIENT_SIGN_DIAGNOSTICS = "coefficient_sign_diagnostics"`
   - `SEPARATION_DIAGNOSTICS = "separation_diagnostics"`
   - `VIF_DIAGNOSTICS = "vif_diagnostics"`
   - `CALIBRATION_DIAGNOSTICS = "calibration_diagnostics"`
2. In `cardre/_evidence/schemas.py`, wire the existing schema constants
   (`SCHEMA_COEFFICIENT_SIGN_DIAGNOSTICS`, etc.) to the new enum members.
3. In `cardre/_evidence/models/`, create typed dataclasses (e.g.
   `cardre/_evidence/models/diagnostics.py`) for each diagnostic kind:
   - `CoefficientSignEntry(variable, feature_name, coefficient, sign,
     expected_sign, sign_match)` + `CoefficientSignDiagnostics(variables,
     schema_version)`
   - Same shape for `SeparationDiagnostics`/`SeparationEntry`,
     `VifDiagnostics`/`VifEntry`, `CalibrationDiagnostics`/`CalibrationRole`
   - Each with `from_json(data, artifact_id) -> Self` classmethod following
     the existing pattern.
4. Add `AdapterSpec` entries in `cardre/_evidence/adapters/__init__.py`
   wiring each kind to its profile + parse callable.
5. Add tests for each new model's `from_json` round-trip (mirror existing
   evidence-model tests).

### T1b — Add `ManualBinningOverrides` typed model

1. In `cardre/_evidence/models/binning.py`, define a typed
   `ManualBinningOverrides` dataclass matching the raw shape the collector
   currently reads via `getattr(data, "_raw", data)`:
   - `overrides: list[ManualBinningOverride]`
   - each override: `variable, action, bins, reason, comment, group_label, new_label`
   - `schema_version: str`, `source_artifact_id: str`
   - `from_json(data, artifact_id) -> Self`
   - `to_dict() -> dict` (the collector currently calls `data.to_dict()` via
     duck-typing — make it a real typed method)
2. Update `cardre/_evidence/adapters/__init__.py` to wire
   `ManualBinningOverrides.from_json` as the parse callable for
   `EvidenceKind.MANUAL_BINNING_OVERRIDES`.

### T1c — Add typed read-only properties to `ModelArtifactV1` (properties only, no consumer migration)

**Important:** This task adds typed properties to `ModelArtifactV1` so that
PR3a/3b/3c can replace `_raw.get(...)` with typed access. It does NOT
retire the existing `_evidence/models/model.py:ModelArtifact` or change
`build_model_artifact` — that retirement happens after all consumers are
migrated (a later PR or PR11).

1. Compare the three model-artifact representations:
   - `cardre/modeling/schema.py:ModelArtifactV1` (320 LOC, full typed —
     has `model_payload`, `feature_contract`, `prediction_contract`,
     `estimator_reference`, `training`, `interpretability`, `warnings`)
   - `cardre/_evidence/models/model.py:ModelArtifact` (152 LOC — has
     `features`, `intercept`, `coefficients`, `coefficients_dict`,
     `ensemble_type`, `base_models`, `weights`, `voting`, `threshold`,
     `estimator_reference: JsonDict`, `_raw: JsonDict`)
   - Raw `dict[str, Any]` from `build_model_artifact` (has `features`
     top-level, `bad_class_label`, `target_event_value`, `feature_strategy`
     top-level — **none of these are on `ModelArtifactV1`**)
2. Add typed read-only properties on `ModelArtifactV1` for every field
   currently accessed via `_raw.get(...)` in consumers. Grep
   `cardre/nodes/build/scoring_export.py` (47 hits), `calibrate.py` (22),
   `collector.py` (14), `freeze.py` (10), `comparison_service.py` (8) to
   identify the full set. Likely includes:
   - `coefficients_dict: dict[str, float]` (convenience currently on
     `ModelArtifact`)
   - `intercept: float`
   - `features: list[str]` (currently top-level in the raw dict, not on
     `ModelArtifactV1` — add as a property reading from
     `feature_contract.features` or the raw `model_payload`)
   - `base_odds: float` (parse `"N:M"` to float once in `from_dict` —
     fixes N4's inline `parse_base_odds` duplication)
   - `bad_class_label: str`, `target_event_value: str`,
     `feature_strategy: str` (currently top-level in raw dict only)
   - any other fields the grep reveals
3. Add round-trip tests: read the golden model artifact fixture
   (`tests/fixtures/golden_model_artifact.json` from PR0) through
   `ModelArtifactV1.from_dict()`, access every new property, assert
   values match the raw dict. This proves the properties are correct
   before any consumer migrates.
4. **Do not delete** `_evidence/models/model.py:ModelArtifact` or change
   `build_model_artifact` in this PR. Those retire after all consumers
   are migrated (PR11 or a dedicated retirement PR).

### T2 — Adapter table collapse

1. In `cardre/_evidence/adapters/__init__.py`, replace
   `EVIDENCE_ADAPTERS: dict[EvidenceKind, type[EvidenceAdapter]]` with
   `dict[EvidenceKind, AdapterSpec]` where:
   ```python
   @dataclass(frozen=True)
   class AdapterSpec:
       profile: _Profile
       parse: Callable[[Path, ArtifactRef, ProjectStore], Any]
   ```
2. Replace `get_adapter(kind)` to return the `AdapterSpec`.
3. Update `cardre/_evidence/reader.py` to use the new table. The shared
   `match` becomes a free function `match(profile, artifacts, store)`.
4. Delete all 40 adapter classes. For the ~30 trivial passthroughs, replace
   each with a single `AdapterSpec(profile=X_PROFILE, parse=lambda path,
   art, store: XModel.from_json(read_json_payload(path),
   artifact_id=art.artifact_id))` entry.
5. Keep the `EvidenceAdapter` Protocol for the ~3 adapters that do real
   `parse` work (`WoeTable`, `IvTable`, `ScoredDataset`) — convert them to
   `AdapterSpec` entries too if feasible.
6. Delete the duplicated `_match` helpers in `governance.py`, `manifest.py`,
   `model.py`, `sample.py`, `validation.py`, `woe.py`, and the inlined copy
   in `binning.py`.
7. Delete `kind`/`profile` class attrs from any remaining classes.

### T7 — Land the PR2 share of the binning cleanup

1. Replace `normalize` + `_normalize_var` with:
   ```python
   def normalize(self) -> "LifecycleBinDefinition":
       return dataclasses.replace(self, schema_version=SCHEMA_BIN_DEFINITION)
   ```
2. Rewrite `validate_overrides` and `apply_overrides` to take and return
   `LifecycleBinDefinition` (not `JsonDict`). Construct merged bins via
   `dataclasses.replace`/`LifecycleBin(...)`. This fixes the silent
   field-drop bug where merged-bin dict literals (lines 466-478) are
   missing `kind`/`woe`/`iv`/`bad_rate`/`row_pct`.
3. Update callers of `validate_overrides`/`apply_overrides` (likely in
   `cardre/services/manual_binning_service.py`) to pass/expect typed
   `LifecycleBinDefinition`.
4. Do not attempt repo-wide retirement of `BinDefinition` in PR2. If a
   wrapper still remains after these changes, PR7 owns only the narrow
   follow-up: current-schema fixture alignment and regression coverage for
   the manual-binning override seam.
5. Add round-trip tests using the golden bin definition + manual overrides
   fixtures from PR0. Assert that `apply_overrides` produces bins with ALL
   `LifecycleBin.from_dict` fields present.

### K2 — Dedup `artifacts.py` write/register dance

1. In `cardre/artifacts.py`, extract a shared helper:
   ```python
   def _register_bytes_artifact(
       store, *, bytes_writer, logical_hash, stem, media_type, directory, metadata
   ) -> ArtifactRef:
       # owns: mkdir parent, write via temp-file + replace, physical_hash,
       # build ArtifactRef, repo.register, dedup-return-existing
   ```
2. Rewrite `write_json_artifact`, `write_parquet_artifact`,
   `write_csv_artifact` as ~4-line functions calling the helper.
3. Reconcile the `try/except BaseException` inconsistency (json doesn't
   catch temp-cleanup; parquet/csv do). Pick one (narrow to
   `except OSError` and re-raise, or use a contextmanager).
4. In `cardre/modeling/serialization.py:write_estimator_artifact`, rewrite
   to use the same helper. It currently lacks temp-file atomicity and
   dedup-return — this fixes both.

## Acceptance criteria

- [ ] The 4 diagnostics kinds have `EvidenceKind` members, typed models,
  and `AdapterSpec` entries.
- [ ] `ManualBinningOverridesAdapter.parse` returns a typed model.
- [ ] `ModelArtifactV1` has typed read-only properties for every field
  accessed via `_raw.get(...)` in consumers (grep-verified against
  `scoring_export.py`, `calibrate.py`, `collector.py`, `freeze.py`,
  `comparison_service.py`).
- [ ] Golden model artifact round-trip test passes (every new property
  matches the raw dict value).
- [ ] `EVIDENCE_ADAPTERS` is a `dict[EvidenceKind, AdapterSpec]` table;
  ≤3 adapter classes remain.
- [ ] Duplicated `_match` helpers deleted.
- [ ] `BinDefinition` has no `_lifecycle: Any` field.
- [ ] `normalize` is `dataclasses.replace(self, schema_version=...)` (one
  line).
- [ ] `apply_overrides`/`validate_overrides` operate on typed
  `LifecycleBinDefinition`; merged bins include all
  `LifecycleBin.from_dict` fields.
- [ ] Golden bin definition + manual overrides round-trip tests pass.
- [ ] `write_estimator_artifact` uses the shared `_register_bytes_artifact`
  helper.
- [ ] `_evidence/models/model.py:ModelArtifact` still exists (not retired
  yet — retirement is after consumer migration).
- [ ] `build_model_artifact` still returns a dict (not changed yet).
- [ ] `ruff check` clean; `pytest tests/ -q` green.
- [ ] `scripts/audit_quality.py --json` shows adapter count ≤3.

## Do not

- **Do not migrate any `_raw` consumers in this PR.** The typed properties
  are additive — consumers migrate in PR3a/3b/3c. This is the key change
  from the original plan: type unification and consumer migration are
  separate PRs.
- Do not delete `_evidence/models/model.py:ModelArtifact` — it retires
  after all consumers are migrated.
- Do not change `build_model_artifact`'s return type — it stays a dict
  until consumers are migrated and the retirement PR is safe.
- Do not touch `reporting/collector.py`'s structure (that's PR5).
