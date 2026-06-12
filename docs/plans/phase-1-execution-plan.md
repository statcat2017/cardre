# Phase 1 Execution Plan

Phase 1 proves Cardre's foundation before building the full scorecard engine or
GUI. The goal is not modelling accuracy. The goal is a reproducible local engine
that can import datasets, store immutable artifacts, execute a fixed pathway
template, replay changed steps, and expose that through a minimal desktop shell.

## Test Data

Use the datasets documented in `docs/data-sources/phase-1-datasets.json`:

- UCI Statlog German Credit Data: small deterministic smoke fixture.
- UCI Default of Credit Card Clients: medium-size import/split/profiling fixture.

Raw downloads live locally under `input/credit/` and are ignored by git.

## Phase 1A: Engine And Storage Proof

### Objectives

- Define the local project storage contract.
- Store metadata in SQLite and artifacts on the filesystem.
- Convert imported data into canonical immutable artifacts.
- Record step execution evidence without mutating history.
- Prove staleness and replay semantics on a tiny DAG-capable plan.
- Prove split role enforcement with train/test/OOT artifacts.

### Work Items

1. Define SQLite schema.
   - `projects`
   - `plans`
   - `plan_versions`
   - `plan_steps`
   - `runs`
   - `run_steps`
   - `artifacts`
   - `warnings`
   - `errors`

2. Define filesystem artifact layout.
   - project-local `artifacts/`
   - project-local `datasets/`
   - content-addressed file naming
   - metadata references in SQLite only

3. Implement core storage objects.
   - `ProjectStore`
   - `ArtifactRef`
   - `PlanVersion`
   - `StepSpec`
   - `PipelineRun`
   - `RunStep`

4. Implement artifact hashing.
   - `physical_hash` from raw bytes
   - `logical_hash` from canonical content
   - canonical JSON hashing for definition artifacts
   - canonical tabular hashing for imported datasets

5. Implement minimal node registry.
   - node type identifier
   - implementation version
   - params schema
   - input/output artifact contract
   - category: `fit`, `apply`, `selection`, `refinement`, `transform`

6. Implement initial built-in proof nodes.
   - import CSV/text dataset
   - profile dataset
   - validate binary target
   - train/test/OOT split
   - dummy fit node that produces a definition artifact
   - dummy apply node that consumes split data plus a definition artifact

7. Implement executor.
   - topological execution
   - parent run-step dependency tracking
   - role-based artifact access validation
   - execution fingerprint generation
   - computed staleness detection
   - replay changed step and descendants only

8. Implement dataset fixture adapters.
   - German Credit raw text to canonical table
   - Taiwan Default local Excel/converted source handling deferred if Excel support
     is not yet available; use manifest and archive verification first

### Acceptance Tests

- Import German Credit and create a canonical tabular artifact.
- Re-import German Credit and get the same logical hash.
- Create a split step and produce immutable `train`, `test`, and `oot` artifacts.
- Verify each split artifact carries an immutable role.
- Run a dummy build-stream step that consumes `train` only.
- Run a dummy apply-stream step that consumes `train`, `test`, and `oot` plus the
  build-stream definition artifact.
- Prove a fit node cannot consume `test` or `oot` artifacts.
- Change split params and verify downstream steps become stale.
- Replay from the changed step and preserve old run records.
- Verify execution fingerprints include plan version, step params hash, parent
  run-step IDs, input logical hashes, output logical hashes, node version, and
  runtime metadata.

### Deliverables

- SQLite schema migration/initialisation.
- Filesystem artifact store.
- Node registry and executor.
- Dataset import proof using German Credit.
- Cross-stream artifact wiring test.
- Reproducibility/staleness test suite.

## Phase 1B: Desktop Shell Proof

### Objectives

- Prove the app can launch as a local desktop shell.
- Prove the Tauri shell can manage a bundled/local sidecar.
- Prove React can create/open a local project and trigger a backend run.
- Keep the GUI minimal: no full scorecard modelling yet.

### Work Items

1. Scaffold Tauri app.
2. Scaffold React/TypeScript frontend.
3. Scaffold FastAPI sidecar.
4. Add `/health` endpoint.
5. Add create/open project API.
6. Add dataset import API for Phase 1 fixtures.
7. Add run API for the dummy fixed pathway.
8. Add minimal pathway view showing step status and stale markers.
9. Add sidecar lifecycle handling.
   - choose localhost port
   - start sidecar
   - wait for health
   - capture logs
   - shut down cleanly
10. Add installer smoke test target.

### Acceptance Tests

- Desktop shell launches.
- Sidecar starts and `/health` passes.
- User can create/open a local project.
- User can import German Credit from local disk.
- User can run the dummy pathway.
- UI shows succeeded/failed/stale status from API state, not local inference.
- Project writes SQLite records and artifact files locally.
- App shutdown stops the sidecar cleanly.

## Out Of Scope For Phase 1

- Real fine classing.
- WOE/IV calculation.
- Logistic regression.
- Manual bin editor.
- Score scaling.
- Full governance report.
- Arbitrary DAG editing.
- Production packaging hardening beyond smoke proof.

## Next Gate

Phase 1 is complete when the engine can run the proof pathway over German Credit
with durable artifacts, reproducible hashes, replay/staleness semantics, and the
desktop shell can trigger and display that run through the local sidecar.
