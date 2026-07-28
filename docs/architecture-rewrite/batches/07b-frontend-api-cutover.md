# Batch 07b — Frontend API Cutover

## Objective

Complete the frontend's cutover to the API surface merged in PR 7a. Project identity is path-only; `X-Project-Id` and `X-Project-Path` must not be sent, accepted, or retained as compatibility behavior.

## Scope

- Regenerate `frontend/src/api/openapi.json` and `schema.d.ts` from the merged API.
- Update `frontend/src/api/client.ts` so `api.forProject` uses only path parameters, exposes the committed endpoints including cancellation, and retains the established error transport behavior.
- Remove header handling from `cardre/api/dependencies.py` in the same PR.
- Update `useProjectWorkspace`, affected components, MSW fixtures, and focused frontend/API tests for the generated response shapes and terminal run statuses.
- Keep governance gating and the existing sidecar lifecycle unchanged.

## Prohibited

- No header fallback, optional header validation, dual request shape, or compatibility wrapper.
- No evidence, binning, persistence, or execution-context migration.
- No changes to the generated contract except those produced from the already merged API.

## Acceptance

- A repository search finds no `X-Project-Id`, `X-Project-Path`, or `projectHeaders` production usage.
- OpenAPI generation is clean and `test_error_code_sync.py` passes.
- The focused frontend API, workspace, and ProjectView tests pass, followed by frontend typecheck and build.

## Depends on

`origin/main` at merged PR 7a. The branch must not contain commits from `batch-07-cleanup`.
