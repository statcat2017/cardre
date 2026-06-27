# Project-Scoped Run & Artifact Resolution — TDD Plan

## Purpose

Eliminate the project-scope leakage and performance hazard where global run
and artifact routes scan every registered project, and migrate the frontend
to project-scoped endpoints so no normal UI flow can resolve a run or artifact
from the wrong project.

## Why this exists

- `GET /runs/{run_id}` (+`/steps`, `/manifest`) iterate `load_registry()` and
  open each project's `ProjectStore` until a match is found
  (`sidecar/routes/runs.py:79-166`).
- `GET /artifacts/{artifact_id}` (+`/summary`, `/preview`) call
  `find_artifact()`, which calls `scan_all_stores()` over every project
  (`cardre/services/artifact_service.py:16-28`,
  `sidecar/routes/artifacts.py:82-179`).
- Three frontend components still drive these global routes:
  `RunHistoryTab.tsx:16` (`getRunSteps`),
  `ArtifactSummaryInline.tsx:14` (`getArtifactSummary`),
  `ArtifactPreviewPane.tsx:23` (`getArtifactPreview`).
- Project-scoped run routes already exist at `/runs/project/{project_id}/...`
  and a project-scoped artifact *metadata* route exists at
  `/artifacts/project/{project_id}/artifacts/{artifact_id}` — but there is no
  project-scoped **summary** or **preview** route.

Target outcome: every normal UI flow resolves runs and artifacts strictly
within a project; "valid id, wrong project" returns 404; the backend never
opens a second project's store during a UI lookup.

## Scope boundary

In scope:
- Remove the six global run/artifact routes listed above.
- Remove `scan_all_stores()` / `find_artifact()`.
- Add project-scoped artifact `summary` and `preview` routes.
- Migrate the three leaking UI components and the `client.ts` API surface.
- Regenerate OpenAPI / TypeScript types.
- Rewrite affected tests; add wrong-project isolation tests.

Out of scope (explicitly deferred — do not touch here):
- Other scan-all loops in `plans.py`, `projects.py`, `comparisons.py`,
  `branches.py`, `reports.py`. Same hazard, different surface; separate batch.
- Normalizing the `/runs/project/{project_id}/runs/{run_id}` path to
  `/projects/{project_id}/runs/{run_id}` (cleaner REST, but large blast
  radius across client/MSW/`useRunProgress`/tests). Tracked as follow-up in
  "Future work".
- The `evidence.py` routes are already project-scoped via `project_id` query
  param and stay as-is.

## Decision: remove, not deprecate

Global lookup is removed outright. Justification:

- Run ids and artifact ids are UUIDs minted inside a `ProjectStore`; the
  frontend always knows its `projectId` (route param). No real consumer needs
  cross-project resolution.
- Deprecation-with-warning keeps the slow path alive and the
  cross-project-resolution hazard latent. The task asks to "fully bottom out"
  the issue.
- The cost of removal (rewriting ~12 existing tests, threading `projectId`
  through 3 components) is bounded and mechanical.

## Outcome contract (what must be true when done)

1. No normal UI flow issues a request to `/runs/{run_id}*` or
   `/artifacts/{artifact_id}*` (global).
2. `GET /artifacts/project/{project_id}/artifacts/{artifact_id}/summary` and
   `.../preview` exist and enforce project scoping (404 when the artifact is
   not in that project).
3. A request for a valid run_id via a different project_id returns 404
   `RUN_NOT_FOUND`; a valid artifact_id via a different project_id returns 404
   `ARTIFACT_NOT_FOUND`. No 403 (no authz layer; wrong scope = resource does
   not exist).
4. `scan_all_stores` and `find_artifact` symbols no longer exist in the repo.
5. `frontend/src/api/openapi.json` and `schema.d.ts` contain no global run /
   artifact paths and do contain the two new project-scoped artifact paths.
6. `pytest tests/` is green; `npm test` is green; `npx tsc --noEmit` is clean;
   `npm run lint` is clean; OpenAPI regen produces no uncommitted diff.

## TDD execution sequence

Work strictly red → green → refactor in the numbered phases. Do not advance
until the named gate passes. Each phase lists: (a) failing tests to write,
(b) the minimum code to make them pass, (c) refactor/cleanup. Code snippets
are skeletons — copy the surrounding style from the linked files, do not paste
blindly.

---

### Phase 1 — Red: backend wrong-project isolation tests

Goal: force project-scoped routes into existence and pin their 404 semantics.

#### 1a. Wrong project + valid run → 404

Add to `tests/test_sidecar_api.py`, in `TestProjectRuns` or a new
`TestProjectScopeIsolation` class:

```python
def test_project_run_404_for_wrong_project(self, client, tmp_dir, sample_german_credit):
    """A run owned by project A must not be reachable via project B."""
    # Set up project A with one run.
    proj_a = client.post("/projects", json={
        "path": str(tmp_dir / "a.cardre"), "name": "A",
    }).json()
    pid_a = proj_a["project_id"]
    client.post("/datasets/import", json={
        "project_id": pid_a, "source_path": str(sample_german_credit),
        "dataset_id": "uci-statlog-german-credit",
    })
    store_a = ProjectStore(tmp_dir / "a.cardre")
    plan_id = store_a.get_plans_for_project(pid_a)[0]["plan_id"]
    pv_id = store_a.get_latest_plan_version_id(plan_id)
    run_id = client.post("/runs?sync=true", json={
        "project_id": pid_a, "plan_version_id": pv_id,
    }).json()["run_id"]

    # Set up an unrelated project B.
    pid_b = client.post("/projects", json={
        "path": str(tmp_dir / "b.cardre"), "name": "B",
    }).json()["project_id"]

    # Every project-scoped run route must 404 via B.
    for suffix in ("", "/steps", "/manifest"):
        resp = client.get(f"/runs/project/{pid_b}/runs/{run_id}{suffix}")
        assert resp.status_code == 404, suffix
        assert resp.json()["detail"]["code"] == "RUN_NOT_FOUND", suffix
```

This test should already **pass** for `/runs` and `/steps` (project-scoped
routes exist and call `store.get_run(run_id)` → None → 404). It will **fail**
for `/manifest` only if the manifest handler returns `MANIFEST_NOT_FOUND`
instead of `RUN_NOT_FOUND` when the run doesn't exist in B — check
`sidecar/routes/runs.py:226-245`; if `run is None` raises `RUN_NOT_FOUND`
this passes already. If it passes trivially, keep it as a regression guard.

#### 1b. Wrong project + valid artifact → 404 for summary and preview

These routes do **not** exist yet, so these tests are genuinely red:

```python
def test_project_artifact_summary_404_for_wrong_project(self, client, tmp_dir, sample_german_credit):
    proj_a = client.post("/projects", json={
        "path": str(tmp_dir / "a.cardre"), "name": "A",
    }).json()
    pid_a = proj_a["project_id"]
    artifact_id = client.post("/datasets/import", json={
        "project_id": pid_a, "source_path": str(sample_german_credit),
        "dataset_id": "uci-statlog-german-credit",
    }).json()["artifact_id"]

    pid_b = client.post("/projects", json={
        "path": str(tmp_dir / "b.cardre"), "name": "B",
    }).json()["project_id"]

    resp = client.get(f"/artifacts/project/{pid_b}/artifacts/{artifact_id}/summary")
    assert resp.status_code == 404
    assert resp.json()["detail"]["code"] == "ARTIFACT_NOT_FOUND"


def test_project_artifact_preview_404_for_wrong_project(self, client, tmp_dir, sample_german_credit):
    # same setup as above
    ...
    resp = client.get(f"/artifacts/project/{pid_b}/artifacts/{artifact_id}/preview")
    assert resp.status_code == 404
    assert resp.json()["detail"]["code"] == "ARTIFACT_NOT_FOUND"
```

Also add a positive test (project-scoped summary/preview succeed when the
artifact belongs to the project) so the route is exercised happy-path:

```python
def test_project_artifact_summary_scoped(self, client, tmp_dir, sample_german_credit):
    pid = client.post("/projects", json={...}).json()["project_id"]
    artifact_id = client.post("/datasets/import", json={...}).json()["artifact_id"]
    resp = client.get(f"/artifacts/project/{pid}/artifacts/{artifact_id}/summary")
    assert resp.status_code == 200
    assert resp.json()["artifact_id"] == artifact_id
```

Gate: `pytest tests/test_sidecar_api.py::TestProjectScopeIsolation -q` must
fail on the summary/preview tests with 404-not-registered (FastAPI) or
route-doesn't-exist, confirming red.

---

### Phase 2 — Green: add project-scoped artifact summary & preview routes

Edit `sidecar/routes/artifacts.py`. Move the lazy `get_store_for_project`
import to the top of the file; remove the `find_artifact` import.

Add two handlers mirroring `get_project_artifact` (lines 182-199). Enforce
project scoping by looking the artifact up *via the project store only*:

```python
@router.get("/project/{project_id}/artifacts/{artifact_id}/summary", response_model=ArtifactSummaryResponse)
def get_project_artifact_summary(project_id: str, artifact_id: str):
    store = get_store_for_project(project_id)
    artifact = store.get_artifact(artifact_id)
    if artifact is None:
        raise HTTPException(
            status_code=404,
            detail={"code": "ARTIFACT_NOT_FOUND",
                    "message": f"No artifact with ID {artifact_id} in project {project_id}"},
        )
    reader = ArtifactEvidenceReader(store)
    evidence_summary = reader.summarise_artifact(artifact_id)
    row_count = artifact.metadata.get("row_count")
    column_count = artifact.metadata.get("column_count")
    summary_preview = None
    if artifact.media_type == "application/json":
        summary_preview = _json_artifact_preview(reader, artifact_id, evidence_summary.kind)
    return ArtifactSummaryResponse(
        artifact_id=artifact.artifact_id,
        artifact_type=artifact.artifact_type,
        role=artifact.role,
        media_type=artifact.media_type,
        logical_hash=artifact.logical_hash,
        physical_hash=artifact.physical_hash,
        row_count=row_count,
        column_count=column_count,
        summary_preview=summary_preview,
    )


@router.get("/project/{project_id}/artifacts/{artifact_id}/preview", response_model=ArtifactPreviewResponse)
def get_project_artifact_preview(
    project_id: str,
    artifact_id: str,
    limit: int = Query(default=100, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
):
    store = get_store_for_project(project_id)
    artifact = store.get_artifact(artifact_id)
    if artifact is None:
        raise HTTPException(
            status_code=404,
            detail={"code": "ARTIFACT_NOT_FOUND",
                    "message": f"No artifact with ID {artifact_id} in project {project_id}"},
        )
    # Copy the parquet/json branch bodies verbatim from the old global
    # get_artifact_preview (artifacts.py:130-179), swapping the `find_artifact`
    # pair for `store`/`artifact` you already have. Keep the same exception
    # codes (PREVIEW_FAILED, etc.).
    artifact_path = store.artifact_path(artifact)  # cardre-allow-artifact-read: artifact-byte-download
    reader = ArtifactEvidenceReader(store)
    if artifact.media_type == "application/json":
        evidence_summary = reader.summarise_artifact(artifact_id)
        json_preview = _json_artifact_preview(reader, artifact_id, evidence_summary.kind)
        return ArtifactPreviewResponse(
            artifact_id=artifact.artifact_id,
            media_type=artifact.media_type,
            json_content=json_preview,
            limit=limit, offset=offset,
        )
    if artifact.media_type == "application/vnd.apache.parquet":
        try:
            total_rows = artifact.metadata.get("row_count")
            preview = build_parquet_preview(artifact_path, offset, limit, total_rows)
            return ArtifactPreviewResponse(
                artifact_id=artifact.artifact_id,
                media_type=artifact.media_type,
                row_count=preview["total_rows"],
                column_count=len(preview["columns"]),
                columns=[ColumnInfo(name=c["name"], dtype=c["dtype"]) for c in preview["columns"]],
                rows=preview["rows"],
                limit=limit, offset=offset,
            )
        except Exception as exc:
            raise HTTPException(status_code=400, detail={
                "code": "PREVIEW_FAILED",
                "message": f"Could not read Parquet artifact: {exc}",
                "context": {"artifact_id": artifact_id, "path": str(artifact_path)},
            })
    return ArtifactPreviewResponse(
        artifact_id=artifact.artifact_id,
        media_type=artifact.media_type,
        json_content={"note": f"Preview not supported for media type {artifact.media_type}"},
    )
```

Do **not** delete the global routes yet — Phase 1 tests go green first.

Gate: `pytest tests/test_sidecar_api.py::TestProjectScopeIsolation -q` green.

---

### Phase 3 — Refactor: remove global routes and `find_artifact`

Now that project-scoped equivalents exist and are tested, delete the dead
globals. Order matters for keeping the suite green at each step.

1. In `sidecar/routes/artifacts.py`, delete `get_artifact`, `
   get_artifact_summary`, `get_artifact_preview` (the three `@router.get`
   handlers at lines 82-179). Keep `_shape_value`, `_json_artifact_preview`,
   and the `build_parquet_preview` import.
2. In `sidecar/routes/runs.py`, delete `get_run`, `get_run_steps`,
   `get_run_manifest` (lines 79-166). Keep `run_plan` (POST) and the three
   `/runs/project/...` handlers. Drop the now-unused `load_registry`,
   `ProjectNotFoundError`, `ProjectPathMissingError` imports if nothing else
   in the file references them — re-read the file imports before deleting.
3. In `cardre/services/artifact_service.py`, delete `scan_all_stores` and
   `find_artifact`, plus the `load_registry` and `ProjectStore` imports they
   pulled in (verify nothing else in that module uses them).
4. Rewrite existing tests that hit global routes to use project-scoped ones.
   The exhaustive list (grep `client.get(f"/runs/{` and
   `client.get(f"/artifacts/` in `tests/test_sidecar_api.py`):
   - `test_get_run` (line 276): `/runs/{run_id}` → `/runs/project/{pid}/runs/{run_id}`
   - `test_stale_run_not_recovered_by_get` (364): same
   - `test_get_run_steps` (443): `/runs/{run_id}/steps` → project-scoped
   - `test_create_import_run_view` (518): `/runs/{data['run_id']}/steps` (564)
   - `test_get_artifact` (493): `/artifacts/{artifact_id}` → project-scoped metadata
   - `test_get_artifact_not_found` (507): `/artifacts/nonexistent-id` → query a real project with a bogus id; expect 404 `ARTIFACT_NOT_FOUND`
   - `test_artifact_summary` (973), `test_json_artifact_summary` (1057),
     `test_json_artifact_preview` (1086), `test_artifact_preview` (1118),
     `test_artifact_preview_uses_store_artifact_path` (1135),
     `test_parquet_preview_pagination` (1251),
     `test_full_flow_with_params_and_artifacts` (1280): all use
     `/artifacts/{id}/...` → project-scoped
   - `test_manifest_endpoint` (2141): `/runs/{run_id}/manifest` → project-scoped
   - `test_branch_run_returns_403_when_governance_disabled` (2082): `/runs/{run_id}/cancel` — check whether a `/cancel` route exists; if so it's a separate route, leave it; if the test is hitting a deleted global, repoint.
5. Rewrite `test_artifact_preview_uses_store_artifact_path` (lines 1135-1178).
   It currently monkeypatches `artifacts_route.find_artifact`. Replace with a
   project-scoped approach — monkeypatch `get_store_for_project` to return a
   fake store holding the fake artifact:

```python
def test_artifact_preview_uses_store_artifact_path(self, monkeypatch):
    from types import SimpleNamespace
    from sidecar.routes import artifacts as artifacts_route

    calls: list[str] = []
    fake_artifact = SimpleNamespace(
        artifact_id="art-1", artifact_type="report", role="report",
        path="artifacts/report.parquet", physical_hash="p", logical_hash="l",
        media_type="application/vnd.apache.parquet",
        created_at="2026-01-01T00:00:00+00:00", metadata={"row_count": 2},
    )

    class FakeStore:
        root = Path("/tmp/unused")
        def get_artifact(self, artifact_id):
            return fake_artifact if artifact_id == "art-1" else None
        def artifact_path(self, artifact):
            calls.append(artifact.artifact_id)
            return Path("/tmp/explicit-preview.parquet")

    monkeypatch.setattr(artifacts_route, "get_store_for_project",
                        lambda pid: FakeStore())

    def fake_build_parquet_preview(artifact_path, offset, limit, total_rows):
        assert artifact_path == Path("/tmp/explicit-preview.parquet")
        assert (offset, limit, total_rows) == (0, 5, 2)
        return {"total_rows": 2, "columns": [], "rows": []}

    monkeypatch.setattr(artifacts_route, "build_parquet_preview",
                        fake_build_parquet_preview)

    resp = artifacts_route.get_project_artifact_preview(
        "proj-1", "art-1", limit=5, offset=0,
    )
    assert resp.artifact_id == "art-1"
    assert calls == ["art-1"]
```

   Note: `get_store_for_project` must be imported into `artifacts_route`'
   module namespace (top of `artifacts.py`) for `monkeypatch.setattr` to
   take effect — do that import move in Phase 2.

Gate: `pytest tests/test_sidecar_api.py tests/test_api_contracts.py tests/test_project_registry.py tests/test_artifact_guardrail.py -q` green. Then run the full `pytest tests/` and address any stragglers (e.g. `test_legacy_artifact_compatibility.py`, `test_audit_artifact_reads.py` if they reference global routes).

---

### Phase 4 — Red: frontend component tests asserting project-scoped calls

Goal: lock the UI migration before doing it.

Existing pattern to copy: `frontend/src/hooks/__tests__/useRunProgress.test.tsx`
spies on `api.getProjectRun` / `getProjectRunSteps`. Mirror that for the three
leaking components.

#### 4a. RunHistoryTab

Create `frontend/src/components/inspector/__tests__/RunHistoryTab.test.tsx`
(or extend existing). Assert it calls `api.getProjectRunSteps(projectId, runId)`
and **never** `api.getRunSteps`. Because `api.getRunSteps` will be deleted in
Phase 6, the test's failure mode right now (red) is "called the global".

```tsx
import { describe, it, expect, vi } from "vitest";
import { render } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { api } from "../../../api/client";
import { RunHistoryTab } from "../RunHistoryTab";

function withClient(ui: React.ReactNode) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={qc}>{ui}</QueryClientProvider>;
}

describe("RunHistoryTab", () => {
  it("polls project-scoped run steps", async () => {
    const spy = vi.spyOn(api, "getProjectRunSteps").mockResolvedValue({
      run_id: "run1", steps: [],
    } as any);
    render(withClient(
      <RunHistoryTab stepId="import" projectId="prj1" runId="run1" tab="history" />,
    ));
    // let react-query fire
    await new Promise((r) => setTimeout(r, 0));
    expect(spy).toHaveBeenCalledWith("prj1", "run1");
    expect((api as any).getRunSteps).toBeUndefined(); // global must not exist after Phase 6
  });
});
```

Red state: the spy assertion fails because the component calls
`api.getRunSteps(runId)`.

#### 4b. ArtifactSummaryInline and ArtifactPreviewPane

Create `frontend/src/components/__tests__/ArtifactSummaryInline.test.tsx`:

```tsx
it("loads summary via project-scoped route", async () => {
  const sumSpy = vi.spyOn(api, "getProjectArtifactSummary").mockResolvedValue({
    artifact_id: "art1", artifact_type: "dataset", role: "input",
    media_type: "application/vnd.apache.parquet", logical_hash: "h",
    physical_hash: "p", row_count: 10, column_count: 2, summary_preview: null,
  } as any);
  render(withClient(<ArtifactSummaryInline projectId="prj1" artifactId="art1" />));
  await new Promise((r) => setTimeout(r, 0));
  expect(sumSpy).toHaveBeenCalledWith("prj1", "art1");
});
```

Similarly for `ArtifactPreviewPane`, asserting
`api.getProjectArtifactPreview("prj1", "art1", limit, offset)` once
`showPreview` is toggled (or render with `summaryPreview` set so it short-
circuits — for the preview path, drive the toggle in the test).

Gate: all three new frontend tests fail red.

---

### Phase 5 — Green: thread `projectId` and add client methods

Order: client first, then components top-down.

1. **`frontend/src/api/client.ts`** — replace the five global methods. Add the
   two new project-scoped artifact helpers:

```ts
  getProjectRunSteps: (projectId: string, runId: string, opts?: FetchOptions) =>
    fetchJson<RunStepsResponse>(`/runs/project/${projectId}/runs/${runId}/steps`, {
      timeoutMs: 5_000, ...opts,
    }),

  getProjectArtifact: (projectId: string, artifactId: string) =>
    fetchJson<ArtifactResponse>(`/artifacts/project/${projectId}/artifacts/${artifactId}`, {
      timeoutMs: 5_000,
    }),

  getProjectArtifactSummary: (projectId: string, artifactId: string) =>
    fetchJson<ArtifactSummaryResponse>(
      `/artifacts/project/${projectId}/artifacts/${artifactId}/summary`,
      { timeoutMs: 5_000 },
    ),

  getProjectArtifactPreview: (projectId: string, artifactId: string, limit = 100, offset = 0) =>
    fetchJson<ArtifactPreviewResponse>(
      `/artifacts/project/${projectId}/artifacts/${artifactId}/preview?limit=${limit}&offset=${offset}`,
      { timeoutMs: 10_000 },
    ),
```

   Delete: `getRun`, `getRunSteps`, `getArtifact`, `getArtifactSummary`,
   `getArtifactPreview`. Keep `getProjectRun`, `getProjectRunSteps` (already
   present).

2. **`ArtifactRow.tsx`** — accept and forward `projectId`:

```tsx
interface Props {
  item: ArtifactListItem;
  projectId: string;
  expanded: boolean;
  onToggle: () => void;
}
export function ArtifactRow({ item, projectId, expanded, onToggle }: Props) {
  ...
  {expanded && <ArtifactSummaryInline projectId={projectId} artifactId={item.artifact_id} />}
}
```

3. **`ArtifactBrowser.tsx`** — pass `projectId` (it already has it):

```tsx
<ArtifactRow key={item.artifact_id} item={item} projectId={projectId}
  expanded={...} onToggle={...} />
```

4. **`ArtifactSummaryInline.tsx`** — add `projectId` prop, call project-scoped:

```tsx
interface Props { projectId: string; artifactId: string; }
export function ArtifactSummaryInline({ projectId, artifactId }: Props) {
  const { data, isLoading } = useQuery({
    queryKey: ["artifactSummary", projectId, artifactId],
    queryFn: () => api.getProjectArtifactSummary(projectId, artifactId),
    enabled: !!artifactId,
  });
  ...
  <ArtifactPreviewPane
    projectId={projectId}
    artifactId={data.artifact_id}
    mediaType={data.media_type}
    rowCount={data.row_count}
    summaryPreview={data.summary_preview}
  />
}
```

   Update the queryKey to include `projectId` so caches don't collide across
   projects (defensive; ids are UUIDs anyway).

5. **`ArtifactPreviewPane.tsx`** — add `projectId` prop, call project-scoped:

```tsx
interface Props {
  projectId: string;
  artifactId: string;
  mediaType: string;
  rowCount: number | null | undefined;
  summaryPreview: Record<string, unknown> | null | undefined;
}
export function ArtifactPreviewPane({ projectId, artifactId, ... }: Props) {
  const { data: preview, isLoading } = useQuery({
    queryKey: ["artifactPreview", projectId, artifactId, limit, offset],
    queryFn: () => api.getProjectArtifactPreview(projectId, artifactId, limit, offset),
    enabled: showPreview,
  });
  ...
}
```

6. **`RunHistoryTab.tsx`** — already receives `projectId` (currently aliased
   `_projectId`); use it:

```tsx
export function RunHistoryTab({ stepId, projectId, runId, tab }: Props) {
  const { data: runStepsData, isLoading } = useQuery({
    queryKey: ["runSteps", projectId, runId],
    queryFn: () => api.getProjectRunSteps(projectId, runId!),
    enabled: !!runId && tab === "history",
  });
  ...
}
```

7. **`frontend/src/test/server.ts`** — add MSW handlers so any test that
   mounts these components (without per-test spies) gets deterministic
   responses:

```ts
http.get(`${BASE}/artifacts/project/:projectId/artifacts/:artifactId/summary`, () =>
  HttpResponse.json({
    artifact_id: "art1", artifact_type: "dataset", role: "input",
    media_type: "application/vnd.apache.parquet", logical_hash: "h",
    physical_hash: "p", row_count: 0, column_count: 0, summary_preview: null,
  }),
),
http.get(`${BASE}/artifacts/project/:projectId/artifacts/:artifactId/preview`, () =>
  HttpResponse.json({
    artifact_id: "art1", media_type: "application/vnd.apache.parquet",
    row_count: 0, column_count: 0, columns: [], rows: [],
    limit: 100, offset: 0,
  }),
),
```

Gate: Phase 4 frontend tests go green. Run
`npm run test -- src/components/__tests__ src/hooks src/api` and
`npm run test -- src/components/inspector/__tests__`.

---

### Phase 6 — Cleanup: regenerate OpenAPI, typecheck, lint, full test sweep

Run in this order; each must be clean before advancing.

1. **Regenerate types**:
   ```
   python3 scripts/generate-openapi-types.py
   ```
   Expect `frontend/src/api/openapi.json` to lose the six global paths and
   gain the two new project-scoped artifact paths; `schema.d.ts` follows.
2. **Typecheck** (from `frontend/`):
   ```
   npx tsc --noEmit
   ```
   Fix any references to deleted `api.getRun`/`getRunSteps`/`getArtifact`/
   `getArtifactSummary`/`getArtifactPreview` — the compiler will surface them.
   If `schema.d.ts` has a residual `paths["/runs/{run_id}"]` reference in
   hand-written code, that's a missed migration; fix the call site.
3. **Lint**:
   ```
   cd frontend && npm run lint
   ```
4. **Frontend tests**:
   ```
   cd frontend && npm test
   ```
   Per AGENTS.md, the robustness subset is:
   `npm run test -- src/api src/hooks src/components/__tests__/ProjectView`.
5. **Backend tests**:
   ```
   pytest tests/test_sidecar_api.py tests/test_api_contracts.py tests/test_project_registry.py tests/test_artifact_guardrail.py -q
   pytest tests/ -q   # full sweep, slow
   ```
6. **OpenAPI-no-drift check** (commit hygiene, run before committing):
   ```
   python3 scripts/generate-openapi-types.py
   git diff --exit-code frontend/src/api/openapi.json frontend/src/api/schema.d.ts
   ```
   Empty diff confirms committed types match the live app. (The
   `check-line-counts` / `check-doc-references` scripts treat these as
   generated; a non-empty diff after regen means a route wasn't added to the
   committed spec.)

Gate: all of the above green. Then, and only then, commit.

---

## Test inventory (single source of truth)

### New tests to add

| Location | Test | Phase |
| --- | --- | --- |
| `tests/test_sidecar_api.py` (new `TestProjectScopeIsolation`) | `test_project_run_404_for_wrong_project` | 1a |
| same | `test_project_artifact_summary_404_for_wrong_project` | 1b |
| same | `test_project_artifact_preview_404_for_wrong_project` | 1b |
| same | `test_project_artifact_summary_scoped` (happy path) | 1b |
| `frontend/src/components/inspector/__tests__/RunHistoryTab.test.tsx` | asserts `getProjectRunSteps(projectId, runId)` | 4a |
| `frontend/src/components/__tests__/ArtifactSummaryInline.test.tsx` | asserts `getProjectArtifactSummary(projectId, artifactId)` | 4b |
| `frontend/src/components/__tests__/ArtifactPreviewPane.test.tsx` | asserts `getProjectArtifactPreview(projectId, artifactId, limit, offset)` | 4b |

### Existing tests to rewrite (project-scoped)

`tests/test_sidecar_api.py`: `test_get_run` (276),
`test_stale_run_not_recovered_by_get` (364),
`test_get_run_steps` (443),
`test_get_artifact` (493),
`test_get_artifact_not_found` (507),
`test_create_import_run_view` (518, `/runs/{id}/steps` at 564),
`test_artifact_summary` (973),
`test_json_artifact_summary` (1057),
`test_json_artifact_preview` (1086),
`test_artifact_preview` (1118),
`test_artifact_preview_uses_store_artifact_path` (1135),
`test_parquet_preview_pagination` (1251),
`test_full_flow_with_params_and_artifacts` (1280),
`test_manifest_endpoint` (2141),
`test_branch_run_returns_403_when_governance_disabled` (2082 — verify
`/runs/{run_id}/cancel` route existence separately).

### Tests that must NOT depend on scan-all

`test_artifact_filters_by_run_id` (988) and any project-artifacts test must
keep using `/projects/{pid}/artifacts?run_id=...` (already project-scoped).
No new test should rely on `find_artifact` resolving across projects — that
helper is gone.

---

## Files changed (expected)

Backend:
- `sidecar/routes/runs.py` — delete 3 global handlers; trim imports.
- `sidecar/routes/artifacts.py` — delete 3 global handlers; add 2 project-
  scoped; lift `get_store_for_project` import.
- `cardre/services/artifact_service.py` — delete `scan_all_stores`,
  `find_artifact`; trim imports.

Frontend:
- `frontend/src/api/client.ts` — delete 5 global methods; add
  `getProjectArtifactSummary`, `getProjectArtifactPreview`.
- `frontend/src/components/ArtifactRow.tsx` — add `projectId` prop, forward.
- `frontend/src/components/ArtifactBrowser.tsx` — pass `projectId`.
- `frontend/src/components/ArtifactSummaryInline.tsx` — add `projectId`;
  project-scoped query.
- `frontend/src/components/ArtifactPreviewPane.tsx` — add `projectId`;
  project-scoped query.
- `frontend/src/components/inspector/RunHistoryTab.tsx` — use `projectId`;
  project-scoped query.
- `frontend/src/test/server.ts` — add 2 MSW handlers.

Generated (regen, commit):
- `frontend/src/api/openapi.json`
- `frontend/src/api/schema.d.ts`

Tests:
- `tests/test_sidecar_api.py` — rewrite + add `TestProjectScopeIsolation`.
- New frontend component test files (3).

## Migration notes for API consumers

Removed:
- `GET /runs/{run_id}`
- `GET /runs/{run_id}/steps`
- `GET /runs/{run_id}/manifest`
- `GET /artifacts/{artifact_id}`
- `GET /artifacts/{artifact_id}/summary`
- `GET /artifacts/{artifact_id}/preview`

Replacements (project-scoped):
- `GET /runs/project/{project_id}/runs/{run_id}`
- `GET /runs/project/{project_id}/runs/{run_id}/steps`
- `GET /runs/project/{project_id}/runs/{run_id}/manifest`
- `GET /artifacts/project/{project_id}/artifacts/{artifact_id}`
- `GET /artifacts/project/{project_id}/artifacts/{artifact_id}/summary` *(new)*
- `GET /artifacts/project/{project_id}/artifacts/{artifact_id}/preview` *(new)*

Behavior change: a request for a valid id scoped to a project that does not
own it now returns **404** (codes `RUN_NOT_FOUND` / `ARTIFACT_NOT_FOUND`)
instead of 200-via-scan-all. Consumers must carry `project_id` alongside run
and artifact ids. There is no 403 path — wrong scope is "resource does not
exist", not "forbidden".

`scan_all_stores()` and `find_artifact()` are removed from
`cardre.services.artifact_service`; any out-of-tree importer must scope
lookups via `get_store_for_project(project_id)` followed by
`store.get_run` / `store.get_artifact`.

## Future work (not this batch)

- Normalize `/runs/project/{project_id}/runs/{run_id}` →
  `/projects/{project_id}/runs/{run_id}` for REST symmetry with the reports
  routes. Coordinated client + MSW + `useRunProgress` + test migration.
- Apply the same project-scoping pass to the remaining scan-all routes:
  `plans.py`, `projects.py` (list), `comparisons.py`, `branches.py`,
  `reports.py`.
- Consider a `GET /projects/{project_id}/runs/{run_id}/artifacts` listing
  if the UI ever needs run-scoped artifact enumeration without the
  `/projects/{project_id}/artifacts?run_id=` filter.

## Validation context

Validated against the repo on 2026-06-27. Key confirmed facts:

- `frontend/src/hooks/useRunProgress.ts:150-151` already polls
  `api.getProjectRun` / `getProjectRunSteps` — no migration needed there.
- `frontend/src/api/client.ts:349-381` defines the five global methods;
  `getRun`, `getArtifact` have **no UI callers** (safe to delete outright);
  `getRunSteps`, `getArtifactSummary`, `getArtifactPreview` have one caller
  each (listed above).
- `frontend/src/test/server.ts` only mocks project-scoped run routes; the two
  new artifact handlers are additive.
- `cardre/services/project_registry.py:get_store_for_project` raises
  `ProjectNotFoundError` (404) for unknown project_id and
  `ProjectPathMissingError` (410) for missing on-disk path — reuse these for
  all project-scoped routes; do not invent new error codes.
- `cardre/store/project_store.py:299-311` provides `get_artifact`,
  `list_artifacts`, `artifact_path` — sufficient for the new routes; no store
  changes required.
- The `/runs/project/{project_id}/runs/{run_id}` path's doubled `runs` is
  awkward but stable; normalization is deferred to avoid compounding churn.