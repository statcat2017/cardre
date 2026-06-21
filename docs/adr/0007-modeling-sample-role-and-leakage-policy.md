# Modeling Sample-Role And Leakage Policy

## Status

Proposed

## Context

Cardre's build/validate two-stream pathway (ADR 0001) enforces leakage prevention structurally: fit/refinement/selection nodes cannot consume `test` or `oot` dataset artifacts. However, several modeling paths can still leak information or produce misleading results within the training stream:

1. **Feature selection can select the target.** `FeatureSelectionFilterNode` accepts a `target_column` parameter but does not resolve it from modelling metadata. If the parameter is omitted and the target is numeric, the target can be selected as a feature. Tests avoid this by always passing `target_column`, masking the leak.

2. **Weighted ensemble optimization uses training data for weight search.** `optimize_weights=True` computes base-model probabilities on the training artifact and grid-searches AUC against the same training target. This is an overfit path. The docstring claims "validation-optimized weights" but no validation artifact is used.

3. **Estimator kwargs are silently filtered.** `BaseClassifierNode` filters kwargs against `inspect.signature(__init__)` without handling `**kwargs`. For estimators whose constructors expose parameters through `**kwargs` (common in optional boosting libraries), valid params can be silently discarded, producing default models while artifacts report the requested params.

4. **Resampling promises synthetic-row flags but does not write them.** The metadata advertises `synthetic_row_column: "_is_synthetic_row"`, but the parquet output has no such column. Downstream governance cannot distinguish duplicated oversampled rows.

5. **Explainability dispatch misses optional boosting families.** Apply supports `xgboost`, `lightgbm`, and `catboost`, and their artifacts carry feature importance payloads, but explainability falls through to "none" because it duplicates model-family dispatch logic instead of reading from the artifact.

## Decision

1. **Target metadata is resolved from evidence, not optional params.** Every supervised node (feature selection, model fitting, ensemble, tuning) must resolve `target_column`, `good_values`, and `bad_values` from `EvidenceKind.MODELLING_METADATA`. The `target_column` param is removed or made a fallback override only. Nodes fail closed when metadata cannot be resolved.

2. **Weight optimization requires a validation or OOT sample.** `optimize_weights` in ensemble nodes must use an explicit validation/OOT artifact or out-of-fold predictions. Train-in-sample optimization is forbidden by default. If retained for experimental use, it requires an explicit `allow_train_optimization` parameter and the artifact must record the sample role used.

3. **Estimator kwargs are validated per family, not silently filtered.** The silent `inspect.signature` filter is removed. Each model family adapter validates its own supported parameters and raises on unknown kwargs. For estimators with `**kwargs`, the adapter explicitly lists supported params rather than passing everything through.

4. **Synthetic row flags are written.** Resampling nodes must write the `_is_synthetic_row` column to the output parquet artifact. Training feature resolution must exclude columns beginning with governance/internal prefixes.

5. **Explainability is driven from artifact metadata, not model-family dispatch.** The explainability node reads `interpretability` and `model_payload` from the model artifact generically, with a small registry for family-specific enrichments. It does not duplicate the model-family switch from the apply node.

## Consequences

- **Easier:** target leakage in feature selection is structurally prevented, not convention-dependent.
- **Easier:** ensemble optimization results are trustworthy because they use held-out data.
- **Easier:** estimator parameter errors are caught at validation time, not silently producing default models.
- **Easier:** explainability automatically supports new model families without code changes.
- **Harder:** existing projects that omit `target_column` from feature selection params will fail until they provide modelling metadata. This is a breaking change, but ADR 0003 permits it.
- **Harder:** the estimator adapter refactor touches every model family node. Each adapter must be reviewed for correct parameter support.
- **Risk:** requiring modelling metadata for all supervised nodes may break test fixtures that construct nodes without a full metadata artifact. Fixtures must be updated to provide metadata.
