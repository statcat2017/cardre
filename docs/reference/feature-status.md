# Feature Status

## Launch Mode & Governance

| Area | Launch default (`CARDRE_LAUNCH_MODE=1`) | Governance mode (`CARDRE_GOVERNANCE=1`) | Deferred |
|------|------------------------------------------|----------------------------------------|----------|
| Logistic scorecard | executable | executable | — |
| Decision tree challenger | executable | executable | — |
| Branch/champion/comparison APIs | off | on | — |
| Random forest/boosting/fairness/explainability | visible as schema/deferred | visible as schema/deferred | not executable |

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `CARDRE_LAUNCH_MODE` | `1` | When enabled, deferred nodes are visible as schemas but raise `NodeNotAvailableForLaunch` on instantiation. Set to `0` to enable all nodes. |
| `CARDRE_GOVERNANCE` | `0` | When enabled, branch/comparison/champion routers are registered. Branch runs execute normally. When disabled, branch endpoints return 403 and governance routers are not registered. |

## Node Tiers

See `docs/reference/node-catalogue.md` for the full list of launch and deferred nodes.
