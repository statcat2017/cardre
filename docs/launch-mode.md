# Feature Flags

Cardre uses one environment variable to control the challenger-governance
feature set.

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

There is no launch/deferred node tier and no `CARDRE_LAUNCH_MODE` flag. Every
registered node in the flat production catalogue is executable.

## Health endpoint

The `GET /health` response includes one field describing the current mode:

| Field | Description |
|-------|-------------|
| `governance_enabled` | Whether challenger governance is active |
