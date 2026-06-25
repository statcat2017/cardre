# Node Registry

The `NodeRegistry` (`cardre/registry.py`) is the central registry of available node types. Nodes are registered by their `node_type` string identifier (e.g. `"cardre.import_dataset"`) and resolved at plan-execution time.

## Node Tiers

Nodes are divided into two tiers controlled by `CARDRE_LAUNCH_MODE`:

| Tier | Behaviour | Examples |
|------|-----------|---------|
| **launch** | Executable at plan-run time | Logistic regression, decision tree, binning, WOE, import, split, cutoff, validation metrics |
| **deferred** | Registered for schema display but raise `NodeNotAvailableForLaunch` on instantiation | Gradient boosting, XGBoost, LightGBM, CatBoost, random forest, ensembles, feature selection, hyperparameter tuning, SMOTE, reject inference, fairness, explainability, proxy risk |

## Registration

Nodes are registered via `NodeRegistry.with_defaults()` which calls `_register_launch_nodes()` and `_register_deferred_nodes()`. Deferred nodes are marked with the `@_deferred` decorator.

```python
reg = NodeRegistry.with_defaults()
reg.list_launch_nodes()   # returns launch-tier node type strings
reg.list_deferred_nodes() # returns deferred-tier node type strings
```

## Node Interface

Every node type implements the `NodeType` abstract base class (`cardre/audit.py`):

- `run(context: ExecutionContext) -> NodeOutput`: execute the node.
- `validate_params(params: dict) -> list[str]`: validate parameter values at run time.
- `parameter_schema() -> NodeParameterSchema`: return the parameter schema for UI rendering and plan-time validation.

## Node Categories

- **Fit nodes** (build stream only): consume `train`, produce definition artifacts.
- **Refinement nodes** (build stream only): consume a definition artifact and produce a refined definition.
- **Selection nodes** (build stream only): consume metrics/rankings and filter which variables proceed downstream.
- **Apply nodes** (validate stream only): consume definitions from build stream + test/oot data, produce predictions and metrics.
