# Legacy-Compatibility Collapse Plan

**Status:** Finalized
**Date:** 2026-07-14
**Authority:** ADR 0003 (`docs/adr/0003-no-legacy-plan-accommodation.md`) — Cardre is unreleased; no persisted plans, no production users, no external integrations require backward compatibility.
**Supersedes:** `docs/plans/legacy-compat-removal-sprint.md` (Phases 1, 2, 4, 5 already done; this sprint completes the remaining Phases 3 + 6 plus the binning-identity and artifact-schema collapse that the prior sprint deliberately deferred).

---

## 1. Goal

Leave Cardre with **one** of everything canonical and **zero** compatibility shims:

- One canonical workflow.
- One canonical identity for each node (automatic binning and manual binning are distinct first-class stages).
- One canonical format for each artifact.
- One canonical parameter schema.
- One canonical run-manifest representation.
- One current database schema.
- No legacy aliases, compatibility fallbacks, migration shims, or deprecated wrappers.

## 2. Critical workflow clarification: automatic and manual binning are separate stages

The scorecard workflow bins variables twice for different purposes. **Do not conflate them.**

### Stage 1 — automatic initial binning
Algorithmic; applies to the broad set of candidate variables on `train`. Methods (`fine_classing`, `optbinning`, future `chi_merge`/`tree_binning`) are values of the node's `method` parameter, **not** separate node identities. Produces an *initial* `BIN_DEFINITION` artifact. WOE/IV computed downstream by `cardre.calculate_woe_iv` with `purpose="initial"`.

### Stage 2 — manual binning and expert refinement
A separate first-class refinement node (`cardre.manual_binning`). Consumes the initial bin definition (+ selection definition), applies expert overrides (merge/group/reject/reorder), produces the *final* `BIN_DEFINITION` artifact. WOE/IV recomputed by `cardre.calculate_woe_iv` with `purpose="final"`. The final WOE map, IV, and bin definitions are what model fitting, scoring, validation, reporting, and exports consume.

### Canonical sequence

```
Import and preparation
    ↓
Automatic initial binning          (cardre.automatic_binning)
    ↓
Initial WOE / IV                   (cardre.calculate_woe_iv, purpose=initial)
    ↓
Variable clustering and correlation analysis
    ↓
Variable selection
    ↓
Manual binning and expert refinement (cardre.manual_binning)
    ↓
Final WOE / IV                     (cardre.calculate_woe_iv, purpose=final)
    ↓
WOE transformation
    ↓
Model fitting
    ↓
Score scaling and validation
```

The two binning stages cannot be confused because:
1. Distinct `node_type` identities (`cardre.automatic_binning` vs `cardre.manual_binning`).
2. The canonical workflow routes each consumer's `BIN_DEFINITION` via explicit `parent_step_ids` (initial-woe-iv parents automatic-binning; final-woe-iv parents manual-binning; score-scaling parents manual-binning; woe-transform-train parents manual-binning).
3. The `purpose` param on `CalculateWoeIvNode` (`initial`|`final`) is part of the node's params hash and the emitted artifact metadata, making stage explicit in the evidence.

## 3. Canonical architecture selected

### Canonical node identities
| Concept | Identity | Category | Notes |
|---|---|---|---|
| Automatic initial binning | `cardre.automatic_binning` | fit | Renamed from `cardre.fine_classing`. `method` param dispatches `fine_classing`/`optbinning`/future methods. |
| Manual binning | `cardre.manual_binning` | refinement | Unchanged — remains a distinct first-class node. |

`cardre.auto_binning_fit` (orphaned, never registered) and `cardre.binning` (planned in docs, never implemented) are removed entirely.

### Canonical artifact identities
| Artifact | Schema | Notes |
|---|---|---|
| Bin definition | `cardre.bin_definition.v1` | Single format for both automatic and manual outputs. Stage distinguished by producing run step (graph routing), not schema. |
| WOE table | `cardre.woe_table.v1` | Initial vs final distinguished by `purpose` param/metadata + graph routing. |
| IV table | `cardre.iv_table.v1` | Same. |
| WOE/IV evidence | `cardre.woe_iv_evidence.v1` | Same. |
| Model artifact | `cardre.model_artifact.v1` | Single `ModelArtifactV1`; `_raw` escape hatches removed; list-of-dicts `coefficients` form rejected. |
| Score scaling | `cardre.score_scaling.v1` | Single field name `points_to_double_odds` (int); single `score_direction` (string enum) across scorecard AND model artifacts. |
| Scored dataset | (parquet, no JSON schema version) | One column `score`; `cardre_scaled_score` removed. |
| Run manifest | `cardre.run_manifest.v1` | One canonical `RunManifest` model, written once, registered once as the `run_manifest` artifact. |

### Canonical parameter schema
- Score scaling: `points_to_double_odds` (int) — sole name. No `pdo` alias.
- Score direction: `score_direction` (string: `higher_is_lower_risk` | `higher_is_better`) — sole representation across scorecard + model artifacts. The node's UI param may stay `higher_score_is_lower_risk` (bool) for form clarity; it is translated to `score_direction` (string) in the artifact.
- No dual-accept `data.get(a, data.get(b))` fallbacks in any reader.

### Canonical database schema
- Single baseline: `V2_STORE_SCHEMA_VERSION = 101`. Migration runner removed. `check_and_migrate` becomes a strict family+version check: family must be `cardre-v2` and version must equal `101`, else `SchemaVersionError`. Opening a v100 dev database fails with a clear unsupported-schema error.

## 4. Legacy compatibility mechanisms to remove

| # | Mechanism | Location | Action |
|---|---|---|---|
| 1 | `AutoBinningFitNode` class + `cardre.auto_binning_fit` identity (orphaned, never registered, `is_internal=True` never read) | `cardre/nodes/build/auto_binning_fit.py` (entire file) | Delete file; move `_run_optbinning` into `cardre/nodes/build/bins.py`. |
| 2 | Mislabel `"cardre_node_type": "cardre.fine_classing"` in optbinning manifest | `auto_binning_fit.py:449` | Removed with file; `_run_optbinning` writes correct `cardre.automatic_binning`. |
| 3 | `is_internal` field on `NodeType` (set, never read by behaviour) | `cardre/nodes/contracts.py:41` | Remove field; remove `is_internal=True` from `DummyFitNode`, `NoopNode`. |
| 4 | `is_deprecated` field on `NodeType` (never set, never read) | `cardre/nodes/contracts.py:42` | Remove field. |
| 5 | Compat-alias enum members `WOE_APPLICATION_EVIDENCE`, `SCORE_APPLICATION_EVIDENCE` | `cardre/_evidence/kinds.py:33,35` | Remove. |
| 6 | Compat-alias constants `SCHEMA_WOE_APPLICATION_EVIDENCE`, `SCHEMA_SCORE_APPLICATION_EVIDENCE` | `cardre/_evidence/schemas.py:28,30` | Remove; update callers to canonical names. |
| 7 | `LegacyEvidenceCompatibilityError` (no raiser after `_legacy_match` removal) | `cardre/_evidence/kinds.py:66` | Remove class. |
| 8 | Dual score-scaling name `pdo` vs `points_to_double_odds` | `cardre/_evidence/models/model.py:152`; `cardre/reporting/schema.py:201`; `cardre/reporting/sections/score_scaling.py:33`; `tests/fixtures/golden_report_bundle.json:1813` | Canonical = `points_to_double_odds`. Reader uses single key; report bundle model + section + golden fixture renamed. |
| 9 | Dual score-direction representation (`higher_score_is_lower_risk` bool in scorecard; `score_direction` string in model) + dual-accept in reader | `cardre/_evidence/models/model.py:178-184`; scorecard writers `nodes/build/models.py:469`, `freeze.py:124`, `scoring_export.py`; `modeling/adapters.py:139,296` | Unify on `score_direction` (string). Scorecard artifact emits `score_direction`; readers read only that key. |
| 10 | Duplicate `cardre_scaled_score` column | `cardre/modeling/adapters.py:196-197,301-302` | Remove both write lines. |
| 11 | Dual-key writer+reader in validation metrics (`roles`+`metrics`, `stability`+`psi`, `cutoff_tables`+`tables`, `score_cutoff`+`score`) | `cardre/nodes/validate/analyse.py:468-471,907`; `cardre/_evidence/models/validation.py:32,35,52,83,89` | Writer emits only `roles`, `stability`, `cutoff_tables`, `score_cutoff`. Reader uses single canonical key. |
| 12 | `_raw` escape hatches + permissive alternate-structure parsing in evidence models | `cardre/modeling/schema.py:220-265`; `cardre/_evidence/models/model.py`, `validation.py`, `apply.py`, `manifest.py:71` | Remove `_raw` fields; define explicit typed fields; parse only canonical structure; reject unknown. `ModelArtifact.from_json` accepts only dict-form `coefficients`. `features` and `model_family` required. |
| 13 | Two parallel model-artifact classes (`ModelArtifactV1` vs `ModelArtifact`) | `cardre/modeling/schema.py:190`; `cardre/_evidence/models/model.py:27` | Collapse to one canonical parser. |
| 14 | Legacy `RunRepository.finish()` wrapper | `cardre/store/run_repo.py:148-155` | Remove; update test callers to `transition`. |
| 15 | Run-manifest half-migration: legacy `MANIFEST_VERSION="1.0.0"` + `build_manifest_payload` vs canonical `RunManifest` model | `cardre/execution/run_lifecycle.py:30,45-88` | Replace with canonical builder emitting `cardre.run_manifest.v1` shape; register as artifact. |
| 16 | Orphaned `RUN_MANIFEST` evidence path (kind + adapter + profile + `RunManifestEvidence` model — no caller) | `cardre/_evidence/{kinds,schemas,profiles,adapters,models/manifest}`; `tests/test_evidence_adapters.py:234` | Remove. Manifest read via canonical file path (collector) + DB-registered artifact (audit). |
| 17 | DB migration runner + 100→101 step + migration test | `cardre/store/_schema_version.py:72-101`; `tests/test_store_repos.py:705-752` | Collapse to strict family+version check. Remove `_run_migrations` + test. |
| 18 | Stale `cardre/nodes/__init__.py` docstring "for backward compatibility" | `cardre/nodes/__init__.py:3` | Rephrase (facade stays — has live consumers). |
| 19 | Stale docs claims that `FineClassingNode`/`AutoBinningFitNode` were "removed from registry by PR318" | `docs/plans/thermo-nuclear-quality-sprint/decision-log.md:62`; `docs/plan-reviews/013-thermo-nuclear-codebase-review.md:994` | Mark historical/correct. |
| 20 | ADR 0003 references to `cardre.binning` rename (never executed) and `_LEGACY_NODE_TYPE_METHOD` (already deleted) | `docs/adr/0003-no-legacy-plan-accommodation.md:19,25,53` | Preserve reasoning; note canonical is `cardre.automatic_binning`; mark `_LEGACY_NODE_TYPE_METHOD` historical. |
| 21 | `optbinning-first-class-path-plan.md` / `optbinning-technical-implementation.md` describing `AutoBinningFitNode` + `cardre.binning` | `docs/plans/` | Mark superseded. |

## 5. PR batches

The work is split into **6 PRs**. Each PR is independently mergeable and testable, ordered by dependency. Each PR must pass `ruff check` + `make preflight` + the PR gate (`scripts/pr-gate.sh`) before human review.

| PR | Title | Depends on | Risk |
|----|-------|------------|------|
| 1 | `refactor(binning): collapse automatic-binning identities to cardre.automatic_binning` | — | Medium |
| 2 | `refactor(evidence): remove compat aliases and orphaned RUN_MANIFEST kind` | 1 | Low |
| 3 | `refactor(artifacts): canonical score column, score-direction, score-scaling name` | 2 | Medium |
| 4 | `refactor(artifacts): remove _raw escape hatches and dual-key parsing in evidence models` | 3 | High |
| 5 | `refactor(manifest+db): canonical run-manifest + collapse DB schema to baseline 101` | 4 | High |
| 6 | `docs: mark legacy-compat-removal complete; supersede stale binning/migration plans` | 5 | Low |

### Dependency graph
```
PR1 (binning identity)
  ↓
PR2 (evidence aliases / RUN_MANIFEST)
  ↓
PR3 (score column + score-direction + points_to_double_odds)
  ↓
PR4 (_raw removal + dual-key parsing)
  ↓
PR5 (manifest canonical + DB collapse)
  ↓
PR6 (docs)
```

Rationale for batching: the artifact-shape changes (PR3, PR4) are interdependent (readers and writers must change together), so they are sequenced. PR1 is isolated to node identity. PR2 is a pure-deletion cleanup. PR5 combines the two highest-risk independent changes (manifest + DB) because both are isolated modules with no shared files. PR6 trails with docs only.

---

## PR 1 — Collapse automatic-binning identities to `cardre.automatic_binning`

**Goal:** One canonical automatic-binning node identity. Delete the orphaned `AutoBinningFitNode` and its file. Rename `FineClassingNode` → `AutomaticBinningNode`, `cardre.fine_classing` → `cardre.automatic_binning`. Manual binning is untouched.

**Authority:** ADR 0003; user decision (rename to `cardre.automatic_binning`).

### Files to read first (do not edit)
- `cardre/nodes/build/bins.py` — `FineClassingNode` (lines 21-331) and `_run_fine_classing`.
- `cardre/nodes/build/auto_binning_fit.py` — `AutoBinningFitNode` (orphaned) + `_run_optbinning` (used by `FineClassingNode.run` at `bins.py:329`).
- `cardre/nodes/contracts.py` — `NodeType` (`is_internal`, `is_deprecated` fields at :41-42).
- `cardre/workflows/scorecard.py` — canonical steps (`fine-classing` step at :74-78; downstream parents referencing `fine-classing`).
- `cardre/nodes/registry.py` — registration lists.

### Code instructions

1. **Move `_run_optbinning` and its helper `_resolve_train_input`** from `cardre/nodes/build/auto_binning_fit.py` into `cardre/nodes/build/bins.py` (place after `_run_fine_classing`). Update the import at `bins.py:329`:
   ```python
   # was: from cardre.nodes.build.auto_binning_fit import _run_optbinning
   # now: direct call (same module)
   ```
   In `_run_optbinning`, fix `AutoBinningFitNode._NUMERIC_TYPES` → move the `_NUMERIC_TYPES` set to module level in `bins.py` as `_NUMERIC_TYPES` (or keep on the class). Replace the reference at the former `auto_binning_fit.py:273`.

2. **Fix the manifest mislabel** in `_run_optbinning` (was `auto_binning_fit.py:449`):
   ```python
   # was: "cardre_node_type": "cardre.fine_classing",
   "cardre_node_type": "cardre.automatic_binning",
   ```

3. **Rename the class and identity** in `cardre/nodes/build/bins.py`:
   - `class FineClassingNode(NodeType):` → `class AutomaticBinningNode(NodeType):`
   - `node_type = "cardre.fine_classing"` → `node_type = "cardre.automatic_binning"`
   - `title="Fine Classing"` → `title="Automatic Binning"`
   - In `validate_params` and `run`, the `require_train_artifact("cardre.fine_classing")` call at `bins.py:353` → `require_train_artifact("cardre.automatic_binning")`.

4. **Delete `cardre/nodes/build/auto_binning_fit.py`** entirely.

5. **Update `cardre/nodes/build/__init__.py`**: replace `FineClassingNode` with `AutomaticBinningNode` in the import from `.bins` and in `__all__`.

6. **Update `cardre/nodes/__init__.py`**: replace `FineClassingNode` with `AutomaticBinningNode` in the import from `.build` and in `__all__`. Also delete the misleading "for backward compatibility" phrase in the module docstring (line 3) — rephrase as: *"This module re-exports all node classes from subpackages as a convenience for the registry and tests."*

7. **Update `cardre/nodes/registry.py`**: replace `FineClassingNode` with `AutomaticBinningNode` in the import (line 178) and in the registration list (line 224).

8. **Remove dead contract fields** in `cardre/nodes/contracts.py`: delete `is_internal: bool = False` (line 41) and `is_deprecated: bool = False` (line 42). Then remove `is_internal = True` from:
   - `cardre/nodes/build/models.py:582` (`DummyFitNode`)
   - `cardre/nodes/build/models.py:619` (`NoopNode`)
   - (the `AutoBinningFitNode` one is gone with the deleted file)

9. **Update `cardre/workflows/scorecard.py`**:
   - Step id `"fine-classing"` → `"automatic-binning"`.
   - `node_type` `"cardre.fine_classing"` → `"cardre.automatic_binning"`.
   - Update every downstream step's `parent_step_ids` that reference `"fine-classing"`: `initial-woe-iv` (line 82), `manual-binning` (line 100), `final-woe-iv` (no — it parents `manual-binning`), `woe-transform-train` (no — parents `manual-binning`), `score-scaling` (line 158 — parents `manual-binning`, not `fine-classing`... verify). **Search the whole file for `"fine-classing"` and replace with `"automatic-binning"`.**

10. **Bulk-update tests**. Run this search and replace across `tests/` and `tests/fixtures/`:
    - `cardre.fine_classing` → `cardre.automatic_binning`
    - `FineClassingNode` → `AutomaticBinningNode`
    - `"fine-classing"` (step id) → `"automatic-binning"`
    - `AutoBinningFitNode` / `auto_binning_fit` references — remove (no test should import the deleted file; if any does, delete that import — `AutoBinningFitNode` was never registered).

    Verify with:
    ```bash
    rg -n "cardre\.fine_classing|FineClassingNode|\"fine-classing\"|AutoBinningFit|auto_binning_fit" cardre/ tests/
    # Must return zero matches after the changes.
    ```

### Test instructions
- Update `tests/test_binning_node.py` to instantiate `AutomaticBinningNode` and assert `node_type == "cardre.automatic_binning"`.
- Update `tests/test_node_registry_tiers.py` and `tests/test_deferred_nodes.py`: assert `cardre.automatic_binning` is a launch node; `cardre.auto_binning_fit` is not registered.
- Update `tests/conftest.py` fixtures that seed `cardre.fine_classing` steps → `cardre.automatic_binning`.
- Update `tests/fixtures/golden_report_bundle.json` step_type references.
- **Add** a guard test in `tests/test_node_registry_tiers.py` (or a new `tests/test_canonical_contract.py`):
    ```python
    def test_only_one_automatic_binning_node_registered():
        reg = NodeRegistry.with_defaults()
        assert reg.has("cardre.automatic_binning")
        assert not reg.has("cardre.fine_classing")
        assert not reg.has("cardre.auto_binning_fit")
        assert not reg.has("cardre.binning")

    def test_manual_binning_distinct_node():
        reg = NodeRegistry.with_defaults()
        manual = reg.resolve("cardre.manual_binning")
        assert manual.category == "refinement"
        assert manual.node_type == "cardre.manual_binning"
    ```

### Verification
```bash
. .venv/bin/activate
rg -n "cardre\.fine_classing|FineClassingNode|\"fine-classing\"|AutoBinningFit|auto_binning_fit|is_internal|is_deprecated" cardre/ tests/
# Zero matches.
ruff check --fix
pytest tests/test_binning_node.py tests/test_node_registry_tiers.py tests/test_deferred_nodes.py tests/test_launch_pathway.py tests/test_api_manual_binning.py -q
make preflight
scripts/pr-gate.sh
```

---

## PR 2 — Remove evidence compat aliases and orphaned `RUN_MANIFEST` kind

**Goal:** Delete the dead compat-alias enum members, schema constants, and the orphaned `RUN_MANIFEST` evidence path (kind + adapter + profile + model — no caller). Update the 3 callers of the compat-alias schema constants to use the canonical names.

**Depends on:** PR 1 (so `cardre.automatic_binning` is canonical before touching evidence).

### Files to read first
- `cardre/_evidence/kinds.py` — `WOE_APPLICATION_EVIDENCE` (:33), `SCORE_APPLICATION_EVIDENCE` (:35), `RUN_MANIFEST` (:38), `LegacyEvidenceCompatibilityError` (:66).
- `cardre/_evidence/schemas.py` — `SCHEMA_WOE_APPLICATION_EVIDENCE` (:28), `SCHEMA_SCORE_APPLICATION_EVIDENCE` (:30), `SCHEMA_RUN_MANIFEST` (:33).
- `cardre/_evidence/profiles.py` — `RUN_MANIFEST` profile (:223-228).
- `cardre/_evidence/adapters/__init__.py` — `RUN_MANIFEST` adapter (:158-161).
- `cardre/_evidence/models/manifest.py` — `RunManifestEvidence` (:53-87).
- Callers of compat-alias constants: `cardre/modeling/adapters.py:26,71,84`; `cardre/nodes/validate/apply.py:12,207,223`; `cardre/nodes/validate/analyse.py:17,211`.

### Code instructions

1. **Remove from `cardre/_evidence/kinds.py`:**
   - `WOE_APPLICATION_EVIDENCE = "apply_woe_evidence"  # compat alias` (line 33)
   - `SCORE_APPLICATION_EVIDENCE = "apply_model_evidence"  # compat alias` (line 35)
   - `RUN_MANIFEST = "run_manifest"` (line 38)
   - `class LegacyEvidenceCompatibilityError(EvidenceSchemaError):` and its docstring (lines 66-67)

2. **Remove from `cardre/_evidence/schemas.py`:**
   - `SCHEMA_WOE_APPLICATION_EVIDENCE = SCHEMA_APPLY_WOE_EVIDENCE  # compat alias` (line 28)
   - `SCHEMA_SCORE_APPLICATION_EVIDENCE = SCHEMA_APPLY_MODEL_EVIDENCE  # compat alias` (line 30)
   - `SCHEMA_RUN_MANIFEST = "cardre.run_manifest.v1"` (line 33)

3. **Remove the `RUN_MANIFEST` profile** from `cardre/_evidence/profiles.py` (lines 223-228) and its import of `SCHEMA_RUN_MANIFEST` if present.

4. **Remove the `RUN_MANIFEST` adapter** from `cardre/_evidence/adapters/__init__.py` (lines 158-161) and the `RunManifestEvidence` import at line 45.

5. **Remove `RunManifestEvidence` class** from `cardre/_evidence/models/manifest.py` (lines 53-87) and its export from `cardre/_evidence/models/__init__.py` (lines 40, 104).

6. **Update callers** of the removed compat-alias constants to use canonical names:
   - `cardre/modeling/adapters.py:26`: `SCHEMA_SCORE_APPLICATION_EVIDENCE` → `SCHEMA_APPLY_MODEL_EVIDENCE` (and lines 71, 84).
   - `cardre/nodes/validate/apply.py:12`: `SCHEMA_WOE_APPLICATION_EVIDENCE` → `SCHEMA_APPLY_WOE_EVIDENCE` (and lines 207, 223).
   - `cardre/nodes/validate/analyse.py:17`: `SCHEMA_SCORE_APPLICATION_EVIDENCE` → `SCHEMA_APPLY_MODEL_EVIDENCE` (and line 211).

   Verify:
   ```bash
   rg -n "WOE_APPLICATION_EVIDENCE|SCORE_APPLICATION_EVIDENCE|SCHEMA_WOE_APPLICATION|SCHEMA_SCORE_APPLICATION|RUN_MANIFEST|RunManifestEvidence|LegacyEvidenceCompatibilityError" cardre/ tests/
   # The only acceptable matches: the test file you update in step 7.
   ```

7. **Update `tests/test_evidence_adapters.py`**: remove the `RUN_MANIFEST` adapter test at line 234 (the tuple referencing `EvidenceKind.RUN_MANIFEST`). If other tests reference the removed kinds/aliases, update or remove them.

8. **Update the banned-import guard test** (`tests/test_evidence_adapters.py`, near line 66) to also assert the removed identifiers do not appear in `cardre/` source:
    ```python
    def test_no_compat_aliases_in_source():
        import subprocess
        banned = [
            "WOE_APPLICATION_EVIDENCE", "SCORE_APPLICATION_EVIDENCE",
            "SCHEMA_WOE_APPLICATION_EVIDENCE", "SCHEMA_SCORE_APPLICATION_EVIDENCE",
            "LegacyEvidenceCompatibilityError", "SCHEMA_RUN_MANIFEST",
            "EvidenceKind.RUN_MANIFEST", "RunManifestEvidence",
        ]
        result = subprocess.run(
            ["rg", "-n", "|".join(banned), "cardre/"],
            capture_output=True, text=True,
        )
        assert result.returncode != 0, f"Banned compat identifiers still in source:\n{result.stdout}"
    ```

### Verification
```bash
. .venv/bin/activate
rg -n "WOE_APPLICATION_EVIDENCE|SCORE_APPLICATION_EVIDENCE|SCHEMA_WOE_APPLICATION|SCHEMA_SCORE_APPLICATION|RUN_MANIFEST|RunManifestEvidence|LegacyEvidenceCompatibilityError" cardre/
# Zero matches in cardre/.
ruff check --fix
pytest tests/test_evidence_adapters.py tests/test_evidence_reader.py tests/test_evidence_profiles.py -q
make preflight
scripts/pr-gate.sh
```

---

## PR 3 — Canonical score column, score-direction, and `points_to_double_odds`

**Goal:** One canonical score column (`score`); one canonical score-direction representation (`score_direction` string); one canonical score-scaling param name (`points_to_double_odds`).

**Depends on:** PR 2.

### Files to read first
- `cardre/modeling/adapters.py` — `cardre_scaled_score` writes (:196-197, 301-302); `higher_score_is_lower_risk` bool reads (:139, 296).
- `cardre/nodes/build/models.py` — ScoreScalingNode writes `points_to_double_odds` (:466) and `higher_score_is_lower_risk` (:469); summary report (:558).
- `cardre/nodes/build/freeze.py` — `:124`.
- `cardre/nodes/build/scoring_export.py` — many references to `higher_score_is_lower_risk` and `points_to_double_odds`.
- `cardre/_evidence/models/model.py` — `ScoreScaling.from_json` dual-accept (:152); `higher_score_is_lower_risk` property dual-accept (:178-184).
- `cardre/reporting/schema.py` — `ScoreScalingInfo.pdo` (:201), `score_direction` (:204).
- `cardre/reporting/sections/score_scaling.py` — `pdo=scaling.pdo` (:33).
- `tests/fixtures/golden_report_bundle.json` — `pdo` (:1813), `higher_score_is_lower_risk` occurrences.
- `tests/test_scoring_export_parity.py:122` — drops both `score` and `cardre_scaled_score`.

### Code instructions

1. **Remove `cardre_scaled_score` column** from `cardre/modeling/adapters.py`:
   - Line 196: delete `add_exprs.append(score_expr.alias("cardre_scaled_score"))`.
   - Line 197: change `output_cols.extend(["score", "cardre_scaled_score"])` → `output_cols.append("score")`.
   - Line 301: delete `add_exprs.append(score_series.alias("cardre_scaled_score"))`.
   - Line 302: change `output_cols.extend(["score", "cardre_scaled_score"])` → `output_cols.append("score")`.

2. **Unify score direction to `score_direction` (string)** in the scorecard artifact writers:
   - `cardre/nodes/build/models.py:469`: replace `"higher_score_is_lower_risk": higher_is_lower_risk,` with `"score_direction": "higher_is_lower_risk" if higher_is_lower_risk else "higher_is_better",`.
   - `cardre/nodes/build/models.py:428`: keep the node param `higher_score_is_lower_risk` (bool) — it's the UI form control. Translate to `score_direction` only when writing the artifact.
   - `cardre/nodes/build/models.py:560`: the build summary report — replace `"higher_score_is_lower_risk": scorecard.higher_score_is_lower_risk,` with `"score_direction": scorecard.score_direction,` (the reader now exposes `score_direction`).
   - `cardre/nodes/build/freeze.py:124`: replace `"higher_score_is_lower_risk": higher_is_lower_risk,` with `"score_direction": "higher_is_lower_risk" if higher_is_lower_risk else "higher_is_better",`.
   - `cardre/nodes/build/scoring_export.py`: replace all `"higher_score_is_lower_risk": ...` writes with `"score_direction": "higher_is_lower_risk" if ... else "higher_is_better",` (lines 72, 163, 318, 339, 514, 535). Replace all reads `scorecard_dict.get("higher_score_is_lower_risk", True)` (lines 140, 372) with `scorecard_dict.get("score_direction") == "higher_is_lower_risk"` (default to True — i.e., `scorecard_dict.get("score_direction", "higher_is_lower_risk") == "higher_is_lower_risk"`).
   - `cardre/modeling/adapters.py:139,296`: replace `scorecard_parsed.get("higher_score_is_lower_risk", True)` with `scorecard_parsed.get("score_direction", "higher_is_lower_risk") == "higher_is_lower_risk"`.

3. **Canonicalize `ScoreScaling` reader** in `cardre/_evidence/models/model.py`:
   - Line 137: rename field `pdo: int = 20` → `points_to_double_odds: int = 20`.
   - Line 152: replace `pdo = data.get("pdo", data.get("points_to_double_odds", 20))` with `points_to_double_odds = data.get("points_to_double_odds", 20)`. **Reject** if `pdo` is the only key present? No — just read only `points_to_double_odds`. (Strict: raise if `pdo` present? Keep simple: ignore `pdo`, read only `points_to_double_odds`.)
   - Line 163: `pdo=pdo` → `points_to_double_odds=points_to_double_odds`.
   - Lines 178-184: replace the `higher_score_is_lower_risk` property with a `score_direction`-only read:
     ```python
     @property
     def higher_score_is_lower_risk(self) -> bool:
         return self.score_direction == "higher_is_lower_risk"
     ```
     Keep the `score_direction` field as-is (line 140: `score_direction: str = "higher_is_better"`). In `from_json`, set `score_direction = data.get("score_direction", "higher_is_lower_risk")` (canonical default). Remove the `_raw`-based dual read.

4. **Canonicalize `points_to_double_odds` in report bundle**:
   - `cardre/reporting/schema.py:201`: rename `pdo: int = 20` → `points_to_double_odds: int = 20`.
   - `cardre/reporting/sections/score_scaling.py:33`: `pdo=scaling.pdo` → `points_to_double_odds=scaling.points_to_double_odds`.

5. **Update `tests/fixtures/golden_report_bundle.json`**: rename `"pdo": 20` → `"points_to_double_odds": 20`; rename every `"higher_score_is_lower_risk": true/false` in the scorecard payload → `"score_direction": "higher_is_lower_risk"` (or `"higher_is_better"`).

6. **Update `tests/test_scoring_export_parity.py:122`**: change the drop list from `["score", "cardre_scaled_score", "predicted_bad_probability", ...]` to `["score", "predicted_bad_probability", ...]`.

7. **Update any score-scaling tests** that assert `pdo` or `higher_score_is_lower_risk`:
   - `tests/test_score_scaling_known_input.py`
   - `tests/test_score_scaling_errors.py`
   - `tests/test_freeze_scorecard_bundle.py`
   - `tests/test_build_summary_node.py` / `test_build_summary_report.py`
   - `tests/test_reporting.py`
   - Search: `rg -n "pdo|higher_score_is_lower_risk|cardre_scaled_score" tests/` and update each assertion to the canonical name.

8. **Add guard tests** in `tests/test_canonical_contract.py`:
    ```python
    def test_score_scaling_rejects_pdo_key():
        from cardre._evidence.models.model import ScoreScaling
        with pytest.raises((KeyError, TypeError, ValueError)):
            # Only points_to_double_odds is read; pdo alone should not populate it
            s = ScoreScaling.from_json({"pdo": 20, "base_score": 600})
            assert s.points_to_double_odds != 20  # must not silently accept pdo

    def test_scored_dataset_single_score_column():
        # Build a tiny scored dataset via apply_logistic and assert columns
        # Contains "score", does not contain "cardre_scaled_score".
        ...
    ```

### Verification
```bash
. .venv/bin/activate
rg -n "cardre_scaled_score" cardre/ tests/
# Zero matches (except maybe historical docs — PR6 handles those).
rg -n "\"pdo\"" cardre/ tests/
# Zero matches in non-doc files.
rg -n "higher_score_is_lower_risk" cardre/
# Only the node param definition (UI form) may remain; all artifact writers/readers use score_direction.
ruff check --fix
pytest tests/test_score_scaling_known_input.py tests/test_score_scaling_errors.py \
       tests/test_freeze_scorecard_bundle.py tests/test_scoring_export_parity.py \
       tests/test_build_summary_node.py tests/test_reporting.py tests/test_canonical_contract.py -q
make preflight
scripts/pr-gate.sh
```

---

## PR 4 — Remove `_raw` escape hatches and dual-key parsing in evidence models

**Goal:** Every evidence model parses only the canonical structure; no `_raw` fields, no `data.get(a, data.get(b))` fallbacks, no inferred required fields. One model-artifact parser.

**Depends on:** PR 3 (so `score_direction`/`points_to_double_odds` are canonical before tightening the reader).

### Files to read first
- `cardre/modeling/schema.py` — `ModelArtifactV1` (:190-317), `_raw` (:222), `_raw`-backed properties (:228-265).
- `cardre/_evidence/models/model.py` — `ModelArtifact` (:27-131) with `_raw`, dual-structure `coefficients` parsing (:54-77), inferred `features`/`model_family` (:76-82), `_raw`-backed properties (:110-130); `ScoreScaling._raw` (:144), `_raw`-backed properties (:180-209).
- `cardre/_evidence/models/validation.py` — `ValidationMetrics._raw` (:26), dual-key parsing (:32, 35, 52, 83, 89); `CutoffAnalysis._raw` (:78).
- `cardre/_evidence/models/apply.py` — `ScoredDataset._raw` (:64).
- `cardre/_evidence/models/manifest.py:71` — `ReportBundleEvidence.from_json` (already strict — keep; verify).
- `cardre/nodes/validate/analyse.py:468-471,907` — dual-key writer.

### Code instructions

1. **Tighten the validation-metrics writer** in `cardre/nodes/validate/analyse.py`:
   - Line 468: `"roles": roles_metrics,` — keep.
   - Line 469: `"metrics": roles_metrics,` — delete.
   - Line 470: `"stability": stability,` — keep.
   - Line 471: `"psi": stability,` — delete.
   - Line 907: `"cutoff_tables": cutoff_tables,` — keep. Verify no `"tables"` duplicate is written (search the file). Cutoff row uses `score_cutoff` (line 897) — already canonical; keep.

2. **Tighten `ValidationMetrics.from_json`** in `cardre/_evidence/models/validation.py`:
   - Line 32: `raw_metrics = data.get("roles", data.get("metrics", {}))` → `raw_metrics = data.get("roles", {})`. **Do not** fall back to top-level `train`/`test`/`oot` keys (lines 34-36) — delete that fallback block.
   - Line 52: `raw_psi = data.get("stability", data.get("psi", {}))` → `raw_psi = data.get("stability", {})`.
   - Remove the `_raw` field (line 26) and its assignment in the constructor (line 62).
   - `CutoffAnalysis.from_json` (line 83): `raw_tables = data.get("cutoff_tables", data.get("tables", {}))` → `raw_tables = data.get("cutoff_tables", {})`. Line 89: `r.get("score_cutoff", r.get("score", 0))` → `r.get("score_cutoff", 0)`. Remove `_raw` field (line 78).

3. **Tighten `ModelArtifact.from_json`** in `cardre/_evidence/models/model.py`:
   - Lines 54-77: accept **only** the dict form of `coefficients`. If `isinstance(raw_coeffs, list)` → raise `EvidenceParseError` (or `TypeError`). Remove the list-of-dicts branch (lines 63-74).
   - Lines 76-82: `features` and `model_family` are **required** — if missing, raise `EvidenceParseError` instead of inferring.
   - Remove the `_raw` field (line 37) and all `_raw`-backed properties (lines 110-130): `feature_contract`, `source_variables`, `calibration`, `has_explicit_intercept`, `to_dict`. If consumers need these, promote them to explicit typed fields populated in `from_json`, or read them via the canonical `ModelArtifactV1` (see step 5).
   - Line 91: `_raw=data` → remove.
   - `to_dict()` (line 129): rebuild from typed fields instead of `_raw`.

4. **Tighten `ScoreScaling`** in `cardre/_evidence/models/model.py` (PR3 already did the `points_to_double_odds`/`score_direction` parts; here remove the remaining `_raw` field and `_raw`-backed properties):
   - Remove `_raw` field (line 144) and assignment (line 174).
   - Remove `_raw`-backed properties: `base_odds_text` (lines 186-189), `intercept` (lines 191-193), `has_explicit_intercept` (lines 195-197), `base_points` (lines 199-201), `target_column` (lines 203-205), `attributes` (lines 207-209). Promote to explicit typed fields populated in `from_json`:
     ```python
     @dataclass(frozen=True)
     class ScoreScaling:
         base_score: int = 600
         base_odds: float = 50.0
         points_to_double_odds: int = 20
         factor: float = 0.0
         offset: float = 0.0
         score_direction: str = "higher_is_lower_risk"
         rounding: str = "nearest_integer"
         min_score: int = 0
         max_score: int = 0
         source_artifact_id: str = ""
         base_odds_text: str = "50:1"
         intercept: float = 0.0
         has_explicit_intercept: bool = False
         base_points: float | int | None = None
         target_column: str = ""
         attributes: list = field(default_factory=list)
     ```
     Populate all in `from_json` from explicit keys (no `_raw`).
   - Remove the `factor`/`offset` recompute fallback (lines 154-159): require `factor` and `offset` in the payload, OR keep the recompute but only from the canonical `points_to_double_odds`/`base_score`/`base_odds` (no dual keys). **Decision: keep the recompute** (the scorecard writer emits `factor`/`offset` already at `models.py:467-468`; but if a consumer supplies only the three base params, recompute is convenient — keep it as a derived calculation, not a compat fallback).

5. **Collapse the two model-artifact classes**: decide whether `ModelArtifact` (evidence reader) delegates to `ModelArtifactV1` (writer) or replaces it. **Simplest:** make the evidence adapter's parse callable construct `ModelArtifactV1.from_dict` and return it; delete `ModelArtifact`. Update `cardre/_evidence/adapters/__init__.py` MODEL_ARTIFACT adapter parse lambda to `ModelArtifactV1.from_dict(read_json_payload(path))`. Update `cardre/_evidence/models/__init__.py` exports. Update any consumer that imported `ModelArtifact` (grep: `rg -n "from cardre._evidence.models.model import ModelArtifact"`).
   - If consumers used `ModelArtifact`-specific properties (`coefficients`, `coefficients_dict`, `ensemble_type`, etc.), map them to `ModelArtifactV1` properties. `ModelArtifactV1` already has `coefficients_dict`, `intercept`, `features`. Add an `ensemble_type`/`base_models`/`weights`/`voting`/`threshold` accessor if needed, or read from `model_payload`.

6. **Tighten `ModelArtifactV1`** in `cardre/modeling/schema.py`:
   - Remove the `_raw` field (line 222) and its assignment in `from_dict` (line 316).
   - Remove the `_raw`-backed properties `base_odds` (lines 248-257), `bad_class_label` (lines 260-261), `feature_strategy` (lines 264-265). If any consumer reads these, add explicit fields to the dataclass populated from explicit keys in `from_dict`. Grep first: `rg -n "\.base_odds|\.bad_class_label|\.feature_strategy" cardre/ tests/`.
   - Update the comment at line 220 ("Raw payload for backward compatibility") — delete it.

7. **Tighten `ScoredDataset`** in `cardre/_evidence/models/apply.py`: remove `_raw` (line 64); promote any `_raw`-backed accessors to explicit fields.

8. **Tighten `RunManifestEvidence`** — already removed in PR 2. Skip.

9. **Update tests**:
   - `tests/test_evidence_adapters.py` parity tests: any fixture that supplies list-form `coefficients` or legacy keys must be updated to the canonical dict form.
   - `tests/test_validation_metrics_node.py`, `tests/test_validation_failure_evidence.py`: update fixtures/payloads to canonical keys (`roles`, `stability`, `cutoff_tables`, `score_cutoff`).
   - `tests/test_model_apply_boundary.py`, `tests/test_logistic_regression_known_input.py`: update model-artifact fixtures to dict-form coefficients, required `features`/`model_family`.
   - `tests/test_golden_fixtures_roundtrip.py`: update golden fixtures if they carry list-form coefficients or `_raw`-dependent fields.

10. **Add guard tests** in `tests/test_canonical_contract.py`:
    ```python
    def test_model_artifact_rejects_list_coefficients():
        from cardre._evidence.models.model import ModelArtifact  # or ModelArtifactV1
        with pytest.raises((TypeError, ValueError, EvidenceParseError)):
            ModelArtifact.from_json({"coefficients": [{"variable_name": "x", "coefficient": 1.0}]})

    def test_validation_metrics_rejects_legacy_keys():
        from cardre._evidence.models.validation import ValidationMetrics
        with pytest.raises((KeyError, TypeError, EvidenceParseError)):
            ValidationMetrics.from_json({"metrics": {"train": {}}})  # legacy 'metrics' key
    ```

### Verification
```bash
. .venv/bin/activate
rg -n "_raw" cardre/_evidence/models/ cardre/modeling/schema.py
# Zero matches (no _raw fields remain in evidence/modeling models).
rg -n "data\.get\(\"[a-z_]+\", data\.get\(" cardre/
# Zero dual-key fallbacks.
ruff check --fix
pytest tests/test_evidence_adapters.py tests/test_validation_metrics_node.py \
       tests/test_validation_failure_evidence.py tests/test_model_apply_boundary.py \
       tests/test_logistic_regression_known_input.py tests/test_golden_fixtures_roundtrip.py \
       tests/test_canonical_contract.py -q
make preflight
scripts/pr-gate.sh
```

---

## PR 5 — Canonical run-manifest + collapse DB schema to baseline 101

**Goal:** One run-manifest representation (`cardre.run_manifest.v1`), written once, registered once. One DB schema (101) with no migration runner.

**Depends on:** PR 4.

### Files to read first
- `cardre/execution/run_lifecycle.py` — `MANIFEST_VERSION` (:30), `build_manifest_payload` (:45-88), `write_manifest` (:91-137), `assert_run_audit_integrity` (:365-460).
- `cardre/reporting/schema.py` — `RunManifest` model (:429-447), `RunManifestStep` (:407-426).
- `cardre/reporting/collector.py` — `_read_canonical_manifest` (:129-195).
- `cardre/store/_schema_version.py` — `check_and_migrate` (:16-69), `_run_migrations` (:72-101).
- `cardre/store/schema.py` — `V2_STORE_SCHEMA_VERSION = 101` (:13), docstring (:1-9).
- `cardre/store/db.py` — `open()` (:66-92), stale docstring (:83-85).
- `tests/test_run_lifecycle.py`, `tests/test_run_audit_integrity.py`, `tests/test_store_repos.py` (migration test at :705-752).

### Code instructions

#### Part A — Canonical run manifest

1. **Replace `build_manifest_payload`** in `cardre/execution/run_lifecycle.py` with a canonical builder that emits the `RunManifest` shape. Use the `RunManifest` Pydantic model from `cardre/reporting/schema.py`:
   ```python
   MANIFEST_VERSION = "cardre.run_manifest.v1"  # was "1.0.0"

   def build_manifest_payload(*, run_id, plan_version_id, run_record, run_steps,
                              execution_mode, final_status, finished_at,
                              branch_id=None, target_step_id=None,
                              in_scope_step_ids=None, store=None) -> JsonDict:
       # Build RunManifestStep objects from run_steps, populate RunManifest,
       # compute manifest_hash over the dict with manifest_hash="",
       # return the full dict.
       ...
   ```
   Each `RunManifestStep` needs: `step_id`, `canonical_step_id`, `branch_id`, `node_type`, `node_version`, `category`, `status`, `action`, `is_carried_forward`, `started_at`, `finished_at`, `params`, `params_hash`, `parent_step_ids`, `input_artifact_ids`, `output_artifact_ids`, `warnings`, `errors`, `execution_fingerprint`. Pull these from the `RunStep` records and the plan-step lookup (the store has `plan_step_edges` for parent ids and `evidence_artifacts` for input/output artifact ids — query them).

2. **Register the manifest as the `run_manifest` artifact** in `write_manifest` (after writing the file at :135-137):
   ```python
   from cardre.domain.artifacts import ArtifactRef, json_logical_hash
   from cardre.artifacts import physical_hash, relative_path
   import uuid
   phys = physical_hash(manifest_path)
   logical = json_logical_hash(payload)  # payload already has manifest_hash set
   store.register_artifact(ArtifactRef(
       artifact_id=str(uuid.uuid4()),
       artifact_type="run_manifest",
       role="audit",
       path=relative_path(manifest_path, store.root),
       physical_hash=phys,
       logical_hash=logical,
       media_type="application/json",
       metadata={"schema_version": MANIFEST_VERSION, "run_id": run_id},
   ))
   ```
   Read `cardre/artifacts.py` and `cardre/store/artifact_repo.py` first to confirm `register_artifact` accepts a path under `exports/` (if it hard-codes `artifacts/`, fall back to writing a thin registered copy under `artifacts/` — but prefer the single-file approach; report any deviation).

3. **Update `assert_run_audit_integrity`** (:365-460) to validate the canonical shape: `manifest_version == "cardre.run_manifest.v1"`, non-empty `manifest_hash`, and the hash is self-consistent (recompute with `manifest_hash=""` and compare). The existing `run_id`/`plan_version_id`/`status` checks stay.

4. **`cardre/reporting/collector.py` `_read_canonical_manifest`** (:129-195): it already reads the canonical file and validates via `RunManifest.model_validate`. With the writer now emitting the canonical shape, this works unchanged. Verify only.

5. **Update tests**:
   - `tests/test_run_lifecycle.py`: assert `manifest_version == "cardre.run_manifest.v1"`, non-empty `manifest_hash`, `RunManifestStep` fields present. Remove any assertion on `"1.0.0"`.
   - `tests/test_run_audit_integrity.py`: update the manifest fixture at :55 to emit `"manifest_version": "cardre.run_manifest.v1"` and a valid `manifest_hash`.
   - `tests/test_manifest.py` (if present): assert exactly one `artifact_type == "run_manifest"` artifact is registered, pointing at `exports/manifest-{run_id}/manifest.json`.
   - Any test that filters `list_artifacts()` by `artifact_type == "run_manifest"`: now finds the canonical artifact. Update payload assertions.

#### Part B — Collapse DB schema

6. **Replace `check_and_migrate`** in `cardre/store/_schema_version.py` with a strict check:
   ```python
   def check_and_migrate(conn: sqlite3.Connection) -> None:
       conn.execute(
           "CREATE TABLE IF NOT EXISTS store_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)"
       )
       rows = conn.execute(
           "SELECT key, value FROM store_meta WHERE key IN ('schema_family', 'schema_version')"
       ).fetchall()
       meta = {row["key"]: row["value"] for row in rows}
       family = meta.get("schema_family")
       if family != V2_STORE_SCHEMA_FAMILY:
           raise SchemaVersionError(
               f"Store schema family {family!r} does not match app family "
               f"{V2_STORE_SCHEMA_FAMILY!r}. Recreate this project with the current app."
           )
       version_text = meta.get("schema_version")
       if version_text is None:
           raise SchemaVersionError(
               "Store schema version is missing. Recreate this project with the current app."
           )
       try:
           stored_version = int(version_text)
       except ValueError as exc:
           raise SchemaVersionError(
               f"Store schema version {version_text!r} is invalid. "
               "Recreate this project with the current app."
           ) from exc
       if stored_version != V2_STORE_SCHEMA_VERSION:
           raise SchemaVersionError(
               f"Store schema version {stored_version} is not supported by this app "
               f"(expected {V2_STORE_SCHEMA_VERSION}). Recreate this project with the current app."
           )
   ```
   Delete `_run_migrations` (lines 72-101) entirely.

7. **Update `cardre/store/schema.py` docstring** (lines 1-9): keep the version history as a historical comment but mark v100 obsolete:
   ```
   Current schema version: 101. Older versions are not supported; opening
   a v100 (or other) store raises SchemaVersionError. Recreate the project.
   ```

8. **Fix the stale docstring** in `cardre/store/db.py:83-85`: replace the "Hard-errors on schema_version != 100" comment with "Rejects stores whose schema version is not the current app version (see `_schema_version.check_and_migrate`)."

9. **Update tests**:
   - Delete `tests/test_store_repos.py::TestSchemaMigration::test_v100_store_migrated_to_v101_adds_active_step_id` (lines 705-752).
   - **Add** a test `test_v100_store_rejected`:
     ```python
     def test_v100_store_rejected(self, tmp_path):
         # Seed a v100 store, open it, assert SchemaVersionError raised.
         ...
         with pytest.raises(SchemaVersionError):
             ProjectStore.open(store_path)
     ```
   - `tests/test_store_rejects_v1_project.py` already asserts `STORE_VERSION_INCOMPATIBLE` — verify it still passes (it tests a different family mismatch).

10. **Add guard tests** in `tests/test_canonical_contract.py`:
    ```python
    def test_run_manifest_canonical_shape():
        # After a run, the manifest has manifest_version="cardre.run_manifest.v1",
        # non-empty manifest_hash, RunManifestStep fields.
        ...

    def test_db_rejects_v100_store():
        # Seed v100, open, assert SchemaVersionError.
        ...
    ```

### Verification
```bash
. .venv/bin/activate
rg -n "MANIFEST_VERSION|build_manifest_payload|_run_migrations" cardre/
# MANIFEST_VERSION exists once (= cardre.run_manifest.v1); _run_migrations gone.
pytest tests/test_run_lifecycle.py tests/test_run_audit_integrity.py \
       tests/test_store_repos.py tests/test_store_rejects_v1_project.py \
       tests/test_canonical_contract.py -q
make preflight
scripts/pr-gate.sh
```

---

## PR 6 — Mark legacy-compat-removal complete; supersede stale plans

**Goal:** Documentation only. No code changes. Mark obsolete plans as historical/superseded; correct false claims; explain the canonical architecture.

**Depends on:** PR 5.

### Files to read first
- `docs/adr/0003-no-legacy-plan-accommodation.md`
- `docs/plans/legacy-compat-removal-sprint.md` + `docs/plans/legacy-compat-removal/phase-*.md`
- `docs/plans/optbinning-first-class-path-plan.md`, `optbinning-technical-implementation.md`, `optbinning-integration-plan.md`
- `docs/plans/thermo-nuclear-quality-sprint/decision-log.md`
- `docs/plan-reviews/013-thermo-nuclear-codebase-review.md`
- `docs/architecture/domain-model.md`, `node-registry.md`, `artifact-evidence-access.md`, `storage-and-migrations.md`
- `docs/reference/node-catalogue.md`, `evidence-kinds.md`
- `CONTEXT.md`

### Code instructions

1. **`docs/plans/legacy-compat-removal-sprint.md`**: add a status banner at the top: *"**Status: Completed (2026-07-14).** All six phases resolved; see `docs/plans/legacy-compat-collapse.md` for the final canonical state."* Check off all Definition-of-Done items.

2. **`docs/plans/legacy-compat-removal/phase-3-manifest-consolidation.md`** and **`phase-6-deferred-facade-removal.md`**: add *"**Status: Completed via `docs/plans/legacy-compat-collapse.md` PR 5 / PR 1.**"* banners.

3. **`docs/plans/optbinning-first-class-path-plan.md`**: add a superseded banner: *"**Status: Superseded. The canonical automatic-binning node is `cardre.automatic_binning` (not `cardre.binning`). `AutoBinningFitNode` is deleted; `method` dispatch lives on `AutomaticBinningNode`. See `docs/plans/legacy-compat-collapse.md`.**"*

4. **`docs/plans/optbinning-technical-implementation.md`**: same superseded banner.

5. **`docs/plans/thermo-nuclear-quality-sprint/decision-log.md:62`**: correct the false claim that `FineClassingNode`/`AutoBinningFitNode` were "removed from registry by PR318" — add a correction note: *"Correction (2026-07-14): PR318 did not remove `FineClassingNode` from the registry; it remained registered as `cardre.fine_classing`. The actual collapse happened in `docs/plans/legacy-compat-collapse.md` PR 1: renamed to `cardre.automatic_binning`, `AutoBinningFitNode` deleted."*

6. **`docs/plan-reviews/013-thermo-nuclear-codebase-review.md:994`**: same correction.

7. **`docs/adr/0003-no-legacy-plan-accommodation.md`**: preserve the reasoning; add a consequence note: *"Update (2026-07-14): the canonical automatic-binning identity is `cardre.automatic_binning`. The `cardre.binning` rename described in this ADR was never executed; `cardre.automatic_binning` was chosen instead. `_LEGACY_NODE_TYPE_METHOD` (referenced at the old `cardre/store.py:32-35`) was deleted in the legacy-compat-removal sprint Phase 1."*

8. **`docs/architecture/domain-model.md`** and **`node-registry.md`**: update binning references to `cardre.automatic_binning` + `cardre.manual_binning`; add a paragraph explaining the two-stage binning workflow (automatic initial → manual refinement) and why WOE/IV is recalculated after manual binning.

9. **`docs/architecture/storage-and-migrations.md`**: update to reflect the single-baseline schema (no migration runner).

10. **`docs/reference/node-catalogue.md`**: update the `cardre.fine_classing` row → `cardre.automatic_binning` (description: "Automatic initial binning of variables (supports fine_classing and optbinning methods)").

11. **`docs/reference/evidence-kinds.md`**: remove `RUN_MANIFEST`, `WOE_APPLICATION_EVIDENCE`, `SCORE_APPLICATION_EVIDENCE` from the kind list.

12. **`CONTEXT.md`**: update the "Build Stream Workflow" section (lines 67-82) — step 5 "Auto fine classing" → "Automatic initial binning"; step 9 "Manual bin editing / coarse classing" stays; add a note that `cardre.automatic_binning` is the canonical identity.

13. **`docs/plans/ml-scorecard-methods-implementation-plan.md:183,278`**: remove `cardre_scaled_score` from the scored-columns list (single `score` column).

### Verification
```bash
rg -n "cardre\.fine_classing|AutoBinningFitNode|cardre\.binning|MANIFEST_VERSION.*1\.0\.0|_LEGACY_NODE_TYPE_METHOD" docs/
# Remaining matches must be in clearly-marked historical/superseded sections only.
python3 scripts/check_doc_references.py  # if this script validates doc references
make preflight  # includes check_doc_references
scripts/pr-gate.sh
```

---

## 6. Remaining compatibility code (justified, not removable)

- **`cardre/nodes/__init__.py` facade** — 41+ live import sites (registry, tests). A package-level convenience export, not a compat shim. The misleading docstring is rewritten in PR 1; the facade stays. Pure mechanical removal is a separate follow-up sprint.
- **Two-phase evidence matching** (`_base.py:match` — schema-version-first, then role/type/media) — the *current* canonical design, not a legacy fallback. `_legacy_match` is already gone. The Phase-2 role/type/media path is needed for artifacts like `SCORED_DATASET` (parquet, no JSON schema version). Keep.
- **`SCORED_DATASET` empty `schema_version`** — intentional: parquet datasets identified by role/type/media + required columns. Keep.
- **`raw_project_path` / `_raw_project_path_allowed`** — a dev-mode feature toggle (`CARDRE_ALLOW_RAW_PROJECT_PATH`), not legacy compat. Keep.
- **`cardre_score` / `predicted_bad_probability` / `raw_model_output` / `native_scorecard_points` / `decision_label`** — these are distinct scored-dataset columns with distinct meanings (not duplicates of `score`). Keep.

## 7. Intentional breaking changes

- Node identity `cardre.fine_classing` → `cardre.automatic_binning` (step id `fine-classing` → `automatic-binning`).
- Scorecard artifact field `higher_score_is_lower_risk` (bool) → `score_direction` (string).
- Scorecard/report field `pdo` → `points_to_double_odds`.
- Scored dataset column `cardre_scaled_score` removed.
- Validation artifact keys `metrics`, `psi`, `tables`, `score` (cutoff row key) removed in favour of `roles`, `stability`, `cutoff_tables`, `score_cutoff`.
- Model artifact list-of-dicts `coefficients` form no longer accepted (dict only).
- `EvidenceKind.RUN_MANIFEST`, `WOE_APPLICATION_EVIDENCE`, `SCORE_APPLICATION_EVIDENCE`, `LegacyEvidenceCompatibilityError`, `SCHEMA_*` compat aliases removed.
- `RunRepository.finish()` removed.
- `NodeType.is_internal`, `NodeType.is_deprecated` removed.
- DB v100 stores no longer auto-migrate; they fail with `SchemaVersionError`.
- Run manifest version `1.0.0` → `cardre.run_manifest.v1`; manifest now registered as artifact.
- `_raw` escape hatches removed from evidence/modeling models; unknown fields rejected where strictness is enforced.

## 8. Tests and checks to run (final, after all PRs)

```bash
. .venv/bin/activate
ruff check --fix
make preflight
```

Workflow exercise (canonical path end-to-end):
```bash
pytest tests/test_launch_pathway.py tests/test_scorecard_model.py \
       tests/test_frozen_scorecard_bundle.py tests/test_reporting_acceptance.py \
       tests/test_binning_node.py tests/test_api_manual_binning.py \
       tests/test_score_scaling_known_input.py tests/test_validation_metrics_node.py \
       tests/test_run_lifecycle.py tests/test_run_audit_integrity.py \
       tests/test_evidence_adapters.py tests/test_canonical_contract.py -q
```

## 9. Follow-up work genuinely outside scope

- **`cardre/nodes/__init__.py` facade mechanical removal** — 41+ import sites; a separate mechanical sprint (the original legacy-compat Phase 6, deliberately deferred).
- **Frontend editor forms** — the score-scaling form param `higher_score_is_lower_risk` (bool) stays as the UI control; only the artifact representation unifies to `score_direction`. If the frontend should also display `score_direction`, that's a separate UI change. No frontend `pdo`/`points_to_double_odds` references exist.
- **Deferred-tier evidence kinds** (`REPORT_BUNDLE`, `COMPARISON_ARTIFACT`, `FEATURE_SELECTION_EVIDENCE`, `RESAMPLING_EVIDENCE`, `HYPERPARAMETER_TUNING_EVIDENCE`, `ENSEMBLE_MODEL_ARTIFACT`, `EXPLAINABILITY_REPORT`, `FAIRNESS_REPORT`, `PROXY_RISK_REPORT`) — their writers may also lack `schema_version` or have permissive parsing. The task scope is the scorecard path; a separate writer-audit pass for deferred kinds is follow-up.
- **Adding `schema_version` to `SCORED_DATASET` writer** — currently relies on Phase-2 matching. If strict schema-version matching is desired for scored datasets, that's a separate change.