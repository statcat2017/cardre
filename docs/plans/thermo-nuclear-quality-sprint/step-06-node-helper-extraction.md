# PR6 — Extract node helpers and split god-functions

**Findings:** T4, N2, N3, N4, T5 (prep.py, analyse.py, clustering.py)
**Batch:** E (parallel with PR5, PR7)
**Depends on:** PR2 (needs typed properties for `require_model`)
**Behaviour change:** No

## Scope revisions (audit after PR0–PR5 merge)

This document was revised after auditing the codebase post-PR5. The
following items from the original plan were **dropped**:

- **N1 — `BinningNode` dispatcher collapse.** `FineClassingNode` is still
  a launch-tier node referenced in `workflows/scorecard.py`,
  `api/routes/node_types.py`, three test files, and the golden report
  bundle fixture. Converting it to a plain function and deleting the
  `cardre.fine_classing` registration is a hidden deprecation, not a
  "collapse." `AutoBinningFitNode` is already unregistered
  (`is_internal=True`). The `replace(context, validated_params=...)`
  pattern is ugly but working. **Do not touch.**
- **N5 — `to_payload()` protocol.** `_typed_definition_payload` is a
  14-line local helper used at exactly 2 call sites in one file
  (`feature_selection.py:281, 465`). It already works. Adding a
  `to_payload()` protocol across ~10 typed evidence classes to remove
  14 lines of glue is a larger change than the smell it fixes. The name
  `to_payload` is also already taken by `LifecycleBinDefinition` in a
  different domain, creating semantic confusion. **Do not add.**
- **N4 sub-item — `freeze.py` inline `"N:M"` parser.** Already done in
  PR3. `parse_base_odds` lives in `_logit_helpers.py` and is imported in
  `models.py`. `freeze.py` no longer has an inline parser. **Already
  complete.**

The following items were **folded in** from findings the original plan
missed (same kind of helper-extraction work):

- `ExecutionContext.train_artifact()` / `require_train_artifact()` — 19
  single-train-artifact sites with two inconsistent idioms (None vs
  StopIteration).
- `reader.read_dataframe(art)` — 43 parquet-read sites that all carry the
  same `# cardre-allow-artifact-read` pragma; a single helper owns the
  pragma.
- `ExecutionContext.find_frozen_bundle()` — 5 identical frozen-bundle
  comprehensions.
- `scoring_export.py` 38-line verbatim duplicate between
  `PythonScoringExportNode.run` and `SqlScoringExportNode.run`.
- `DummyApplyNode` removal — launch-tier node, zero callers, zero tests.
- Broader `except Exception` narrowing in `diagnostics.py` (3),
  `clustering.py` (3), `fairness.py:364`, `explainability.py:727`.

The German-credit fixture is **deleted entirely**, not relocated. Zero
tests and zero production plans reference it; 124 lines of fixture code
has no place in the production prep module or launch registry.

## Goal

Extract six canonical node helpers (`context.target_metadata()`,
`context.data_artifacts()`, `context.train_artifact()`,
`context.find_frozen_bundle()`, `reader.require_model()`,
`reader.read_dataframe()`), replace ~89 copy-pasted boilerplate sites,
fix the fairness copy-paste bug, and dedup a 38-line verbatim duplicate
in scoring export. Then split two god-functions, dedup the
explainability estimator-load, remove ensemble dead code, narrow broad
`except Exception` clauses, delete two dead launch-tier nodes, replace
magic strings with constants, and split `prep.py` into a `prep/`
package.

This is helper extraction + file splits, not a broad rewrite of node
logic.

## Tasks

### T4 — Promote canonical helpers

1. In `cardre/execution/context.py`, add:
   - `ROLES_DATA = ("train", "test", "oot")` constant
   - `data_artifacts(roles=ROLES_DATA) -> list[ArtifactRef]` (replaces
     10 comprehensions across 5 files)
   - `train_artifact() -> ArtifactRef | None` (replaces 19
     single-train-artifact lookups with two inconsistent idioms)
   - `require_train_artifact(node_type) -> ArtifactRef` (raises
     `ValueError(f"{node_type} requires a train artifact")` on None;
     replaces 12+ inline raises)
   - `find_frozen_bundle() -> ArtifactRef | None` (replaces 5 identical
     `next((a for a in context.input_artifacts if
     a.metadata.get("schema_version") == SCHEMA_FROZEN_SCORECARD_BUNDLE),
     None)` sites)
   - `target_metadata() -> TargetMeta | None` (replaces 6 inline
     `good_values if meta` copies; promote the existing
     `_extract_target_metadata` logic from `_training_utils.py`)

   ```python
   @dataclass(frozen=True)
   class TargetMeta:
       target_column: str
       good_values: frozenset[str]
       bad_values: frozenset[str]
       indeterminate_values: frozenset[str]
       all_known: frozenset[str]
   ```
   The helper must perform the `str(v)` cast so callers can use
   `meta.good_values` directly (eliminates the duplicated
   `{str(v) for v in meta.good_values}` pattern at 14+ sites).

2. In `cardre/_evidence/reader.py`, add:
   - `require_model(self, model_art, node_type) -> ModelArtifactV1` —
     `read_optional` + raise
     `ValueError(f"{node_type} requires model artifact {id!r} to be
     readable as MODEL_ARTIFACT evidence")` on parse failure or None.
     Replaces 11 six-line guards and eliminates the copy-paste-name drift
     that caused the fairness bug.
   - `read_dataframe(self, art) -> pl.DataFrame` — wraps
     `pl.read_parquet(store.artifact_path(art))` and owns the
     `# cardre-allow-artifact-read: dataset-frame-input` pragma.
     Replaces 43 inline reads. Callers no longer need the pragma comment.

### T4 — Migrate node files to the canonical helpers

For each of the 15+ node files, replace inline boilerplate with calls to
the new helpers. Key files:
- `nodes/fairness.py` — **fixes the copy-paste bug** at 322, 326, **339**
  where `ProxyRiskReportNode` raises `"fairness_report requires..."`
  (should be `proxy_risk_report`) and warns `"Could not read training
  data for fairness analysis"` (wrong node name).
- `nodes/validate/analyse.py`, `nodes/validate/apply.py`,
  `nodes/feature_selection.py`, `nodes/ensembles.py`,
  `nodes/calibrate.py`, `nodes/reject_inference.py`,
  `nodes/build/diagnostics.py`, `nodes/build/models.py`,
  `nodes/build/features.py`, `nodes/build/scoring_export.py`,
  `nodes/build/clustering.py`, `nodes/explainability.py`,
  `nodes/build/bins.py`, `nodes/build/auto_binning_fit.py`,
  `nodes/_training_utils.py`

### T4.4 — Selection-definition merge dedup

1. Extract `_merge_selection_definition(reader, def_art, selected_vars,
   key, selection)` in `cardre/nodes/feature_selection.py`.
2. Replace the two 16-line copies at 272-288 (filter) and 457-472
   (embedded).
3. Narrow `except (KeyError, TypeError, AttributeError)` to
   `except (EvidenceNotFoundError, EvidenceParseError)`.

### NEW — scoring_export verbatim duplicate

1. Extract `_resolve_frozen_scorecard_inputs(context, reader)` from
   `PythonScoringExportNode.run` (lines 278-315) and
   `SqlScoringExportNode.run` (lines 477-514). The two blocks are
   character-identical (38 lines): find frozen bundle → find
   bin_def/woe_table → find model → find scorecard candidates → call
   `_validate_bundle_components`.
2. Both `run` methods call the helper.

### N2 — `ModelExplainabilityNode` estimator-load dedup

1. Move `_load_estimator` (from `ensembles.py:32`) to
   `cardre/nodes/_estimator_io.py`.
2. Extract `_load_feature_matrix(store, data_art, features) -> np.ndarray`.
3. Fold the 4-line model-extraction block duplicated verbatim at
   `explainability.py:163-166` and `:601-604` into the `require_model`
   helper or a `_load_model_for_explainability(reader, model_art,
   node_type)` helper.
4. Update the 4 compute methods to call the shared helpers. Delete the 3
   copies of the 7-line estimator-deserialization block.
5. Narrow `except Exception: return None` at lines **338, 439, 496**, and
   the newly-found **727** (`except Exception: return issues`), to
   `except (ImportError, FileNotFoundError, joblib.InvalidJoblibException,
   OSError)` (and `return issues` for 727).

### NEW — Broader `except Exception` narrowing

PR6 originally only narrowed `explainability.py`. The same broad-catch
pattern exists in 4 other node files:

- `fairness.py:364` — `except Exception: pass` in
  `ProxyRiskReportNode.run` (correlation computation). Narrow to
  `except (ValueError, pl.ComputeError)`.
- `build/diagnostics.py:393` — `except Exception:` in
  `VifDiagnosticsNode.run`. Narrow to
  `except (EvidenceNotFoundError, EvidenceParseError, ValueError)`.
- `build/diagnostics.py:558` — `except Exception: hl_p_value = None`
  (Hosmer-Lemeshow). Narrow to
  `except (EvidenceNotFoundError, EvidenceParseError, ValueError)`.
- `build/diagnostics.py:567` — `except Exception: auc = None`. Narrow to
  `except (EvidenceNotFoundError, EvidenceParseError, ValueError)`.
- `build/clustering.py:546` — `except Exception: iv_table = None`.
  Narrow to `except (EvidenceNotFoundError, EvidenceParseError)`.
- `build/clustering.py:554` — `except Exception: iv_map = {}`. Narrow
  to `except (EvidenceNotFoundError, EvidenceParseError)`.
- `build/clustering.py:568` — `except Exception: bin_def = None;
  woe_table = None`. Narrow to
  `except (EvidenceNotFoundError, EvidenceParseError)`.

### T5 — God-function extraction

#### `ValidationMetricsNode.run()` (283 → ~80 lines)

File: `cardre/nodes/validate/analyse.py` (909 lines total, `run` at
191-472).

1. Extract `_RoleMetrics` dataclass + `_compute_role_metrics()` pure
   function + `_compute_psi_stability()` + `_evaluate_gates()`.
2. `run()` becomes: resolve inputs → loop over roles → compute PSI →
   evaluate gates → assemble payload → write.

#### `VariableClusteringNode.run()` (232 → ~50 lines)

File: `cardre/nodes/build/clustering.py` (747 lines total, `run` at
516-747).

1. Extract `_resolve_candidates()` + `_cluster_columns()`.
2. **Delete the dead `try/except ImportError` at lines 699-708** — numpy
   is a hard dependency (`pyproject.toml`); the branch is unreachable.
3. `run()` becomes: resolve candidates → build correlation → cluster →
   write.

### N3 — Ensemble dead-code removal

File: `cardre/nodes/ensembles.py`. `VotingEnsembleNode` and
`WeightedEnsembleNode` are registered as deferred-tier nodes but have
zero test coverage and zero production plan usage. Dead computation
(lines 220, 225, 442) discards results without assignment.

1. Delete `VotingEnsembleNode`/`WeightedEnsembleNode` from
   `cardre/nodes/registry.py` (deferred tier, lines 299-300) and
   `cardre/nodes/__init__.py` re-exports (lines 47-48, 152-153).
2. Delete the dead computation lines (results discarded, no assignment).
3. Delete `_optimize_weights` (500-iteration random Dirichlet grid
   search, lines 516-545).
4. Update `validate/apply.py:346` and `modeling/adapters.py:512` to drop
   ensemble family handling.
5. Update `docs/reference/node-catalogue.md`.

### N4 — Magic strings → constants

1. Replace inline `"cardre.model_artifact.v1"` (3 sites: `models.py:291`,
   `ensembles.py:232`, `ensembles.py:453`) and `"cardre.woe_iv_evidence.v1"`
   (2 sites: `build/features.py:351, 373`) with the imported constants
   `SCHEMA_MODEL_ARTIFACT` / `SCHEMA_WOE_IV_EVIDENCE` from
   `cardre/_evidence/schemas.py` (already imported in some files).
2. `freeze.py` inline `"N:M"` parser — **already done in PR3; skip.**
3. `cardre/columns.py` — **defer.** Column-name literals
   (`predicted_bad_probability`, `score`) are consistent across ~43
   sites with no naming drift or bugs. Pure preventive hardening; fold
   into a future PR that touches `analyse.py`/`adapters.py` for
   unrelated reasons.

### NEW — `DummyApplyNode` removal

`DummyApplyNode` (`validate/apply.py:369-418`) is a launch-tier node with
zero callers and zero tests.

1. Delete `DummyApplyNode` from `validate/apply.py`.
2. Remove from `registry.py` (lines 210, 248) and `__init__.py`
   re-exports (lines 94, 116).
3. Remove from `validate/__init__.py` (line 6, 10).
4. Update `docs/reference/node-catalogue.md`.

### German-credit fixture — DELETE (not relocate)

`ImportGermanCreditNode` (`prep.py:54-177`, 124 lines) and
`GERMAN_CREDIT_COLUMNS` (`prep.py:29`) are launch-tier fixture code with
zero test references and zero production plan references.

1. Delete `ImportGermanCreditNode` + `GERMAN_CREDIT_COLUMNS` from
   `prep.py`.
2. Remove from `registry.py` launch tier (lines 200, 224) and
   `nodes/__init__.py` re-exports (lines 71, 76, 100, 126).
3. Update `docs/reference/node-catalogue.md`.
4. (No test changes needed — zero references.)

### T5 (prep.py) — Split into `prep/` package

After German-credit deletion, `prep.py` is ~1075 lines with 8 decoupled
classes (no shared private helpers; only `_DTYPE_MAP` is shared).

1. Create `cardre/nodes/prep/` package:
   - `prep/__init__.py` — re-exports for back-compat + shared `_DTYPE_MAP`
   - `prep/import.py` — `ImportTabularDatasetNode`
   - `prep/profile.py` — `ProfileDatasetNode` (move `_numeric_stats` to
     `_dataset_quality.py`)
   - `prep/split.py` — `SplitTrainTestOotNode`, `ValidateBinaryTargetNode`
   - `prep/metadata.py` — `DefineModellingMetadataNode`,
     `DevelopmentSampleDefinitionNode`
   - `prep/treatment.py` — `ApplyExclusionsNode`,
     `ExplicitMissingOutlierTreatmentNode`
2. Each file <300 lines.
3. Update `cardre/nodes/__init__.py` to re-export from `prep/`.
4. Delete `cardre/nodes/prep.py`.

## Acceptance criteria

- [ ] `context.target_metadata()`, `reader.require_model()`,
  `context.data_artifacts()`, `context.train_artifact()`,
  `context.require_train_artifact()`, `context.find_frozen_bundle()`,
  `reader.read_dataframe()` exist and are used at all target sites.
- [ ] `rg 'meta.good_values if meta' cardre/nodes --type py` returns 0.
- [ ] `rg 'readable as MODEL_ARTIFACT' cardre/nodes --type py` returns 0
  (replaced by `require_model`).
- [ ] `rg 'for a in context.input_artifacts if a.role in' cardre/nodes
  --type py` returns 0.
- [ ] `rg 'next\(\(a for a in context.input_artifacts if a.role ==
  "train"' cardre/nodes --type py` returns 0 (replaced by
  `train_artifact`/`require_train_artifact`).
- [ ] `rg 'pl\.read_parquet\(store\.artifact_path' cardre/nodes --type
  py` returns 0 (all go through `read_dataframe`).
- [ ] `rg 'schema_version.*SCHEMA_FROZEN_SCORECARD_BUNDLE' cardre/nodes
  --type py` returns 0 (replaced by `find_frozen_bundle`).
- [ ] `cardre/nodes/fairness.py` error messages reference
  `proxy_risk_report`, not `"fairness_report"` or `"fairness analysis"`.
- [ ] `rg '_typed_definition_payload' cardre --type py` — kept as local
  helper in `feature_selection.py`; not promoted to a protocol.
- [ ] `rg '"cardre.model_artifact.v1"|"cardre.woe_iv_evidence.v1"'
  cardre/nodes --type py` returns 0 (only constants).
- [ ] `ValidationMetricsNode.run` < 100 lines.
- [ ] `VariableClusteringNode.run` < 80 lines.
- [ ] `rg 'except Exception:\s*$' cardre/nodes/explainability.py
  cardre/nodes/fairness.py cardre/nodes/build/diagnostics.py
  cardre/nodes/build/clustering.py` returns 0.
- [ ] `rg 'VotingEnsembleNode|WeightedEnsembleNode'
  cardre/nodes/registry.py` returns 0.
- [ ] `rg 'DummyApplyNode|cardre.dummy_apply' cardre/nodes/registry.py
  cardre/nodes/__init__.py` returns 0.
- [ ] `rg 'ImportGermanCreditNode|GERMAN_CREDIT_COLUMNS' cardre/nodes`
  returns 0.
- [ ] `cardre/nodes/prep.py` does not exist; `cardre/nodes/prep/`
  package exists with 6 files.
- [ ] `wc -l cardre/nodes/prep/*.py` — each <300 lines.
- [ ] `ruff check` clean; `pytest tests/ -q` green.
- [ ] Golden report bundle diff passes.

## Do not

- Do not touch `reporting/collector.py` (PR5, done).
- Do not touch `readiness/check.py` (PR5, done).
- Do not touch services/execution (PR8).
- Do not collapse `BinningNode`/`FineClassingNode` (N1 — `FineClassingNode`
  is a live launch-tier node referenced in workflows, API, tests, and
  the golden fixture; "collapse" is a hidden deprecation).
- Do not add `to_payload()` protocol to typed evidence classes (N5 —
  14-line local helper with 2 call sites does not justify a cross-cutting
  protocol).
- Do not create `cardre/columns.py` (defer — no naming drift to fix).
- Do not relocate `ImportGermanCreditNode` — delete it (zero references).