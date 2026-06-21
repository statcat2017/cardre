# Launch Mode & Feature Flags

Cardre uses two environment variables to control which features are
available at runtime.

## `CARDRE_LAUNCH_MODE` (default: `1`)

Controls which node types are executable. In launch mode (the default),
nodes are divided into two tiers:

| Tier | Behaviour | Examples |
|------|-----------|---------|
| **launch** | Executable at plan-run time | Logistic regression, decision tree, binning, WOE, import, split, cutoff, validation metrics |
| **deferred** | Registered for schema display but raise `NodeNotAvailableForLaunch` on instantiation | Gradient boosting, XGBoost, LightGBM, CatBoost, random forest, ensembles, feature selection, hyperparameter tuning, SMOTE, reject inference, fairness, explainability, proxy risk |

Set `CARDRE_LAUNCH_MODE=0` to allow deferred-node instantiation
(useful for development or when those nodes are ready for production).

The `GET /node-types` endpoint exposes a `tier` field on each node
(`"launch"` or `"deferred"`) so the UI can display "coming soon"
indicators for deferred nodes.

## `CARDRE_GOVERNANCE` (default: `0`)

Controls the challenger-governance feature set (branch/comparison/champion
workflows). This is an enterprise feature not needed at launch.

| Mode | Behaviour |
|------|-----------|
| `0` (default) | Branch endpoints return 403; branch-related routers are not registered; branch-scope runs raise `GovernanceNotEnabled`. |
| `1` | Branch, comparison, and champion routers are registered. Branch runs execute normally. |

When governance is disabled:
- `POST /runs` with `run_scope: "branch"` returns **403**.
- Branch, comparison, and champion API routes return **404** (not registered).

When governance is enabled (`CARDRE_GOVERNANCE=1`):
- All governance routers are available.
- Governance-gated tests (marked `@pytest.mark.governance`) run.

## Health endpoint

The `GET /health` response includes three fields describing the current
mode:

| Field | Description |
|-------|-------------|
| `launch_node_count` | Number of launch-tier nodes registered |
| `deferred_node_count` | Number of deferred-tier nodes registered |
| `governance_enabled` | Whether challenger governance is active |
