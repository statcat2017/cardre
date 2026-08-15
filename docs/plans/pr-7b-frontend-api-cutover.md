# PR 7b: Frontend API Cutover

## Purpose

Move the frontend completely onto the API contract completed by PR 360. Project
identity must come from the `{project_id}` URL path parameter only, and users
must be able to request cooperative cancellation of a running run.

This document is intentionally implementation-oriented for a smaller LLM. Read
the referenced files before editing; do not add backend cleanup or acceptance
work to this PR.

## Scope

Include:

- Remove `projectHeaders()` and all `X-Project-Id`/`X-Project-Path` request
  headers from the frontend.
- Use generated `{project_id}` path parameters exclusively.
- Add `cancelRun(runId)` to the scoped API client.
- Add a cancellation mutation to `useProjectWorkspace`.
- Add a cancellation control to `RunDetailsPanel` and wire it in `ProjectView`.
- Update client, hook, and component tests.
- Regenerate the OpenAPI TypeScript contract and run frontend verification.

Do not include:

- Legacy package deletion.
- Import-linter tightening.
- Migration-xfail removal.
- Full launch-pathway acceptance testing.

## Contract Facts

The generated contract already includes:

```text
POST /projects/{project_id}/runs/{run_id}/cancel
```

The operation returns `RunResponse`. Relevant fields are:

```ts
type RunResponse = {
  run_id: string;
  plan_version_id: string;
  status: string;
  run_scope: string;
  branch_id?: string | null;
  force: boolean;
  started_at: string;
  finished_at?: string | null;
  step_count: number;
  is_stale: boolean;
  cancel_requested: boolean;
};
```

The backend accepts cancellation only when `run.status === "running"`. It sets
`cancel_requested` and lets cooperative execution transition to `cancelled`.
Do not display a cancel control for `created`, `queued`, terminal, or already
cancel-requested runs.

## Files To Change

- `frontend/src/api/client.ts`
- `frontend/src/api/__tests__/client.test.ts`
- `frontend/src/hooks/useProjectWorkspace.ts`
- `frontend/src/hooks/__tests__/useProjectWorkspace.test.tsx`
- `frontend/src/components/RunDetailsPanel.tsx`
- `frontend/src/components/ProjectView.tsx`
- `frontend/src/components/__tests__/RunDetailsPanel.test.tsx` (new)
- `frontend/src/api/openapi.json` and `frontend/src/api/schema.d.ts` only if
  regeneration changes them

## 1. Remove Project Identity Headers

In `frontend/src/api/client.ts`, delete:

```ts
const projectHeaders = (projectId: string) => ({
  "X-Project-Id": projectId,
});
```

For each method returned by `api.forProject(scope)`, remove the `header` member
from `params`. Preserve the generated `path` member.

Before:

```ts
await client.GET("/projects/{project_id}/runs", {
  params: {
    path: { project_id: pid },
    header: projectHeaders(pid),
  },
});
```

After:

```ts
await client.GET("/projects/{project_id}/runs", {
  params: {
    path: { project_id: pid },
  },
});
```

Apply this to every scoped plans, plan-version, run, run-step, and evidence
method. Do not remove normal transport headers such as `Accept` and JSON
`Content-Type`; only remove project identity headers.

## 2. Add `cancelRun` To The Scoped Client

Add this method alongside `getRun` in the object returned by `api.forProject`:

```ts
cancelRun: async (runId: string) => {
  const client = makeClient();
  return requireData(
    await client.POST("/projects/{project_id}/runs/{run_id}/cancel", {
      params: {
        path: { project_id: pid, run_id: runId },
      },
    }),
  );
},
```

There is no request body. Let `openapi-fetch` infer the response type from
`schema.d.ts`; do not hand-write a response interface.

## 3. Add Workspace Cancellation Mutation

In `frontend/src/hooks/useProjectWorkspace.ts`, add a mutation after
`runMutation`:

```ts
const cancelRunMutation = useMutation({
  mutationFn: (runId: string) => scoped.cancelRun(runId),
  onSuccess: (run) => {
    setError(null);
    queryClient.invalidateQueries({ queryKey: ["runs", scope.projectId] });
    queryClient.invalidateQueries({
      queryKey: ["run", scope.projectId, run.run_id],
    });
    queryClient.invalidateQueries({
      queryKey: ["runSteps", scope.projectId, run.run_id],
    });
    queryClient.invalidateQueries({
      queryKey: ["runEvidence", scope.projectId, run.run_id],
    });
  },
  onError: (err) => {
    setError(toErrorMessage(err));
  },
});
```

Return `cancelRunMutation` from the hook.

Keep the existing terminal-status set unchanged:

```ts
const TERMINAL_RUN_STATUSES = new Set([
  "succeeded", "failed", "cancelled", "interrupted",
]);
```

Polling should continue after cancellation is requested. It stops only after
the run reaches a terminal status.

## 4. Expose Cancellation In The Run Panel

Extend `RunDetailsPanel` props:

```ts
cancelPending: boolean;
onCancel: (runId: string) => void;
```

Derive availability from the backend contract:

```ts
const canCancel = run?.status === "running" && !run.cancel_requested;
```

Within the rendered run details, show either a cancellation-requested state or
the button:

```tsx
{run.cancel_requested ? (
  <div role="status">
    Cancellation requested. Waiting for the active step to stop.
  </div>
) : canCancel ? (
  <button
    type="button"
    disabled={cancelPending}
    onClick={() => onCancel(run.run_id)}
  >
    {cancelPending ? "Cancelling..." : "Cancel run"}
  </button>
) : null}
```

Use the existing button styling pattern in `VersionPanel.tsx`: disabled state
must visually communicate that the action cannot be repeated.

Wire the panel from `ProjectView.tsx`:

```tsx
<RunDetailsPanel
  // existing props
  cancelPending={ws.cancelRunMutation.isPending}
  onCancel={(runId) => ws.cancelRunMutation.mutate(runId)}
/>
```

## 5. Client Tests

Update `frontend/src/api/__tests__/client.test.ts` so tests prove path-only
identity rather than asserting legacy headers.

```ts
it("scoped GET uses only the project path parameter", async () => {
  const fetchMock = vi
    .spyOn(globalThis, "fetch")
    .mockResolvedValue(jsonResponse({ runs: [] }));

  await api.forProject({ projectId: "p-1" }).listRuns();

  const request = fetchMock.mock.calls[0]![0] as Request;
  expect(request.url).toContain("/projects/p-1/runs");
  expect(request.headers.get("X-Project-Id")).toBeNull();
  expect(request.headers.get("X-Project-Path")).toBeNull();
  expect(request.headers.get("Accept")).toBe("application/json");
});
```

Add cancellation coverage:

```ts
it("cancels a run through its scoped path", async () => {
  const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(
    jsonResponse({
      run_id: "r-1",
      plan_version_id: "v-1",
      status: "running",
      run_scope: "full_plan",
      force: false,
      started_at: "2026-01-01T00:00:00Z",
      step_count: 0,
      is_stale: false,
      cancel_requested: true,
    }),
  );

  const run = await api.forProject({ projectId: "p-1" }).cancelRun("r-1");

  const request = fetchMock.mock.calls[0]![0] as Request;
  expect(request.method).toBe("POST");
  expect(request.url).toContain("/projects/p-1/runs/r-1/cancel");
  expect(request.headers.get("X-Project-Id")).toBeNull();
  expect(run.cancel_requested).toBe(true);
});
```

Keep a scoped POST test proving JSON requests still preserve `Content-Type` and
their body while omitting project headers.

## 6. Hook Tests

In `frontend/src/hooks/__tests__/useProjectWorkspace.test.tsx`, add the mock:

```ts
cancelRun: vi.fn(),
```

Test a successful cancellation mutation:

1. Seed a selected running run.
2. Resolve `mockScoped.cancelRun` with the same run and
   `cancel_requested: true`.
3. Trigger `result.current.cancelRunMutation.mutate("r-2")`.
4. Assert the API method receives `"r-2"`.
5. Assert mutation success and that run query data is invalidated/refetched.

Test an error mutation:

1. Reject `cancelRun` with an `ApiError`.
2. Trigger the mutation.
3. Assert `result.current.error` contains `toErrorMessage` output.

Update the legacy `X-Project-Path` comment. The useful assertion is now that
the workspace scope contains only `{ projectId }` and the client sends no
legacy identity headers.

## 7. Component Tests

Create `frontend/src/components/__tests__/RunDetailsPanel.test.tsx`. Use
Testing Library and `user-event`.

```tsx
it("shows Cancel run only for a running run", () => {
  render(<RunDetailsPanel run={runningRun} cancelPending={false} onCancel={onCancel} /* remaining props */ />);
  expect(screen.getByRole("button", { name: "Cancel run" })).toBeEnabled();
});
```

```tsx
it("shows cancellation-requested state without a cancel button", () => {
  render(<RunDetailsPanel run={{ ...runningRun, cancel_requested: true }} cancelPending={false} onCancel={onCancel} /* remaining props */ />);
  expect(screen.getByRole("status")).toHaveTextContent("Cancellation requested");
  expect(screen.queryByRole("button", { name: "Cancel run" })).not.toBeInTheDocument();
});
```

```tsx
it("forwards the selected run id when cancelled", async () => {
  const user = userEvent.setup();
  render(<RunDetailsPanel run={runningRun} cancelPending={false} onCancel={onCancel} /* remaining props */ />);
  await user.click(screen.getByRole("button", { name: "Cancel run" }));
  expect(onCancel).toHaveBeenCalledWith("r-2");
});
```

Also test that `created`, `queued`, completed, and `cancel_requested` runs do
not expose an actionable Cancel button.

## Verification

Regenerate the contract from repository root:

```bash
python3 scripts/generate-openapi-types.py
git diff --exit-code -- frontend/src/api/openapi.json frontend/src/api/schema.d.ts
```

Run frontend checks from `frontend/`:

```bash
npm test
npx tsc --noEmit
npm run lint
npm run format:check
npm run build
```

Before push, run repository checks from the root:

```bash
. .venv/bin/activate
ruff check --fix
make preflight
scripts/pr-gate.sh --timeout 1500
```

## Remaining Sprint Roadmap After PR 7b

The closeout PR is deliberately separate from this frontend cutover. It must:

1. Delete `cardre/store/`, legacy configuration/artifact/capability modules,
   and obsolete API route files.
2. Remove server/OpenAPI compatibility project headers after all consumers use
   path identity only.
3. Set `ignore_unmatched: false` and enable final forbidden-import rules.
4. Remove remaining migration xfail markers.
5. Replace legacy launch tests with `tests/acceptance/test_launch_pathway.py`.
6. Run the full product acceptance pathway, including packaged sidecar and
   Tauri behavior where applicable.
7. Update architecture documentation from rewrite-in-progress to completed.

Keep PR 7b focused. Any deletion, import enforcement, or acceptance failure
belongs to closeout so it can be diagnosed independently.
