# Feature Status

## Governance

| Area | Governance mode (`CARDRE_GOVERNANCE=1`) |
|------|------------------------------------------|
| Logistic scorecard | executable |
| Branch/champion/comparison APIs | off |

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `CARDRE_GOVERNANCE` | `0` | When enabled, branch/comparison/champion routers are registered. Branch runs execute normally. When disabled, branch endpoints return 403 and governance routers are not registered. |

## Node Catalogue

See `docs/reference/node-catalogue.md` for the full flat production node
catalogue. Every registered node is executable; there is no deferred or
launch/deferred tier.
