# PR6 — Extract node helpers and split god-functions

**Findings:** T4, N1, N2, N3, N4, N5, T5 (prep.py, analyse.py, clustering.py)
**Batch:** E (parallel with PR5, PR7)
**Depends on:** PR2 (needs typed properties for `require_model`)
**Behaviour change:** No

## Goal

Extract three canonical node helpers
(`context.target_metadata()`, `reader.require_model()`,
`context.data_artifacts()`), replace the 15+ copy-pasted boilerplate sites,
and fix the fairness copy-paste bug. Then split the god-functions
(`ValidationMetricsNode.run` 280 lines, `VariableClusteringNode.run` 230
lines), collapse the `BinningNode` dispatcher, dedup
`ModelExplainabilityNode`'s 4 compute methods, remove ensemble dead code,
split `prep.py` into a `prep/` package, and relocate the German-credit
fixture.

This is a high-return cleanup, but it's done as helper extraction + file
splits, not as a broad rewrite of node logic.

## Tasks

### T4 — Promote canonical helpers

1. In `cardre/execution/context.py`, add:
   - `ROLES_DATA = ("train", "test", "oot")` constant
   - `context.data_artifacts() -> list[ArtifactRef]` (replaces 6+
     comprehensions)
   - `context.target_metadata() -> TargetMeta | None` (replaces 15 inline
     copies; promote `_training_utils._extract_target_metadata` logic)
   ```python
   @dataclass(frozen=True)
   class TargetMeta:
       target_column: str
       good_values: frozenset[str]
       bad_values: frozenset[str]
       indeterminate_values: frozenset[str]
       all_known: frozenset[str]
   ```
2. In `cardre/_evidence/reader.py`, add:
   ```python
   def require_model(self, model_art, node_type) -> ModelArtifactV1:
       """Read+parse; raise ValueError(
       f"{node_type} requires model artifact {id!r} to be readable as
       MODEL_ARTIFACT evidence") on failure."""
   ```
   Replaces 11 six-line guards and eliminates the copy-paste-name drift
   that caused the fairness bug.

### T4 — Migrate node files to the canonical helpers

For each of the 13+ node files listed in review 013 (T4), replace the
inline boilerplate with calls to the new helpers. Key files:
- `nodes/fairness.py` — **fixes the copy-paste bug** at 322, 326, 487
  where `ProxyRiskReportNode`/`AlternativeDataManifestNode` raise
  "fairness_report requires..." with the wrong node name
- `nodes/validate/analyse.py`, `nodes/feature_selection.py`,
  `nodes/ensembles.py`, `nodes/calibrate.py`, `nodes/reject_inference.py`,
  `nodes/build/diagnostics.py`, `nodes/build/models.py`,
  `nodes/explainability.py`, `nodes/validate/apply.py`

### T4.4 — Selection-definition merge dedup

1. Extract `_merge_selection_definition(reader, def_art, selected_vars,
   key, selection)` in `cardre/nodes/feature_selection.py`.
2. Replace the two 16-line copies at 272-288 (filter) and 457-472 (embedded).
3. Narrow `except (KeyError, TypeError, AttributeError)` to
   `except (EvidenceNotFoundError, EvidenceParseError)`.

### N5 — Replace `_typed_definition_payload` with `to_payload()` protocol

1. Define `TypedEvidence.to_payload() -> dict` protocol.
2. Add `to_payload()` to the typed evidence classes.
3. Delete `_typed_definition_payload` (`feature_selection.py:26-39`).

### N4 — Magic strings → constants

1. Replace inline `"cardre.model_artifact.v1"` / `"cardre.woe_iv_evidence.v1"`
   literals with the imported constants (`SCHEMA_MODEL_ARTIFACT` /
   `SCHEMA_WOE_IV_EVIDENCE`).
2. Delete `freeze.py:114-119`'s inline `"N:M"` base-odds parser; call
   `parse_base_odds` from `_logit_helpers.py` (or use the typed
   `base_odds: float` property from PR2).
3. Create `cardre/columns.py` with canonical output column-name constants
   (`PREDICTED_BAD_PROBABILITY`, `SCORE`, etc.).

### T5 — God-function extraction

#### `ValidationMetricsNode.run()` (280 → ~80 lines)

1. Extract `_RoleMetrics` dataclass + `_compute_role_metrics()` pure
   function + `_compute_psi_stability()` + `_evaluate_gates()`.
2. `run()` becomes: resolve inputs → loop over roles → compute PSI →
   evaluate gates → assemble payload → write.

#### `VariableClusteringNode.run()` (230 → ~50 lines)

1. Extract `_resolve_candidates()` + `_cluster_columns()`.
2. Delete the impossible `try/except ImportError` catching numpy-missing.
3. `run()` becomes: resolve candidates → build correlation → cluster →
   write.

### N1 — `BinningNode` dispatcher collapse

1. Convert `FineClassingNode`/`AutoBinningFitNode` from `NodeType` subclasses
   to plain functions `_run_fine_classing(context) -> NodeOutput` /
   `_run_auto_binning_fit(context) -> NodeOutput`.
2. `BinningNode.run()` calls the function directly — no
   `replace(context, validated_params=...)` hack.
3. Delete `cardre.fine_classing` / `cardre.auto_binning_fit` registrations
   (keep `LEGACY_METHOD_MAP` for read migration). One node type, one
   schema.

### N2 — `ModelExplainabilityNode` estimator-load dedup

1. Move `_load_estimator` (from `ensembles.py:32`) to a shared location
   (`cardre/modeling/serialization.py` or `cardre/nodes/_estimator_io.py`).
2. Extract `_load_feature_matrix(store, data_art, features) -> np.ndarray`.
3. Update the 4 compute methods to call the shared helpers. Delete the 3
   copies of the 7-line estimator-deserialization block.
4. Narrow `except Exception: return None` to `except (ImportError,
   FileNotFoundError, joblib.InvalidJoblibException): return None`.

### N3 — Ensemble dead-code removal

1. **Decide: finish or remove.** Recommended: remove from registry until
   complete.
2. Delete `VotingEnsembleNode`/`WeightedEnsembleNode` from
   `cardre/nodes/registry.py` and `cardre/nodes/__init__.py` re-exports.
3. Delete the dead computation lines (results discarded, no assignment).
4. Delete `_optimize_weights` (500-iteration random Dirichlet grid
   search). If needed later, use `scipy.optimize`.

### T5 (prep.py) — Split into `prep/` package

1. Create `cardre/nodes/prep/` package:
   - `prep/__init__.py` (re-exports for back-compat)
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

### T3-fixture — German-credit fixture relocation

1. Move `ImportGermanCreditNode` + `GERMAN_CREDIT_COLUMNS` to
   `cardre/examples/import_german_credit.py` (or `tests/fixtures/`).
2. Demote to deferred tier or remove from the default registry.
3. Remove from `cardre/nodes/__init__.py`'s `__all__` and re-exports.
4. Update `cardre/nodes/registry.py`.
5. Update tests that used the German credit node (switch to
   `ImportTabularDatasetNode` with a test CSV, or register the fixture
   node explicitly in test setup).

## Acceptance criteria

- [ ] `context.target_metadata()`, `reader.require_model()`,
  `context.data_artifacts()` exist and are used by all 15+ node files.
- [ ] `rg 'meta.good_values if meta' cardre/nodes --type py` returns 0.
- [ ] `rg 'readable as MODEL_ARTIFACT' cardre/nodes --type py` returns 0
  (replaced by `require_model`).
- [ ] `rg 'for a in context.input_artifacts if a.role in' cardre/nodes
  --type py` returns 0.
- [ ] `cardre/nodes/fairness.py` error messages reference
  `cardre.proxy_risk_report` and `cardre.alternative_data_manifest`,
  not "fairness_report".
- [ ] `rg '_typed_definition_payload' cardre --type py` returns 0.
- [ ] `rg 'cardre.model_artifact.v1|cardre.woe_iv_evidence.v1'
  cardre/nodes --type py` returns 0 (only constants).
- [ ] `ValidationMetricsNode.run` < 100 lines.
- [ ] `VariableClusteringNode.run` < 80 lines.
- [ ] `rg 'replace\(context, validated_params' cardre/nodes/build/binning.py`
  returns 0.
- [ ] `rg 'except Exception:\s*$' cardre/nodes/explainability.py` returns 0.
- [ ] `rg 'np.mean\(prob_matrix|majority.astype\(float\)|prob_matrix @ weights'
  cardre/nodes/ensembles.py` returns 0.
- [ ] `cardre/nodes/prep.py` does not exist (split into `prep/`).
- [ ] `wc -l cardre/nodes/prep/*.py` — each <300 lines.
- [ ] `rg 'GERMAN_CREDIT_COLUMNS' cardre/nodes cardre/nodes/__init__.py
  cardre/nodes/registry.py` returns 0.
- [ ] `rg 'cardre.import_fixture_uci_german_credit'
  cardre/nodes/registry.py` shows deferred or absent.
- [ ] `ruff check` clean; `pytest tests/ -q` green.
- [ ] Golden report bundle diff passes.

## Do not

- Do not touch `reporting/collector.py` structure (that's PR5).
- Do not touch `readiness/check.py` (that's PR5).
- Do not touch services/execution (that's PR8).