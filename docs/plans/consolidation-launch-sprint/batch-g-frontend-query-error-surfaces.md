# Batch G — Frontend Query and Error Surfaces

## Goal

Make frontend query string construction consistent (one `withQuery` helper,
no manual interpolation) and make API error surfaces consistently show code,
message, and request ID in the components that today drop or undersurface
them. This is frontend-only and can run in Wave 1 alongside Batch A.

## Context you must read first

- `frontend/src/api/client.ts:92` — `formatApiError` already exists. It
  includes `code`, `requestId`, `timeout`, and `message`.
- `frontend/src/utils/errors.ts:10` — `renderApiError` exists, returns a
  `RenderableError` with `code`, `message`, `context`, `diagnostics`. Used by
  `ParamsEditor`, `SchemaDrivenParamsEditor`, `RawJsonParamsFallback`,
  `ManualBinningEditDialog`.
- `frontend/src/hooks/useRunProgress.ts:116` — already uses `formatApiError`.
- `frontend/src/components/QueryState.tsx:22` — already uses `formatApiError`.
- `frontend/src/components/ProjectView.tsx:192` — already uses
  `formatApiError`.
- `frontend/src/components/ExportPanel.tsx:145` — already uses
  `formatApiError`.
- `frontend/src/components/ManualBinningEditor.tsx:43` — "Could not load
  editor state." with no API error code/request ID.
- `frontend/src/components/ArtifactBrowser.tsx:100` —
  `(error as Error)?.message` only.
- `frontend/src/components/ArtifactSummaryInline.tsx:12` — `useQuery` with no
  `isError` handling; returns `null` on missing data.
- `frontend/src/components/ArtifactPreviewPane.tsx:21` — `useQuery` with no
  explicit error rendering.
- `frontend/src/api/client.ts` query string construction:
  - `URLSearchParams`: `:250` (`getWorkflowGuidance`), `:269`
    (`getProjectArtifacts`), `:317` (`listBranches`), `:408`
    (`getModelRanking`).
  - Manual interpolation: `:245` (`getPlan`), `:297` (`getArtifactPreview`),
    `:300` (`getManualBinningEditorState`), `:326` (`getBranch`), `:370`
    (`getChampion`), `:405` (`getBranchMethodSummary`), `:419`
    (`getStepEvidence`), `:423` (`getRunEvidence`).
  - Correct: `:402` (`getNodeTypeSchema` uses `encodeURIComponent`),
    `:427` (`getReportServeUrl` uses `encodeURIComponent`).
- `frontend/src/test/server.ts` — MSW server; the only network seam.
- `docs/adr/0006-generated-api-contract-as-frontend-boundary.md` — no new
  handwritten TS types.
- `docs/plans/consolidation-launch-sprint/README.md` — cross-cutting rules,
  especially rule 6 (no new handwritten types) and rule 7 (MSW for tests).

## Prerequisite

none (frontend-only, runs in Wave 1).

## Changes

### 1. Add `withQuery`

New file `frontend/src/utils/query.ts`.

```ts
export function withQuery(
  path: string,
  params: Record<string, string | number | boolean | undefined | null>,
): string {
  const qs = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value === undefined || value === null || value === "") continue;
    qs.set(key, String(value));
  }
  const query = qs.toString();
  return query ? `${path}?${query}` : path;
}
```

Rules:

- Omits `undefined`, `null`, and empty-string values.
- Encodes spaces, slashes, `&`, `?` via `URLSearchParams.toString()`.
- Preserves numeric `limit`/`offset` by coercing to string.
- Returns the path unchanged when no params remain (no trailing `?`).

### 2. Replace all manual query string interpolation

In `frontend/src/api/client.ts`:

- `getPlan:244` → `withQuery(\`/plans/${id}\`, { project_id: projectId })`.
- `getArtifactPreview:296` →
  `withQuery(\`/artifacts/${id}/preview\`, { limit, offset })`.
- `getManualBinningEditorState:299` →
  `withQuery(\`/plans/${planId}/steps/${stepId}/editor-state\`, { project_id: projectId })`.
- `getBranch:325` → `withQuery(\`/branches/${branchId}\`, { project_id: projectId })`.
- `getChampion:369` →
  `withQuery(\`/plans/${planId}/champion\`, { project_id: projectId })`.
- `getBranchMethodSummary:404` →
  `withQuery(\`/branches/${branchId}/method-summary\`, { project_id: projectId })`.
- `getStepEvidence:419` →
  `withQuery(\`/runs/${runId}/steps/${stepId}/evidence\`, { project_id: projectId })`.
- `getRunEvidence:422` →
  `withQuery(\`/runs/${runId}/evidence\`, { project_id: projectId })`.
- `getModelRanking:407` →
  `withQuery(\`/branch-comparison-snapshots/${snapshotId}/model-ranking\`, { project_id: projectId, metric })`.

Leave `getReportServeUrl:427` as-is (it uses `encodeURIComponent` for a path
segment, which `withQuery` is not for). Leave `getNodeTypeSchema:402` as-is
(`encodeURIComponent` for a path segment).

The existing `URLSearchParams` callers (`getWorkflowGuidance`,
`getProjectArtifacts`, `listBranches`) can stay or switch to `withQuery` for
consistency — switch them so there is one pattern.

### 3. Add `ErrorNotice`

New file `frontend/src/components/ErrorNotice.tsx`.

```tsx
import { isApiError, formatApiError } from "../api/client";
import { theme } from "../styles";

interface Props {
  error: unknown;
  context?: string;
}

export function ErrorNotice({ error, context }: Props) {
  if (!error) return null;
  const msg = isApiError(error) ? formatApiError(error) : (error instanceof Error ? error.message : String(error));
  return (
    <div style={{ padding: "8px 12px", color: theme.redText, fontSize: 13 }}>
      {context && <div style={{ fontWeight: 600, marginBottom: 4 }}>{context}</div>}
      <div>{msg}</div>
    </div>
  );
}
```

This wraps the existing `formatApiError` so components get code, request ID,
and timeout in one place. It is deliberately tiny to stay under the 600-line
ceiling and to make the migration mechanical.

### 4. Migrate error surfaces

- `ManualBinningEditor.tsx:43` — replace "Could not load editor state." with
  `<ErrorNotice error={state.error} context="Could not load editor state" />`.
  The `useManualBinningState` hook must expose `error` (check the hook; if it
  only exposes `data`/`isLoading`, add `error` from the underlying `useQuery`).
- `ArtifactBrowser.tsx:100` — replace
  `(error as Error)?.message || "Unknown error"` with
  `<ErrorNotice error={error} context="Failed to load artifacts" />`.
- `ArtifactSummaryInline.tsx:12` — add `isError`/`error` from `useQuery` and
  render `<ErrorNotice error={error} context="Artifact summary unavailable" />`
  instead of returning `null` on missing data.
- `ArtifactPreviewPane.tsx:21` — the preview `useQuery` at `:21` has no error
  branch. Add one: when `isError`, render
  `<ErrorNotice error={error} context="Preview failed" />`. The parquet
  `PREVIEW_FAILED` backend code will now surface in the UI.

Do not touch components that already use `formatApiError` or
`renderApiError` correctly (`useRunProgress`, `QueryState`, `ProjectView`,
`ExportPanel`, `ParamsEditor`, `SchemaDrivenParamsEditor`,
`RawJsonParamsFallback`, `ManualBinningEditDialog`).

## Tests

### New: `frontend/src/utils/__tests__/query.test.ts`

- Omits `undefined`, `null`, and `""` params.
- Encodes spaces (`%20`), slashes (`%2F`), `&` (`%26`), `?` (`%3F`).
- Preserves numeric `limit`/`offset` as strings.
- Returns the path unchanged when all params are empty.
- Appends `?` only when at least one param remains.
- Handles a boolean `false` value (encodes as `"false"`; does not omit it —
  only `undefined`/`null`/`""` are omitted).

### New: `frontend/src/components/__tests__/ErrorNotice.test.tsx`

- `ApiError` with `requestId` renders code, message, and `req=...`.
- Non-API `Error` renders its `message`.
- `null` error renders nothing.
- `context` label renders above the message when provided.

### Update: component tests

- `ManualBinningEditor.test.tsx` — assert the error code appears when the
  editor-state query fails (use MSW to return a 500 with a known code).
- `ArtifactBrowser`/`ArtifactSummaryInline`/`ArtifactPreviewPane` tests —
  assert `ErrorNotice` renders the API code on a failed fetch.

### New: API client query tests

Add or extend `frontend/src/api/__tests__/client.test.ts`:

- `api.getPlan("p1", "proj with space")` calls
  `/plans/p1?project_id=proj+with+space` (or the `URLSearchParams`-encoded
  equivalent), not `/plans/p1?project_id=proj with space`.
- `api.getArtifactPreview("a1", 100, 0)` calls
  `/artifacts/a1/preview?limit=100&offset=0`.
- `api.getStepEvidence("r1", "s1", undefined)` calls `/runs/r1/steps/s1/evidence`
  with no trailing `?`.

## Verification

```bash
npm run test -- src/api src/hooks src/components/__tests__/ProjectView \
  src/utils/__tests__/query.test.ts \
  src/components/__tests__/ErrorNotice.test.tsx
npm run typecheck
npm run lint
```

## Definition of done

1. `withQuery` exists and is used for every optional query string in
   `client.ts`; no manual `?param=${value}` interpolation remains.
2. `ErrorNotice` exists and is used in `ManualBinningEditor`,
   `ArtifactBrowser`, `ArtifactSummaryInline`, and `ArtifactPreviewPane`.
3. `ArtifactSummaryInline` no longer collapses to `null` on a query error.
4. `ArtifactPreviewPane` surfaces `PREVIEW_FAILED` instead of rendering
   nothing.
5. Query and error tests are green; `typecheck` and `lint` are clean.
6. No new handwritten TS types for API shapes (regenerate `schema.d.ts` only
   if a backend model changed, which this batch does not).

## Files touched

- `frontend/src/utils/query.ts` (new)
- `frontend/src/components/ErrorNotice.tsx` (new)
- `frontend/src/api/client.ts`
- `frontend/src/components/ManualBinningEditor.tsx`
- `frontend/src/components/ArtifactBrowser.tsx`
- `frontend/src/components/ArtifactSummaryInline.tsx`
- `frontend/src/components/ArtifactPreviewPane.tsx`
- `frontend/src/hooks/useManualBinningState.ts` (expose `error` if missing)
- `frontend/src/utils/__tests__/query.test.ts` (new)
- `frontend/src/components/__tests__/ErrorNotice.test.tsx` (new)
- `frontend/src/api/__tests__/client.test.ts` (updated)
- affected component tests (updated)

## Depends on

none (frontend-only, Wave 1).

## Unblocks

Batch H (frontend parity assertions use `ErrorNotice` and `withQuery`).