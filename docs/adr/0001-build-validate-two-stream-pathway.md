# Build/Validate Two-Stream Pathway

The scorecard pathway forks into two streams after the train/test/OOT split step. The build stream operates on `train` data only and fits all parameters (bin boundaries, WOE maps, model coefficients, scorecard points). The validate stream applies the fitted definitions to `test` and `oot` data and reports performance metrics. The streams converge only at comparison/export time. This enforces leakage prevention structurally: test/oot data never passes through a fitting node, because the executor enforces artifact role access per step type.

## Considered Options

- **Single linear pipeline**: simpler to implement, but leakage prevention relies on convention rather than structure. A bug or user error could accidentally fit on the full dataset. Harder to audit without explicit step-level role metadata.
- **Two explicit streams with role-enforced access**: more executor complexity and a more complex pathway template, but makes leakage prevention architecturally guaranteed rather than procedurally enforced.

## Consequences

- The pathway template is a forked structure, not a straight line. The GUI must render it as two visual streams or a split-path diagram.
- Every node must declare its input artifact roles (e.g., `fit_inputs=["train"]`, `apply_inputs=["test", "oot"]`). The executor validates these before each run.
- The split step is load-bearing: it produces three artifacts with immutable role metadata. If the split step changes, everything downstream is stale.
- New node types must declare their category (fit, refinement, selection, or apply) at registration time.
