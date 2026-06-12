# Phase 1B Technical Addendum — Desktop Shell

*Informed by: phase-1-technical-implementation-plan.md, cardre-application-plan.md, plan-reviews/005, 006, 007, 008, 009, 012, CONTEXT.md, ADR-0001.*

## Objective

Prove the Tauri shell can manage a bundled/local FastAPI sidecar, React can
display backend state, and the full round-trip (create project → import German
Credit → run proof pathway → view step statuses) works from a desktop GUI.

The shell is minimal on purpose — no real model editing, no branching GUI, no
export. Phase 2+ adds those.

## Project Layout

```
cardre/
├── cardre/                  # Python engine (already exists)
├── tests/                    # Python tests (already exist)
├── frontend/                 # New: Tauri + React project
│   ├── src/                  # React source
│   │   ├── App.tsx
│   │   ├── api/              # API client
│   │   │   └── client.ts
│   │   ├── components/       # React components
│   │   │   ├── ProjectView.tsx
│   │   │   ├── StepCard.tsx
│   │   │   ├── StepCardGrid.tsx
│   │   │   ├── ArtifactList.tsx
│   │   │   ├── ProfileOutput.tsx
│   │   │   └── StatusBadge.tsx
│   │   ├── types.ts           # Shared TypeScript interfaces
│   │   └── main.tsx
│   ├── src-tauri/             # Tauri Rust shell
│   │   ├── src/main.rs
│   │   ├── Cargo.toml
│   │   └── tauri.conf.json
│   ├── index.html
│   ├── package.json
│   ├── tsconfig.json
│   └── vite.config.ts
├── sidecar/                   # New: FastAPI sidecar package
│   ├── __init__.py
│   ├── main.py                # FastAPI app, uvicorn entry point
│   ├── models.py              # Pydantic request/response models
│   ├── routes/
│   │   ├── __init__.py
│   │   ├── health.py
│   │   ├── projects.py
│   │   ├── datasets.py
│   │   ├── plans.py
│   │   ├── runs.py
│   │   └── artifacts.py
│   └── proof_pathway.py       # Hardcoded proof plan
└── pyproject.toml
```

## Technology Versions (Pinned)

| Layer | Choice | Rationale |
|-------|--------|-----------|
| Desktop shell | Tauri v2 (Rust) | `externalBin` for sidecar bundling, cross-platform |
| Frontend framework | React 18 + TypeScript 5 | Plan reviews 006, 002 |
| Build tool | Vite 6 | Fast dev server, native ESM |
| State / data fetching | React Query (TanStack Query v5) | Polling API without local staleness logic |
| CSS | Tailwind CSS v4 | Minimal utility-first, no component library overhead |
| API framework | FastAPI 0.115+ | Async, built-in OpenAPI |
| ASGI server | uvicorn 0.32+ | Standard |
| Sidecar bundling | PyInstaller 6+ | Per plan reviews 005, 007, 008 |
| Frontend tests | Vitest + Playwright | API-level with pytest, e2e with Playwright |

## Slice 8: FastAPI Sidecar

### Entry Point (`sidecar/main.py`)

```python
import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sidecar.routes import health, projects, datasets, plans, runs, artifacts

app = FastAPI(title="cardre-api", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # localhost only in dev; Tauri custom protocol in prod
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router)
app.include_router(projects.router)
app.include_router(datasets.router)
app.include_router(plans.router)
app.include_router(runs.router)
app.include_router(artifacts.router)

def main():
    import sys
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8752
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="info")

if __name__ == "__main__":
    main()
```

### Port Selection Protocol

The sidecar accepts a single CLI argument: the port to bind.

```bash
# Tauri shell chooses the port, sidecar binds to it
cardre-api 18763
```

Tauri port selection algorithm (in Rust):

```
1. Bind a TCP listener to 127.0.0.1:0 (OS-assigned ephemeral port)
2. Read the assigned port from the listener
3. Drop the listener
4. Pass port as CLI arg to sidecar
5. If sidecar fails to start, retry with a new ephemeral port (max 3 tries)
6. Surface startup failure with actionable message
```

This avoids port conflicts and guarantees a free port before launching the
sidecar. The ephemeral port window (typically 32768-60999 on Linux, 49152-65535
on Windows/macOS) ensures no collision with common services.

### CORS

Development: allow `*` origins (Vite dev server on random port).  
Production: Tauri's custom `tauri://` protocol is added automatically by the
Tauri Rust layer per the Tauri v2 security model. No additional CORS config
needed in production.

### API Endpoint Specifications

All endpoints return JSON. Error responses follow a uniform shape:

```json
{"detail": {"code": "ERROR_CODE", "message": "Human-readable message"}}
```

#### `GET /health`

No request body.

Response `200`:
```json
{
  "status": "ok",
  "cardre_version": "0.1.0"
}
```

#### `POST /projects`

Create a new Cardre project at a user-chosen directory path.

Request body:
```json
{
  "path": "/home/user/my-scorecard.cardre",
  "name": "My Scorecard"
}
```

Response `201`:
```json
{
  "project_id": "uuid-string",
  "path": "/home/user/my-scorecard.cardre",
  "name": "My Scorecard",
  "created_at": "2026-01-15T10:30:00"
}
```

Implementation:
```python
store = ProjectStore(path)
store.initialize()
project_id = store.create_project(name)
# Store the project path -> project_id mapping in a local registry file
# at ~/.cardre/projects.json so the app can list recent projects.
return {"project_id": project_id, "path": str(path), ...}
```

#### `GET /projects/{project_id}`

Response `200`:
```json
{
  "project_id": "uuid-string",
  "name": "My Scorecard",
  "path": "/home/user/my-scorecard.cardre",
  "created_at": "2026-01-15T10:30:00",
  "plan_count": 1,
  "run_count": 3
}
```

Response `404`:
```json
{"detail": {"code": "PROJECT_NOT_FOUND", "message": "No project with ID ..."}}
```

#### `POST /datasets/import`

Import a dataset from a local file path into the project.

Request body:
```json
{
  "project_id": "uuid-string",
  "source_path": "/home/user/german.data",
  "dataset_id": "uci-statlog-german-credit"
}
```

Implementation opens/creates the project store, creates an import step plan,
runs the executor on just the import node, and registers the artifact.

Response `201`:
```json
{
  "artifact_id": "uuid-string",
  "artifact_type": "dataset",
  "role": "input",
  "path": "datasets/abc123...-german-credit.parquet",
  "physical_hash": "sha256-hex",
  "logical_hash": "sha256-hex",
  "row_count": 1000,
  "column_count": 21
}
```

#### `GET /plans/{plan_id}`

Returns the plan with its latest version and step status/staleness.

Response `200`:
```json
{
  "plan_id": "uuid-string",
  "project_id": "uuid-string",
  "name": "Proof Pathway",
  "latest_version_id": "uuid-string",
  "steps": [
    {
      "step_id": "import",
      "node_type": "cardre.import_dataset",
      "category": "transform",
      "status": "succeeded",
      "is_stale": false,
      "position": 0
    },
    {
      "step_id": "profile",
      "node_type": "cardre.profile_dataset",
      "category": "transform",
      "status": "succeeded",
      "is_stale": false,
      "position": 1
    }
  ]
}
```

Status is derived from the latest run's `run_steps` for this plan version.
`is_stale` is computed by `PlanExecutor.compute_staleness()`.

#### `POST /runs`

Execute a plan version.

Request body:
```json
{
  "project_id": "uuid-string",
  "plan_version_id": "uuid-string"
}
```

Implementation opens the project store, creates a `PlanExecutor` with
`NodeRegistry.with_defaults()`, calls `run_plan_version()`.

The executor runs synchronously for Phase 1B (small dataset, proof nodes only).
The `POST` call blocks until the run completes. Phase 2+ moves to background
execution with polling.

Response `201`:
```json
{
  "run_id": "uuid-string",
  "plan_version_id": "uuid-string",
  "status": "succeeded",
  "started_at": "2026-01-15T10:30:00",
  "finished_at": "2026-01-15T10:30:02"
}
```

On failure, `status` is `"failed"` and `errors` is populated.

#### `GET /runs/{run_id}`

Response `200`:
```json
{
  "run_id": "uuid-string",
  "plan_version_id": "uuid-string",
  "status": "succeeded",
  "started_at": "2026-01-15T10:30:00",
  "finished_at": "2026-01-15T10:30:02",
  "step_count": 6,
  "metadata": {}
}
```

#### `GET /runs/{run_id}/steps`

Response `200`:
```json
{
  "run_id": "uuid-string",
  "steps": [
    {
      "run_step_id": "uuid-string",
      "step_id": "import",
      "node_type": "cardre.import_dataset",
      "status": "succeeded",
      "started_at": "...",
      "finished_at": "...",
      "input_artifact_ids": [],
      "output_artifact_ids": ["uuid..."],
      "warnings": [],
      "errors": []
    }
  ]
}
```

#### `GET /artifacts/{artifact_id}`

Response `200`:
```json
{
  "artifact_id": "uuid-string",
  "artifact_type": "dataset",
  "role": "input",
  "path": "datasets/abc...-german-credit.parquet",
  "physical_hash": "sha256-hex",
  "logical_hash": "sha256-hex",
  "media_type": "application/vnd.apache.parquet",
  "created_at": "...",
  "metadata": {
    "source_dataset_id": "uci-statlog-german-credit",
    "row_count": 1000,
    "column_count": 21
  }
}
```

### Proof Pathway Plan

Hardcoded in `sidecar/proof_pathway.py`, created once on first `/plans` access:

```python
PROOF_PATHWAY_STEPS = [
    {"step_id": "import", "node_type": "cardre.import_dataset", ...},
    {"step_id": "profile", "node_type": "cardre.profile_dataset", ...},
    {"step_id": "validate-target", "node_type": "cardre.validate_binary_target",
     "params": {"target_column": "credit_risk_class"}, ...},
    {"step_id": "split", "node_type": "cardre.split_train_test_oot",
     "params": {"train_fraction": 0.6, "test_fraction": 0.2,
                "oot_fraction": 0.2, "method": "random", "random_seed": 42}, ...},
    {"step_id": "dummy-fit", "node_type": "cardre.dummy_fit", ...},
    {"step_id": "dummy-apply", "node_type": "cardre.dummy_apply", ...},
]
```

When a project is created, this proof pathway plan is automatically registered
in SQLite via `store.create_plan()` + `store.create_plan_version()`.

### Sidecar Dependencies

Add to `pyproject.toml`:
```toml
[project.optional-dependencies]
sidecar = ["fastapi", "uvicorn"]
```

Phase 1B sidecar is installed as `pip install cardre[sidecar]` or bundled via
PyInstaller.

### PyInstaller Bundle

```bash
pyinstaller --onefile --name cardre-api sidecar/main.py
```

Outputs a single `dist/cardre-api` executable that Tauri launches via
`externalBin`. Target size: ~80-120 MB (Python + NumPy/Polars/FastAPI).

## Slice 9: Tauri/React Shell

### Vite Config (`frontend/vite.config.ts`)

```ts
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: { port: 1420, strictPort: false },
  build: { outDir: "dist" },
});
```

### Tauri Config (`frontend/src-tauri/tauri.conf.json`)

```json
{
  "$schema": "https://raw.githubusercontent.com/nicholasgorski/tauri-v2-schema/main/tauri.conf.json",
  "productName": "Cardre",
  "version": "0.1.0",
  "identifier": "com.cardre.app",
  "build": {
    "frontendDist": "../dist",
    "devUrl": "http://localhost:1420",
    "beforeDevCommand": "npm run dev",
    "beforeBuildCommand": "npm run build"
  },
  "app": {
    "windows": [{
      "title": "Cardre",
      "width": 1280,
      "height": 860,
      "resizable": true
    }],
    "security": {
      "csp": "default-src 'self'; connect-src 'self' http://127.0.0.1:*; style-src 'self' 'unsafe-inline'"
    }
  },
  "bundle": {
    "active": true,
    "icon": ["icons/icon.png"],
    "externalBin": ["binaries/cardre-api"]
  }
}
```

The `externalBin` entry points to a PyInstaller-bundled binary placed at
`frontend/src-tauri/binaries/cardre-api-{target-triple}`.

### Tauri Rust — Sidecar Lifecycle (`src-tauri/src/main.rs`)

```rust
fn main() {
    tauri::Builder::default()
        .setup(|app| {
            let port = reserve_port();           // 1. choose port
            let (mut rx, child) = start_sidecar(app, port);  // 2. start
            wait_for_health(port);               // 3. wait /health
            let api_url = format!("http://127.0.0.1:{}", port);
            app.manage(AppState { api_url });    // 4. pass URL to React
            capture_logs(rx);                    // 5. capture logs
            // 6. shutdown on app.exit() via Drop
            // 7. surface failures via tauri::dialog
            Ok(())
        })
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}

fn reserve_port() -> u16 {
    let listener = std::net::TcpListener::bind("127.0.0.1:0").unwrap();
    listener.local_addr().unwrap().port()
}

fn start_sidecar(app: &tauri::App, port: u16) -> (CommandChildEventReceiver, CommandChild) {
    let (mut rx, child) = app.shell()
        .sidecar("cardre-api")
        .expect("failed to create sidecar command")
        .args([port.to_string()])
        .spawn()
        .expect("failed to spawn sidecar");
    (rx, child)
}

fn wait_for_health(port: u16) {
    let url = format!("http://127.0.0.1:{}/health", port);
    for _ in 0..30 {
        if reqwest::blocking::get(&url).is_ok() { return; }
        std::thread::sleep(std::time::Duration::from_millis(500));
    }
    panic!("Sidecar did not become healthy within 15 seconds");
}
```

### React Component Tree

```
<App>
  ├── <WelcomeScreen>        (shown when no project is open)
  │   ├── <CreateProjectForm>
  │   └── <OpenProjectForm>
  └── <ProjectView>          (shown when a project is loaded)
      ├── <ProjectHeader>    (project name, path, run button)
      ├── <StepCardGrid>
      │   └── <StepCard> x N
      │       ├── <StatusBadge>  (not_run/queued/running/succeeded/failed/cancelled)
      │       └── stale marker  (yellow dot if is_stale)
      ├── <ArtifactList>
      │   └── artifact rows (type, role, hash, created_at)
      └── <ProfileOutput>    (JSON view of profile report, if available)
```

### React State & Data Flow

No local staleness inference. The `api/` layer polls endpoints, React Query
caches responses and triggers re-renders:

```
React Query (5s poll) → GET /projects/{id} → render StepCardGrid
React Query (5s poll) → GET /runs/{latest_id}/steps → render statuses
React Query (on action) → GET /plans/{id} → render is_stale markers
React Query (on click) → GET /artifacts/{id} → render detail
```

### Key React Components

**App.tsx** — State: `currentProjectId: string | null`. Routes between
WelcomeScreen and ProjectView.

**ProjectView.tsx** — On mount: fetches plan + latest run. Displays
StepCardGrid and sidebar (ArtifactList + ProfileOutput). "Run" button calls
`POST /runs` then refetches plan state.

**StepCard.tsx** — Props: `{ step_id, node_type, category, status, is_stale }`.
Renders as a card with status badge and stale dot.

**StatusBadge.tsx** — Maps status string to color: not_run=gray,
queued=blue, running=yellow (pulsing), succeeded=green, failed=red,
cancelled=gray.

### API Client (`frontend/src/api/client.ts`)

```typescript
const BASE = window.__API_URL__ || "http://127.0.0.1:8752";

async function fetchJson<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    ...init,
    headers: { "Content-Type": "application/json", ...init?.headers },
  });
  if (!res.ok) throw new ApiError(res.status, await res.json());
  return res.json();
}

export const api = {
  health:        ()             => fetchJson<HealthResponse>("/health"),
  createProject: (body: CreateProjectBody) => fetchJson<ProjectResponse>("/projects", { method: "POST", body: JSON.stringify(body) }),
  getProject:    (id: string)   => fetchJson<ProjectResponse>(`/projects/${id}`),
  importDataset: (body: ImportBody) => fetchJson<ArtifactResponse>("/datasets/import", { method: "POST", body: JSON.stringify(body) }),
  getPlan:       (id: string)   => fetchJson<PlanResponse>(`/plans/${id}`),
  runPlan:       (body: RunBody) => fetchJson<RunResponse>("/runs", { method: "POST", body: JSON.stringify(body) }),
  getRun:        (id: string)   => fetchJson<RunResponse>(`/runs/${id}`),
  getRunSteps:   (id: string)   => fetchJson<RunStepsResponse>(`/runs/${id}/steps`),
  getArtifact:   (id: string)   => fetchJson<ArtifactResponse>(`/artifacts/${id}`),
};
```

The Tauri Rust layer sets `window.__API_URL__` before mounting React, using
the port from the sidecar startup sequence.

### TypeScript Types (`frontend/src/types.ts`)

```typescript
interface HealthResponse {
  status: string;
  cardre_version: string;
}

interface ProjectResponse {
  project_id: string;
  path: string;
  name: string;
  created_at: string;
}

interface CreateProjectBody {
  path: string;
  name: string;
}

interface StepStatus {
  step_id: string;
  node_type: string;
  category: string;
  status: StepStatusCode;
  is_stale: boolean;
  position: number;
}

type StepStatusCode = "not_run" | "queued" | "running" | "succeeded" | "failed" | "cancelled";

interface PlanResponse {
  plan_id: string;
  project_id: string;
  name: string;
  latest_version_id: string;
  steps: StepStatus[];
}

interface RunBody {
  project_id: string;
  plan_version_id: string;
}

interface RunResponse {
  run_id: string;
  plan_version_id: string;
  status: string;
  started_at: string;
  finished_at: string | null;
  step_count?: number;
}

interface RunStepsResponse {
  run_id: string;
  steps: RunStepResponse[];
}

interface RunStepResponse {
  run_step_id: string;
  step_id: string;
  node_type: string;
  status: string;
  started_at: string;
  finished_at: string | null;
  input_artifact_ids: string[];
  output_artifact_ids: string[];
  warnings: string[];
  errors: string[];
}

interface ArtifactResponse {
  artifact_id: string;
  artifact_type: string;
  role: string;
  path: string;
  physical_hash: string;
  logical_hash: string;
  media_type: string;
  created_at: string;
  metadata: Record<string, unknown>;
}

interface ImportBody {
  project_id: string;
  source_path: string;
  dataset_id: string;
}
```

### Frontend Dev Workflow

```bash
# Terminal 1: FastAPI sidecar
cd cardre
pip install -e ".[sidecar]"
python -m sidecar.main 8752

# Terminal 2: React dev server
cd cardre/frontend
npm install
VITE_API_URL=http://127.0.0.1:8752 npm run dev

# Terminal 3: Tauri (optional, uses Vite dev URL from config)
cd cardre/frontend
npx tauri dev
```

Production: `npx tauri build` produces an installer containing the React
production bundle + PyInstaller-bundled sidecar binary.

## Acceptance Tests

Follow existing `test_phase1.py` patterns (pytest for API, PlanExecutor for
integration).

### API Integration Tests (`tests/test_sidecar_api.py`)

```python
"""Test FastAPI sidecar endpoints against a live uvicorn server."""

def test_health_returns_ok(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"

def test_create_project(client, tmp_path):
    proj_path = tmp_path / "test.cardre"
    resp = client.post("/projects", json={"path": str(proj_path), "name": "Test"})
    assert resp.status_code == 201
    data = resp.json()
    assert data["name"] == "Test"
    assert (proj_path / "cardre.sqlite").exists()

def test_import_german_credit(client, sample_german_credit, project):
    resp = client.post("/datasets/import", json={
        "project_id": project["project_id"],
        "source_path": str(sample_german_credit),
        "dataset_id": "uci-statlog-german-credit",
    })
    assert resp.status_code == 201
    assert resp.json()["artifact_type"] == "dataset"

def test_run_proof_pathway(client, project_with_data):
    plan = client.get(f"/plans/{project_with_data['plan_id']}").json()
    resp = client.post("/runs", json={
        "project_id": project_with_data["project_id"],
        "plan_version_id": plan["latest_version_id"],
    })
    assert resp.status_code == 201
    assert resp.json()["status"] == "succeeded"

def test_run_steps_have_statuses(client, completed_run):
    resp = client.get(f"/runs/{completed_run['run_id']}/steps")
    assert resp.status_code == 200
    steps = resp.json()["steps"]
    assert len(steps) > 0
    for step in steps:
        assert step["status"] in ("succeeded", "failed")
```

### E2E Tests (Playwright, `frontend/tests/`)

```
- app launches → window title is "Cardre"
- sidecar starts → /health returns 200 within 15s
- create project → project dir + SQLite created
- import dataset → artifact registered in SQLite
- run pathway → all steps show "succeeded" status
- stale state → step card shows stale dot after param change
```

## Definition Of Done (Phase 1B, appended to Phase 1A Done list)

- [ ] Sidecar starts with `GET /health` returning `200`
- [ ] `POST /projects` creates a `.cardre/` directory with SQLite + subdirs
- [ ] `POST /datasets/import` ingests German Credit into canonical Parquet
- [ ] Proof pathway plan is auto-registered on project creation
- [ ] `POST /runs` executes all proof steps and returns `succeeded`
- [ ] `GET /plans/{plan_id}` returns step statuses and `is_stale` markers
- [ ] `GET /runs/{run_id}/steps` returns per-step evidence
- [ ] Tauri shell starts sidecar, waits for health, passes URL to React
- [ ] React renders step cards with status badges and stale dots
- [ ] React renders artifact list with type/role/hash
- [ ] "Run" button triggers execution and displays updated statuses
- [ ] Shutdown stops sidecar process cleanly
- [ ] Failed sidecar startup shows actionable error to user
