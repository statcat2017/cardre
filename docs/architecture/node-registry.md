# Node Catalogue

The `NodeCatalogue` (`cardre/bootstrap/node_catalogue.py`) is the central registry of available node types. Nodes are registered by their `node_type` string identifier (e.g. `"cardre.import_dataset"`) and resolved at plan-execution time.

## Registration

The catalogue is built from the current production node classes:

```python
from cardre.bootstrap.node_catalogue import build_default_catalogue

cat = build_default_catalogue()
cat.list_types()          # returns all registered node type strings
cat.resolve("cardre.logistic_regression")  # node class
```

## Node Interface

Every node type implements the `NodeType` abstract base class (`cardre/nodes/contracts.py`) and declares exactly one explicit `NodeDefinition` (its single contract source):

- `__definition__: NodeDefinition`: the node's single typed contract — input/output `ArtifactContract` roles with kinds, media types and versioned schemas.
- `run(context: NodeContext) -> NodeResult`: execute the node.
- `validate_params(params: dict) -> list[str]`: validate parameter values at run time.
- `parameter_schema() -> NodeParameterSchema`: return the parameter schema for UI rendering and plan-time validation.

## Node Categories

- **Fit nodes** (build stream only): consume `train`, produce definition artifacts.
- **Refinement nodes** (build stream only): consume a definition artifact and produce a refined definition.
- **Selection nodes** (build stream only): consume metrics/rankings and filter which variables proceed downstream.
- **Apply nodes** (validate stream only): consume definitions from build stream + test/oot data, produce predictions and metrics.
