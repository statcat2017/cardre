# PR10 — Frontend + Tauri cleanup

**Findings:** F1, F2, F3, F4, F5, F6, F7, F8, F9, F10
**Batch:** H (independent of backend)
**Depends on:** nothing strictly (best after API shapes stabilize post-PR9,
but frontend types are generated, so changes flow through `schema.d.ts`)
**Behaviour change:** No

## Goal

Collapse `firstQueryError` to a `queryKey[0]` lookup. Type `ApiError.code`
as a union. Collapse `useRunWatch`'s three prose switches to one
`code → status` table feeding a single `deriveMessage`. Add a shared
`toErrorMessage` helper. Use the generated schema types in components.
Adopt react-query for run polling and manual-binning. Delete dead styles.
Fix `App.tsx` project state. Add a per-request timeout to `main.rs`.

## Tasks

### F1 — `firstQueryError` → `queryKey[0]`

1. Delete `QUERY_SOURCES` and `firstQueryError` in
   `frontend/src/components/ProjectView.tsx:20-39`.
2. Derive the source label from the first errored query's own
   `queryKey[0]`:
   ```ts
   const errored = [projectQuery, plansQuery, ...].find(q => q.error);
   const source = errored?.queryKey?.[0] ?? "query";
   ```

### F2 — `ApiError.code` typed union

1. In `frontend/src/api/client.ts:20-41`, change `readonly code: string`
   to `readonly code: ErrorCodes[keyof ErrorCodes]`.
2. Validate `detail?.code` against the known set in the JSON-parse path.
   If unknown, fall back to a real `ErrorCodes` member (add `HTTP_ERROR`
   to `errorCodes.ts` or map to an existing one). Do not invent
   undeclared literals.

### F3 — `useRunWatch` single prose switch

1. Define `const CODE_TO_STATUS: Partial<Record<ErrorCodes,
   RunWatchStatus>>` in `frontend/src/hooks/useRunWatch.ts` (or a new
   `runStatus.ts`).
2. The catch block sets ONLY `status` (via the lookup) and `error` (raw).
   No prose.
3. `deriveMessage(status, run)` owns ALL human text. Delete the
   hardcoded strings in the catch block.

### F6 — Delete unreachable `stuck` + `deriveStatus` default

1. Delete `stuck` from `RunWatchStatus` (or implement it — recommended:
   delete).
2. Tighten `deriveStatus` to `switch (run.status)` on the schema enum.
   Delete the `default: return "running"` branch.

### F4 — `toErrorMessage` helper

1. Add `export function toErrorMessage(err: unknown): string` to
   `client.ts` (or `errors.ts`).
2. Replace all 4 inline ternaries (`ProjectView.tsx:126,150`;
   `WelcomeScreen.tsx:38`; `useManualBinningReview.ts:51-59`).

### F5 — Schema-typed component props

1. Import `components["schemas"]["RunResponse"]` etc. from the generated
   schema.
2. Replace hand-defined `Run`/`Step`/`Evidence` interfaces in
   `RunDetailsPanel.tsx:3-25`, `PlanSidebar.tsx:3-11`,
   `VersionPanel.tsx:3-19` with `Pick<RunResponse, ...>` or the full type.

### F7 — react-query for run poll + manual-binning

1. Adopt `refetchInterval` for run polling in `useRunWatch`:
   ```ts
   const runQuery = useQuery({
     queryKey: ["run", runId],
     queryFn: () => api.getRun(runId),
     refetchInterval: (q) => isTerminal(q.state.data?.status) ? false : 1000,
   });
   ```
   Deletes: interval ref, teardown effect, `polling` state,
   `completedRunIdsRef`.
2. Add `getManualBinningReview`, `submitManualBinningEdit`,
   `updateManualBinningReview` to `client.ts`'s `api` object.
3. Convert `useManualBinningReview` to thin `useQuery`/`useMutation`
   wrappers. Delete the direct `fetchJson` import and hand-rolled
   `baseUrl`.

### F8 — Delete dead styles

1. Delete `surfaceMuted`, `blueBg`, `blueText`, `greenBg`, `fontMono`,
   `panelStyle` from `frontend/src/styles.ts`.

### F9 — `App.tsx` project state

1. Replace two `useState<string|null>` with one:
   ```ts
   const [project, setProject] = useState<{id: string; path: string} | null>(null);
   ```
2. `onBack` calls `setProject(null)`.

### F10 — `main.rs` timeout + dead ctrl-c

1. Give `wait_for_health` a per-request timeout:
   ```rust
   let client = reqwest::blocking::Client::builder()
       .timeout(Duration::from_secs(2)).build()...;
   ```
2. Delete the unused `running`/ctrl-c `AtomicBool` (or wire to graceful
   shutdown — recommended: delete).
3. Extract `spawn_sidecar` and `inject_api_url` from the `setup` closure.

## Acceptance criteria

- [ ] `npm run typecheck` green.
- [ ] `npm test` green.
- [ ] `rg 'firstQueryError|QUERY_SOURCES' frontend/src` returns 0.
- [ ] `rg 'code:\s*string' frontend/src/api/client.ts` returns 0.
- [ ] `rg 'err instanceof ApiError \? err.detail' frontend/src` returns 0.
- [ ] `rg 'interface Run \{|interface Step \{|interface Evidence \{'
  frontend/src/components` returns 0.
- [ ] `rg 'stuck' frontend/src/hooks/useRunWatch.ts` returns 0.
- [ ] `rg 'fetchJson' frontend/src/hooks/useManualBinningReview.ts`
  returns 0.
- [ ] `rg 'surfaceMuted|blueBg|blueText|greenBg|fontMono|panelStyle'
  frontend/src/styles.ts` returns 0.
- [ ] `rg 'setProjectId\(null\)' frontend/src/App.tsx` returns 0.
- [ ] `rg 'blocking::get' frontend/src-tauri/src/main.rs` returns 0.

## Do not

- Do not change the API response shapes the frontend consumes (those are
  backend-owned). Only change how the frontend reads/types them.
- Do not add new npm dependencies unless `react-query` is not already
  installed (it is — the cluster uses it everywhere except
  `useRunWatch`/`useManualBinningReview`).