# Phase Plan

| Phase | Name | Description |
|---|---|---|
| 1 | Domain kernel + relational store | Build the v2 domain package, hard-versioned store schema, and relational relationship tables. |
| 2 | Manual binning + mutation spike | Add the manual-binning domain/service and a minimal API/UI spike against real persisted draft state. |
| 3 | Execution layer | Port run orchestration, evidence resolution, staleness, and step persistence onto the v2 schema. |
| 4 | Project-scoped API + frontend types | Expand to the full API surface and generated frontend types with project-scoped routes. |
| 5 | Launch pathway + reporting | Port the launch scorecard path, reporting, exports, and node contracts. |
| 6 | Governance + cleanup | Port governance services and deferred nodes, then remove temporary scaffolding. |

Reference plan: `docs/plans/v2/cardre-v2-refactor-plan.md`.
