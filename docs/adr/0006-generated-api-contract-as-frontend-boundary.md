# Generated API Contract As Frontend Boundary

## Status

Proposed

## Context

Cardre generates OpenAPI types from its FastAPI backend (`frontend/src/api/schema.d.ts`), but the frontend API client (`frontend/src/api/client.ts`) is still mostly handwritten. This creates a weak architectural boundary with several concrete problems:

1. **Handwritten request/response shapes can drift from the backend.** The client manually strings URL paths, query parameters, and several inline body shapes. When the backend changes a route path, query parameter name, or response field, the generated schema updates but the handwritten client does not, and there is no type-level check connecting them.

2. **Inline request object types bypass the generated contract.** Methods like `createComparison`, `getReportReadiness`, and `generateReport` define their request bodies inline as anonymous object types. These are not derived from `paths[...]` in the generated schema, so a backend schema change can silently produce a mismatched frontend request.

3. **Backend DTOs expose fields that routes cannot populate.** `BranchListItem` declares `is_champion`, `latest_run_id`, `readiness`, `warning_count`, and `error_count`, but `list_branches` maps only raw branch fields and lets Pydantic defaults fill the rest. The frontend renders `(champion)` from `b.is_champion`, which will be falsely `false`. This is worse than omitting the fields: consumers see authoritative-looking default state.

4. **Run scope is stringly typed.** `RunRequest.run_scope` is an unrestricted `str`. The route only validates `to_node`; a `"branch"` request without `branch_id`, or any misspelled scope, falls into full-plan execution. Sync and async dispatch duplicate the same branching logic.

## Decision

1. **FastAPI/OpenAPI is the source of truth for frontend request/response types.** The generated `schema.d.ts` is the canonical type boundary. Frontend API calls must derive their request body, query parameter, and response types from `paths[...]` or equivalent generated operation types.

2. **Replace the handwritten client with a schema-derived client.** Use `openapi-fetch` or a small typed wrapper that maps each method to its generated operation type. Remove inline request object types from `client.ts`.

3. **Backend DTOs must not expose fields that routes cannot populate truthfully.** Every field in a response model must be populated by the route handler or explicitly documented as a default that consumers should not rely on. Fields that require enrichment (e.g., `is_champion`, `latest_run_id`, `readiness`) must either be populated or removed from the response model until the enrichment path exists.

4. **Run scope is a typed enum.** `RunRequest.run_scope` becomes a `Literal` or `Enum` with Pydantic validation requiring `branch_id` for branch scope and `target_step_id` for to-node scope. Sync and async dispatch are unified into a single `RunOrchestrator` service.

## Consequences

- **Easier:** frontend/backend contract drift is caught at type-check time, not at runtime.
- **Easier:** adding a new API endpoint requires only the backend route and schema regeneration; the frontend client method is a one-liner typed from the generated operation.
- **Easier:** run scope validation is in the Pydantic model, not scattered across the route handler.
- **Harder:** the initial migration requires replacing every method in `client.ts` with schema-derived calls. This is mechanical but touches ~30 methods.
- **Harder:** `openapi-fetch` or a similar tool must be added as a frontend dependency and integrated with the existing `ApiError` class.
- **Risk:** if the generated schema is too large or changes frequently, the frontend may resist regenerating. The CI check (`git diff --exit-code` after regeneration) already mitigates this.
