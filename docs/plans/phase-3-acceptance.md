# Phase 3 — Acceptance

## Goal

Deliver a fixed-pathway desktop GUI that a user can install, run, and complete the full Scorecard Pathway without touching SQLite, Python, Parquet paths, or JSON directly.

## Scope

- Desktop GUI via Tauri/React on top of the existing HTTP API.
- Fixed pathway with real backend step IDs (not dummies).
- Manual binning editor that reads upstream artefacts and validates overrides.
- Stale-downstream detection after param edits.
- Artifact summary/preview.
- Manifest evidence at pathway end.
- E2E test coverage for the full pathway.

## Acceptance criteria

A user can:

1. **Create a project** via the desktop UI or API.
2. **Import the German Credit dataset** (the only supported source).
3. **Run the Scorecard Pathway**  — all 20+ steps execute successfully from import through cutoff analysis.
4. **Open the pathway view** and see step statuses (succeeded/failed) with stale indicators.
5. **Inspect outputs** via the artifact browser — summary metadata and preview content.
6. **Open the manual binning editor**  — see source bins from fine-classing pre-populated.
7. **Preview an invalid bin edit**  — UI shows validation errors.
8. **Preview a valid bin edit**  — UI shows refined bins.
9. **Save a bin edit**  — creates a new plan version.
10. **Check stale downstream state**  — downstream steps show amber stale indicator.
11. **Re-run**  — stale steps re-execute, carried-forward steps retain evidence.
12. **View validation / cutoff / manifest artefacts**  — final outputs are inspectable.
13. **Close and reopen the app**  — the project and its state survive.
14. **All 126 backend tests pass.** 
15. **TypeScript compiles clean, Vite production build succeeds.**

## What was delivered

| Criterion | Status | Notes |
|-----------|--------|-------|
| Create project | ✅ | WelcomeScreen → API |
| Import dataset | ✅ | WelcomeScreen + DatasetImport components |
| Run pathway | ✅ | TopBar "Run Pathway" button |
| Pathway view | ✅ | PathwayView + StepCard with status/stale display |
| Inspect outputs | ✅ | ArtifactBrowser summary + preview |
| Artifact browser | ✅ | With role/type filters |
| Manual binning editor | ✅ | Full override CRUD with upstream read |
| Preview invalid edit | ✅ | Red diagnostic box on `valid: false` |
| Preview valid edit | ✅ | Green confirmation with refined bin JSON |
| Save bin edit | ✅ | Creates new plan version via API |
| Stale downstream state | ✅ | Amber dot on StepCard, stale banner in StepInspector |
| Re-run after edit | ✅ | TopBar "Run Pathway" with current plan version |
| View validation/cutoff/manifest | ✅ | Via ArtifactBrowser (generic) |
| Close/reopen persistence | ❌ | No `localStorage` or URL state — app always returns to WelcomeScreen |
| 126 tests pass | ✅ | `pytest` — 126/126 |
| TS compiles | ✅ | `tsc --noEmit` — clean |
| Vite builds | ✅ | 234 KB production bundle |

## Known gaps (not blocking Phase 3)

These are tracked as separate GitHub issues. See rough-edges list.

- [#13](https://github.com/statcat2017/cardre/issues/13) Reject manual-binning overrides for variables not selected by variable-selection.
- [#14](https://github.com/statcat2017/cardre/issues/14) Add better project-registry diagnostics if a registered .cardre folder is deleted/moved.
- [#15](https://github.com/statcat2017/cardre/issues/15) Add explicit carried-forward status metadata, not just reused succeeded status.
- [#16](https://github.com/statcat2017/cardre/issues/16) Improve unsupported/large artefact previews.
- [#17](https://github.com/statcat2017/cardre/issues/17) Add loading/progress feedback for long synchronous runs.
- [#18](https://github.com/statcat2017/cardre/issues/18) Add first-run/help copy for hidden import plan vs Scorecard Pathway run evidence.
- [#19](https://github.com/statcat2017/cardre/issues/19) Fix Tauri packaging: missing system deps (glib, pkg-config), no sidecar binary, stale Cargo feature.

## Baseline API contract (frozen for Phase 4)

| Method | Endpoint | Purpose |
|--------|----------|---------|
| GET | `/projects/{project_id}/plans` | List plans for a project |
| GET | `/plans/{plan_id}` | Plan detail with step statuses |
| POST | `/plans/{plan_id}/steps/{step_id}/params` | Update step params |
| POST | `/runs` | Execute a plan version |
| GET | `/projects/{project_id}/runs` | List runs for a project |
| GET | `/projects/{project_id}/artifacts` | List artefacts with filters |
| GET | `/artifacts/{artifact_id}/summary` | Artefact summary metadata |
| GET | `/artifacts/{artifact_id}/preview` | Artefact preview content |
| GET | `/plans/{plan_id}/steps/manual-binning/editor-state` | Binning editor state |
| POST | `/plans/{plan_id}/steps/manual-binning/preview` | Validate bin overrides |
| POST | `/projects` | Create project |
| GET | `/projects/{project_id}` | Project detail |
| POST | `/datasets/import` | Import dataset |
| GET | `/runs/{run_id}` | Get run |
| GET | `/runs/{run_id}/steps` | Get run steps |
| GET | `/artifacts/{artifact_id}` | Get artefact |
| GET | `/health` | Health check |
