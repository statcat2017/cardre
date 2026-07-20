# PR 3: Frontend And Desktop Boundary Implementation Guide

## Audience And Goal

This document is an implementation recipe for a smaller coding agent. It is
the detailed plan for PR 3 from the remediation sprint: make the active
workspace coherent, make generated OpenAPI types the frontend boundary, and
make the desktop app own its sidecar through every startup failure path.

The implementation baseline is `main` at commit `808e528`. Read the current
files before editing; use this document to decide *what* to change and the
tests to prove each change. Do not bundle node decomposition, model-artifact
work, or node-parameter wiring into this PR.

## Scope

| Slice | Outcome | Main files |
| --- | --- | --- |
| 5 | The selected Run and the Run sidebar always use the same filtered collection; active Runs refresh without a page reload. | `frontend/src/hooks/useProjectWorkspace.ts`, `PlanSidebar.tsx`, `ProjectView.tsx`, `WelcomeScreen.tsx`, `App.tsx` |
| 6 | Every API operation uses generated OpenAPI path, request, and response types; diagnostics are typed. | `frontend/package.json`, `frontend/src/api/client.ts`, `cardre/api/schemas.py`, `cardre/api/routes/_run_mappings.py`, generated OpenAPI files |
| 7 | The Tauri shell cleans up the child sidecar and returns an observable startup error when handoff fails. | `frontend/src-tauri/src/main.rs`, Rust tests, sidecar CI smoke test |

## Non-Goals

1. Do not change API route URLs, SQLite tables, Run state values, or execution topology.
2. Do not bring back `to_node`, branch-launch modes, or project-path identity.
3. Do not replace `ApiError`, its canonical error codes, timeout behavior, or abort behavior with library defaults.
4. Do not write an application-level polling framework. One small workspace-owned refresh loop is enough.
5. Do not rewrite the sidecar resolver, target-triple naming, or CI platform matrix. Those are already covered by ADR-0011 and existing tests.

## Preconditions

1. Work from a clean branch based on current `main`.
2. Bootstrap the Python virtual environment and frontend dependencies as described in `AGENTS.md`.
3. Read `docs/architecture/thermo-nuclear-remediation-sprint.md`, sections 5 through 7, and ADR-0006 and ADR-0011.
4. Keep generated files generated. Never hand-edit `frontend/src/api/openapi.json` or `frontend/src/api/schema.d.ts`.

## Recommended Delivery Sequence

Implement and test the slices in this order. Make separate commits if that is natural, but one PR is acceptable.

1. Slice 5: workspace semantics and polling.
2. Slice 6a: typed backend diagnostics and generated schema refresh.
3. Slice 6b: typed OpenAPI client migration with the existing robust transport.
4. Slice 7: sidecar lifecycle cleanup and smoke-test check.
5. Run all focused checks, then the required preflight and PR gate.

The client migration depends on the Slice 5 removal of `projectPath` from the API scope. The diagnostic UI migration depends on the regenerated schema from Slice 6a.

---

## Slice 5: Coherent Live Workspace

### Current Problems

`useProjectWorkspace.ts` derives `runsForSelectedVersion`, but
`PlanSidebar.tsx` falls back to every Run when that filtered list is empty.
`useSelectedEntity` validates the selected Run against the filtered list,
while the sidebar can render a different list. A Run shown in the sidebar can
therefore be impossible to select.

Runs are launched with `sync: false`. The current mutation invalidates once;
it does not observe the eventual terminal state.

Finally, `ProjectScope` contains a user-typed filesystem path. The backend
identifies a selected project by `X-Project-Id`, so carrying a stale creation
path into every selected-project request is misleading state.

### 5.1 Establish One Visible Run Collection

In `useProjectWorkspace.ts`, calculate `visibleRuns` once, immediately after
the Runs query:

```ts
const allRuns = runsQuery.data?.runs ?? [];
const visibleRuns = effectiveSelectedVersionId
  ? allRuns.filter((run) => run.plan_version_id === effectiveSelectedVersionId)
  : allRuns;

const effectiveSelectedRunId = useSelectedEntity(
  selectedRunId,
  visibleRuns,
  "run_id",
  "first",
);
```

Requirements:

1. Remove `runsForSelectedVersion`; do not retain it as an alias.
2. Return `visibleRuns` from the hook.
3. Pass only `visibleRuns` to `PlanSidebar`.
4. Change `PlanSidebar` to accept `runs: Run[]` and render that exact list.
5. Render the explicit empty state `No runs for this version.` when a version
   is selected and `runs` is empty. Render `No runs yet.` when no version is
   selected and the project has no Runs. Pass a boolean such as
   `versionSelected` if the component needs to distinguish the messages.
6. Keep the existing behavior that clearing a Plan or Version selection also
   clears the raw selected Run ID.

Do not implement this with a fallback like the following. It recreates the
bug:

```ts
// Incorrect: a version with no Runs must not display another version's Runs.
const displayRuns = runsForVersion.length > 0 ? runsForVersion : allRuns;
```

### 5.2 Poll Active Runs Through One Timer

The domain has four terminal Run states. The frontend must recognize all of
them, including `interrupted`:

```ts
const TERMINAL_RUN_STATUSES = new Set([
  "succeeded",
  "failed",
  "cancelled",
  "interrupted",
]);

function isTerminalRun(status: string): boolean {
  return TERMINAL_RUN_STATUSES.has(status);
}
```

Add one `useEffect` in `useProjectWorkspace.ts`. It starts only when the
currently selected Run has data and is non-terminal. It creates exactly one
interval, then cleans it up on every dependency change and unmount.

```ts
useEffect(() => {
  const runId = effectiveSelectedRunId;
  if (!runId || !selectedRunQuery.data || isTerminalRun(selectedRunQuery.data.status)) {
    return;
  }

  const refresh = () => {
    void Promise.all([
      queryClient.refetchQueries({ queryKey: ["runs", scope.projectId] }),
      queryClient.refetchQueries({ queryKey: ["run", scope.projectId, runId] }),
      queryClient.refetchQueries({ queryKey: ["runSteps", scope.projectId, runId] }),
      queryClient.refetchQueries({ queryKey: ["runEvidence", scope.projectId, runId] }),
    ]);
  };

  const intervalId = window.setInterval(refresh, 1_000);
  return () => window.clearInterval(intervalId);
}, [effectiveSelectedRunId, queryClient, scope.projectId, selectedRunQuery.data]);
```

Implementation notes:

1. It is acceptable for `refetchQueries` to fetch only active observers. All
   four queries are active in `ProjectView` for a selected Run.
2. Do not add a separate interval to each query. The one interval deliberately
   refreshes the list, selected Run, steps, and evidence together.
3. Do not run a timer before `selectedRunQuery` returns a Run. This avoids
   polling an arbitrary Run ID merely because one is selected.
4. Do not invalidate on every render. The effect must return its cleanup and
   depend on the selected Run's current status, so a terminal response stops
   the next timer.
5. Keep the post-create invalidations. Polling begins after the new Run is
   selected and its selected-run query has data.

If React lint rules reject `selectedRunQuery.data` as a dependency, extract
`const selectedRunStatus = selectedRunQuery.data?.status` and depend on that
string instead. Do not suppress the lint rule.

### 5.3 Remove Project Path From Selected Identity

Make the selected App state `{ id: string }`, not `{ id: string; path:
string }`.

Apply the following data-flow changes:

| File | Required change |
| --- | --- |
| `frontend/src/api/client.ts` | Define `ProjectScope` as `{ projectId: string }`. `projectHeaders` sends only `X-Project-Id`. |
| `useProjectWorkspace.ts` | Continue receiving the simplified scope. Every query key uses `scope.projectId` only. |
| `ProjectView.tsx` | Remove the `projectPath` prop and the filesystem-path display. Create `scope` with only `projectId`. |
| `App.tsx` | Store only project ID. The callback from the welcome screen accepts only a project ID. |
| `WelcomeScreen.tsx` | `api.listProjects()` is global, so query it without a path-dependent key or `enabled` condition. The text input remains the path used only by `createProject`. Existing-project selection passes only `project.project_id`. |

The creation form can continue to remember the last creation path in
`localStorage`; it must not make that path part of a selected project's
identity or send it in subsequent API headers.

### Slice 5 Test Plan

Create a hook test at
`frontend/src/hooks/__tests__/useProjectWorkspace.test.tsx`. Use a new
`QueryClient` per test, with retries disabled, and wrap the hook in a
`QueryClientProvider`. Mock `api.forProject` and `api.getProject` at the API
boundary; do not mock TanStack Query internals.

Useful setup pattern:

```tsx
function createWrapper() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return ({ children }: { children: React.ReactNode }) => (
    <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
  );
}
```

Required cases:

1. Given selected version `v-empty`, all Runs belonging to `v-other`, assert
   `result.current.visibleRuns` is empty and
   `effectiveSelectedRunId` is `null`.
2. Given a displayed Run in the selected version, set it with
   `setSelectedRunId`; assert it remains effective and `getRun` is queried
   for that Run.
3. Render `PlanSidebar` with a selected version and `runs={[]}`; assert
   `No runs for this version.` is visible and no Run from another version is
   present.
4. With `vi.useFakeTimers()`, serve a selected Run first as `running`, then
   as `succeeded`. Advance one interval and assert list, Run, steps, and
   evidence fetchers have each been called again. Advance another interval
   after the terminal response and assert no additional calls occur.
5. Render `WelcomeScreen`, select an existing Project after typing a creation
   path, then inspect the next scoped request. Assert its headers include
   `X-Project-Id` and do not include `X-Project-Path`.

Example timer assertion:

```ts
await act(async () => {
  await vi.advanceTimersByTimeAsync(1_000);
});
expect(scoped.listRuns).toHaveBeenCalledTimes(2);
expect(scoped.getRun).toHaveBeenCalledTimes(2);
expect(scoped.listRunSteps).toHaveBeenCalledTimes(2);
expect(scoped.listRunEvidence).toHaveBeenCalledTimes(2);
```

Do not assert an exact total number of requests without first waiting for the
initial queries. Assert the additional polling calls relative to a captured
baseline to avoid a timing-sensitive test.

---

## Slice 6: Generated OpenAPI Boundary And Typed Diagnostics

### 6.1 Add an Explicit Diagnostic DTO

The API currently emits `dict[str, Any]` for Run diagnostics, latest error,
step warnings, and step errors. That turns all generated frontend types into
`Record<string, unknown>` and causes the JSX cast in `RunDetailsPanel.tsx`.

Add this response DTO in `cardre/api/schemas.py`. Import `JsonDict` from
`cardre.domain.diagnostics` rather than redefining a loose alias.

```py
class DiagnosticResponse(BaseModel):
    code: str = "UNKNOWN"
    message: str = ""
    severity: str = "error"
    source: str | None = None
    context: JsonDict = Field(default_factory=dict)
    created_at: str | None = None
```

Change the affected response fields to:

```py
diagnostics: list[DiagnosticResponse] = Field(default_factory=list)
latest_error: DiagnosticResponse | None = None

# In RunStepResponse:
warnings: list[DiagnosticResponse] = Field(default_factory=list)
errors: list[DiagnosticResponse] = Field(default_factory=list)
```

Do not expose arbitrary diagnostic keys as first-class response fields. The
database repository currently flattens JSON context after fetching it. The API
mapping layer must reverse that flattening at the public boundary.

In `cardre/api/routes/_run_mappings.py`, add one pure adapter used by both
Run and RunStep mappings:

```py
_DIAGNOSTIC_FIELDS = {"code", "message", "severity", "source", "created_at"}


def diagnostic_to_response(value: Mapping[str, Any]) -> DiagnosticResponse:
    return DiagnosticResponse(
        code=str(value.get("code", "UNKNOWN")),
        message=str(value.get("message", "")),
        severity=str(value.get("severity", "error")),
        source=value.get("source"),
        created_at=value.get("created_at"),
        context={key: item for key, item in value.items() if key not in _DIAGNOSTIC_FIELDS},
    )
```

Use it for `summary.diagnostics`, `summary.latest_error`, `rs.warnings`, and
`rs.errors`. Do not make `RunRepository` return API models; repository output
remains domain-shaped dictionaries.

Update or add focused mapping tests in `tests/test_api_run_responses.py`.
The most important assertion is preservation of context without the old
flattened response contract:

```py
def test_run_summary_maps_diagnostic_context_to_typed_response() -> None:
    response = run_summary_to_response(summary_with(
        diagnostics=[{
            "code": "RUN_EXECUTION_FAILED",
            "message": "boom",
            "severity": "error",
            "node_id": "fit-model",
        }]
    ))

    diagnostic = response.diagnostics[0]
    assert diagnostic.code == "RUN_EXECUTION_FAILED"
    assert diagnostic.context == {"node_id": "fit-model"}
```

Regenerate the OpenAPI files immediately after the schema and mapping tests
pass:

```bash
. .venv/bin/activate
python3 scripts/generate-openapi-types.py
git diff -- frontend/src/api/openapi.json frontend/src/api/schema.d.ts
```

The generated `RunResponse` must now contain
`DiagnosticResponse[]` and `DiagnosticResponse | null`, and `RunStepResponse`
and correct the FastAPI response models before editing frontend rendering.

### 6.2 Use `openapi-fetch` With the Existing Transport Semantics

Add `openapi-fetch` as a frontend runtime dependency. Do not add a second
handwritten API-schema layer. `schema.d.ts` already exports `paths`, which is
the generic input required by `openapi-fetch`.

The required architecture is:

```text
generated paths/operations
          |
          v
openapi-fetch operation client
          |
          v
Cardre transport fetch adapter
          |
          v
window.fetch
```

The Cardre adapter owns timeouts, cancellation, header normalization, JSON
content validation, and `ApiError` conversion. `openapi-fetch` owns generated
path, parameter, request-body, and success-response typing.

#### Preserve Robust Transport Behavior

Split the current `fetchJson` implementation into two layers:

1. `fetchResponse(input, options): Promise<Response>` performs timeout and
   abort composition, normalizes all non-success responses to `ApiError`, and
   returns a successful response.
2. `fetchJson<T>(...)` remains a compatibility-friendly exported wrapper for
   focused transport tests. It calls `fetchResponse`, validates JSON content,
   rejects empty successful JSON bodies, and parses JSON.

Use the platform `Headers` class. The current cast of `HeadersInit` to
`Record<string, string>` loses legitimate header inputs.

```ts
const headers = new Headers(init.headers);
headers.set("Accept", "application/json");
if (body !== undefined) {
  headers.set("Content-Type", "application/json");
}
```

The `openapi-fetch` transport adapter must receive a `RequestInfo` and
`RequestInit`, call `fetchResponse`, and return the untouched successful
`Response` to the library. Before returning a JSON-bearing success response,
validate a clone so malformed JSON, an empty body, and wrong content type
still produce the existing canonical `ApiError` codes:

```ts
async function typedTransport(input: RequestInfo | URL, init?: RequestInit): Promise<Response> {
  const response = await fetchResponse(input, init);
  if (response.status === 204) return response;

  const contentType = response.headers.get("content-type") ?? "";
  if (!contentType.includes("json")) {
    throw new ApiError(ErrorCodes.MALFORMED_JSON_RESPONSE, ...);
  }
  const text = await response.clone().text();
  if (!text) throw new ApiError(ErrorCodes.EMPTY_OK_BODY, ...);
  try {
    JSON.parse(text);
  } catch {
    throw new ApiError(ErrorCodes.MALFORMED_JSON_RESPONSE, ...);
  }
  return response;
}
```

Use `createClient<paths>({ baseUrl: getBaseUrl(), fetch: typedTransport })`.
Create the client at call time, or derive it from the current `getBaseUrl`, so
the Tauri-injected `window.__API_URL__` is observed after startup. Do not read
the fallback URL once at module import time.

#### Do Not Leak Library Result Unions

`openapi-fetch` returns a `{ data, error, response }` result. Create one small
helper which turns an absent success value into an error and returns `data`.
The API wrapper must continue to return `Promise<ProjectResponse>`, not a
library-specific union to every hook.

```ts
function requireData<T>(result: { data?: T; error?: unknown; response: Response }): T {
  if (result.data !== undefined) return result.data;
  if (result.error instanceof ApiError) throw result.error;
  throw new ApiError(
    ErrorCodes.NON_JSON_ERROR_RESPONSE,
    `API operation failed with HTTP ${result.response.status}`,
    result.response.status,
  );
}
```

Use a return-type-safe operation wrapper if TypeScript otherwise duplicates
the `requireData(await client.GET(...))` shape. Keep it local to
`client.ts`; do not invent a generic application SDK.

Example operation migration:

```ts
const client = createClient<paths>({ baseUrl: getBaseUrl(), fetch: typedTransport });

getProject: async (projectId: string) =>
  requireData(await client.GET("/projects/{project_id}", {
    params: { path: { project_id: projectId } },
  })),

createProject: async (body) =>
  requireData(await client.POST("/projects", { body })),
```

For project-scoped methods, put the header under generated header parameters
and use generated path parameters. Do not interpolate a URL manually:

```ts
const scopeParams = (projectId: string) => ({
  path: { project_id: projectId },
  header: { "X-Project-Id": projectId },
});

listRunSteps: async (runId: string) =>
  requireData(await client.GET("/projects/{project_id}/runs/{run_id}/steps", {
    params: {
      ...scopeParams(scope.projectId),
      path: { project_id: scope.projectId, run_id: runId },
    },
  })),
```

Use the actual generated parameter shape. Do not blindly spread two objects
with a `path` key as in the illustrative snippet; it intentionally shows why a
small helper should return just the header, or why the full path object should
be written once per operation. The final code must have one `path` object with
every required placeholder.

Suggested safe helper:

```ts
const projectHeaders = (projectId: string) => ({
  "X-Project-Id": projectId,
});
```

Then each operation specifies its generated `params.path` explicitly and
`params.header: projectHeaders(scope.projectId)`.

All methods currently exposed by `api` and `api.forProject` must migrate in
this PR. Do not leave a mixture of handwritten and generated methods.

#### Render Diagnostics Without Casts

After regeneration, replace the local cast in `RunDetailsPanel.tsx` with the
generated response shape:

```tsx
{run.latest_error && (
  <div role="alert" style={errorStyle}>
    <strong>{run.latest_error.code}</strong>: {run.latest_error.message}
  </div>
)}
```

Do not add `as`, `unknown`, optional record indexing, or fallback parsing in
the component. The backend DTO supplies the required `code` and `message`.

### Slice 6 Test Plan

Extend `frontend/src/api/__tests__/client.test.ts`; retain every existing
robustness test. Add these transport cases:

```ts
it.each([
  [{ "X-Test": "object" }],
  [new Headers({ "X-Test": "headers" })],
  [["X-Test", "tuple"]],
])("preserves supported HeadersInit input", async ([input]) => {
  const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(jsonResponse({ ok: true }));
  await fetchJson("/test", { headers: input });
  expect(new Headers(fetchMock.mock.calls[0]![1]!.headers).get("X-Test")).toBeTruthy();
});
```

Add operation-level mock-fetch tests for at least one GET and one POST. They
must prove generated placeholder expansion and typed body serialization:

```ts
await api.forProject({ projectId: "p-1" }).createRun({
  plan_version_id: "v-1",
  force: false,
  sync: false,
});

expect(fetchMock).toHaveBeenCalledWith(
  "http://127.0.0.1:8752/projects/p-1/runs",
  expect.objectContaining({
    method: "POST",
    body: JSON.stringify({ plan_version_id: "v-1", force: false, sync: false }),
  }),
);
```

Also add compile-time assertions with Vitest's `expectTypeOf` for a generated
response, such as `RunResponse["latest_error"]`, and for the `createRun`
request. The assertion must import its type from `schema.d.ts`, not redeclare
it. Runtime tests alone cannot prove the generated contract is used.

Add a `RunDetailsPanel` component test that passes a typed generated
`RunResponse` containing `latest_error`, then asserts the diagnostic code and
message render. This test must compile without a cast in production JSX.

Required backend cases:

1. Run diagnostics map known fields and context correctly.
2. `latest_error` maps to the same DTO.
3. Step warning and error arrays map to the same DTO.
4. The OpenAPI generator produces a non-`Record<string, unknown>` diagnostic
   schema.

---

## Slice 7: Owned Tauri Sidecar Lifecycle

### Existing Behavior To Preserve

`main.rs` correctly resolves a bundled sidecar before its development PATH
fallback, uses a target-triple filename, starts a loopback server on an
ephemeral port, and waits for `/health`. Keep these mechanics.

The remaining issue is ownership across the post-spawn path:

1. `std::process::exit` bypasses structured setup failure and complicates
   cleanup.
2. Lock errors when storing the child are ignored.
3. `window.eval` errors when injecting `window.__API_URL__` are ignored.
4. The child is stored before health succeeds, rather than being owned by a
   local guard that is reliably killed on every later failure.

### 7.1 Make Setup Fallible and Cleanup Local

Extract small helpers with fallible return values. Exact names are flexible;
the ownership and ordering are not.

```rust
fn inject_api_url(window: &tauri::WebviewWindow, api_url: &str) -> Result<(), String> {
    let script = api_url_assignment_script(api_url)?;
    window.eval(&script).map_err(|error| format!("failed to inject API URL: {error}"))
}

fn store_sidecar(app: &tauri::App, child: Child) -> Result<(), String> {
    let mut state = app
        .state::<AppState>()
        .sidecar_child
        .lock()
        .map_err(|_| "sidecar state lock poisoned".to_owned())?;
    *state = Some(child);
    Ok(())
}
```

In `setup`, keep `Child` local until all startup prerequisites pass. On any
error after spawning, kill and wait for that local child, then return an error
from the closure. Do not call `std::process::exit` in the setup body.

Required order:

```rust
let mut child = spawn_sidecar(&sidecar_path, port)?;
attach_log_readers(&mut child);

if let Err(error) = wait_for_health(port, 30) {
    kill_child(&mut child);
    return Err(error.into());
}

if let Err(error) = inject_api_url(&window, &api_url) {
    kill_child(&mut child);
    return Err(error.into());
}

if let Err(error) = store_sidecar(app, child) {
    // store_sidecar must return the un-stored Child on failure, or accept
    // &mut Child so this cleanup path still owns it. Design this detail before coding.
    kill_child(&mut child);
    return Err(error.into());
}
```

The final code cannot use `child` after moving it into `store_sidecar`. Pick a
Rust ownership-safe helper signature, for example:

```rust
fn store_sidecar(app: &tauri::App, child: &mut Option<Child>) -> Result<(), String>
```

It takes the child from `Option` only after acquiring the lock. On an error,
the caller still has `Some(child)` and can kill it. This is preferable to
trying to recover an already moved process handle.

Do not inject the API URL until the sidecar reports healthy. Do not store the
child before successful URL injection. The success invariant is:

```text
healthy sidecar + injected exact URL + child stored in AppState
```

The shutdown handler remains responsible for killing a successfully stored
child when the main window is destroyed. Improve it only as needed to avoid a
double-kill or a poisoned-lock panic; do not add a second owner.

### 7.2 Unit-Test Pure And Ownership Helpers

Do not attempt to instantiate a full Tauri app just to test a string helper.
Extract `api_url_assignment_script(api_url)` as a pure function and test it:

```rust
#[test]
fn api_url_assignment_uses_the_selected_loopback_port() {
    let script = api_url_assignment_script("http://127.0.0.1:43129").unwrap();
    assert!(script.contains("http://127.0.0.1:43129"));
    assert!(!script.contains("8752"));
}
```

The helper must safely quote or serialize the URL for JavaScript. Do not build
the script with an unescaped single-quoted interpolation. `serde_json` string
serialization is an appropriate way to create a JavaScript string literal.

Extract process cleanup behind a narrowly scoped test seam if necessary:

```rust
trait ChildProcess {
    fn kill(&mut self) -> std::io::Result<()>;
    fn wait(&mut self) -> std::io::Result<std::process::ExitStatus>;
}
```

Only introduce this trait if testing cleanup without it would require launching
the real Python sidecar. Do not generalize it into an application process
framework.

Required tests:

1. A health-check failure kills and waits for the locally owned child before
   setup returns an error.
2. URL-injection failure is returned, not ignored, and kills the child.
3. State-storage lock failure is returned, not ignored, and kills the child.
4. A successful injection script uses the actual ephemeral API URL.
5. Preserve existing bundled-vs-PATH and target-triple resolution tests.

If a full setup test is too coupled to Tauri's runtime, test a pure
`complete_sidecar_startup` helper that receives closures for health, injection,
and storage. It must still prove the child cleanup order; do not lower the
test to only checking log output.

### 7.3 Verify the CI Smoke Script

The current `smoke-test-sidecar` workflow already uses an ephemeral loopback
port and installs a trap immediately after spawn. Keep that behavior.

Review this sequence after any lifecycle edits:

```bash
PORT=$(python3 -c "import socket; s=socket.socket(); s.bind(('127.0.0.1',0)); print(s.getsockname()[1]); s.close()")
CARDRE_API_PORT=$PORT "$BINARY" &
SIDECAR_PID=$!
cleanup() { kill "$SIDECAR_PID" 2>/dev/null || true; }
trap cleanup EXIT INT TERM
```

Do not replace the ephemeral port with `18000`, and do not move the trap below
the health loop or a naming assertion. The smoke test must terminate the
packed child on success, health timeout, and assertion failure.

Update ADR-0011 only if externally observable sidecar startup behavior
changes. Internal helper extraction and stronger cleanup alone do not require
an ADR amendment.

---

## Verification Checklist

Run focused tests while implementing:

```bash
cd frontend && npm run test -- src/api src/hooks src/components/__tests__/ProjectView
cd frontend/src-tauri && cargo fmt --check
cd frontend/src-tauri && cargo clippy --all-targets -- -D warnings
cd frontend/src-tauri && cargo test
python3 -m pytest tests/test_api_run_response_shape.py tests/test_api_run_responses.py tests/test_api_runs.py -q --tb=short --no-cov
```

Run the frontend build and type check after OpenAPI regeneration:

```bash
cd frontend && npm run lint && npm run format:check && npm run build && npx tsc --noEmit
```

Before pushing, run the repository gate exactly as documented in `AGENTS.md`:

```bash
. .venv/bin/activate
ruff check --fix
make preflight
```

Then use only the PR gate to push, create or locate the PR, and wait for CI:

```bash
bash scripts/pr-gate.sh --base main --timeout 1800
```

## Final Acceptance Criteria

1. A selected version with no Runs cannot show or select another version's
   Run.
2. A selected active Run refreshes list, Run, steps, and evidence through one
   timer, then stops after `succeeded`, `failed`, `cancelled`, or `interrupted`.
3. Selecting an existing project sends no user-typed project path in API
   headers or selected application state.
4. `api` operations use generated OpenAPI paths, generated request bodies, and
   generated response types. No handwritten URL interpolation remains in the
   API wrapper.
5. All prior `fetchJson` error-code tests still pass, including timeout,
   caller abort, empty JSON success, malformed JSON, HTML error, and non-JSON
   error responses.
6. The generated API schema exposes a typed `DiagnosticResponse`; UI code
   renders it without type assertions.
7. A Tauri sidecar spawned during setup is either fully healthy, URL-injected,
   and stored for shutdown, or is killed and reported as a startup error.
8. Rust formatting, clippy, focused frontend/backend tests, preflight, and PR
   CI are green.
