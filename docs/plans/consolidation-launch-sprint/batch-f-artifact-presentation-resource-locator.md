# Batch F — Artifact Presentation and Resource Locator

## Goal

Standardize artifact summary/preview/evidence presentation and cross-project
ID lookup. Today the artifact browser and step evidence inspector can disagree
about whether a JSON artifact is available, unsupported, stale, or partially
parseable, and cross-project ID scans handle missing paths and duplicate IDs
inconsistently.

## Context you must read first

- `sidecar/routes/artifacts.py:25` — `_shape_value` (route-local JSON shape
  helper).
- `sidecar/routes/artifacts.py:61` — `_json_artifact_preview` (route-local
  JSON preview).
- `sidecar/routes/artifacts.py:101` — `get_artifact_summary`.
- `sidecar/routes/artifacts.py:130` — `get_artifact_preview`.
- `sidecar/routes/evidence.py:26` — `_to_item`, a separate semantic summary
  with parsed payload, status, stale flag, warnings.
- `cardre/services/artifact_service.py:18` — `scan_all_stores` and
  `find_artifact:25` (cross-project artifact scan).
- `cardre/services/artifact_service.py:33` — `build_json_summary_preview`.
  Grep confirms the only hit is its own definition — it is unused.
- `cardre/services/artifact_service.py:46` — `build_parquet_preview` (keep;
  parquet preview stays here).
- `sidecar/routes/runs.py:253` — `get_run` scans the registry.
- `sidecar/routes/comparisons.py:52` — `get_branch_comparison` scans the
  registry, does not skip missing paths.
- `sidecar/routes/branches.py:60` — `get_branch` scans the registry when
  `project_id` is absent.
- `sidecar/routes/plans.py:43` — `get_plan` scans the registry when
  `project_id` is absent.
- `sidecar/routes/plans.py:128` — `get_workflow_guidance` scans the registry.
- `cardre/evidence.py` — `ArtifactEvidenceReader.summarise_artifact` and
  `read_optional`.
- `cardre/_evidence/summaries.py` — `summarise`.
- `docs/plans/consolidation-launch-sprint/README.md` — cross-cutting rules.

## Prerequisite

Batch A is recommended (for `EvidenceResolver` on the evidence route), but
not strictly required. This batch can run in Wave 2 alongside B and D.

## Changes

### 1. Create `ArtifactPresentationService`

New file `cardre/services/artifact_presentation_service.py`.

```python
from dataclasses import dataclass
from typing import Any
from cardre.evidence import ArtifactEvidenceReader, EvidenceKind
from cardre.store import ProjectStore


@dataclass
class ArtifactPresentation:
    artifact_id: str
    artifact_type: str
    role: str
    media_type: str
    logical_hash: str
    physical_hash: str
    row_count: int | None
    column_count: int | None
    summary_preview: dict[str, Any] | None
    evidence_kind: str | None
    unsupported_kind: bool


@dataclass
class ArtifactPreview:
    artifact_id: str
    media_type: str
    json_content: dict[str, Any] | None
    row_count: int | None
    column_count: int | None
    columns: list[dict] | None
    rows: list[dict] | None


class ArtifactPresentationService:
    def __init__(self, store: ProjectStore) -> None: ...

    def summarise_artifact(
        self, artifact_id: str, *, include_staleness: bool = False,
        context: dict | None = None,
    ) -> ArtifactPresentation | None: ...

    def preview_artifact(
        self, artifact_id: str, limit: int = 100, offset: int = 0,
    ) -> ArtifactPreview | None: ...
```

Move `_shape_value` and `_json_artifact_preview` from
`sidecar/routes/artifacts.py` into this service. The semantic evidence
summarisation logic from `sidecar/routes/evidence.py:_to_item:26` (parsed
payload, status, stale flag, warnings) also lives here, so the artifact
summary route and the run evidence route report the same `evidence_kind`,
`unsupported_kind`, and warnings for the same artifact.

### 2. Delete unused `build_json_summary_preview`

In `cardre/services/artifact_service.py:33`, delete
`build_json_summary_preview`. It has no callers. Grep confirms only the
definition exists.

### 3. Migrate artifact routes

In `sidecar/routes/artifacts.py`:

- `get_artifact_summary:101` calls
  `ArtifactPresentationService.summarise_artifact`. The route maps the
  result onto `ArtifactSummaryResponse`. `_shape_value` and
  `_json_artifact_preview` are removed from the route file.
- `get_artifact_preview:130` calls
  `ArtifactPresentationService.preview_artifact` for JSON and delegates to
  `build_parquet_preview` for parquet (parquet stays in
  `artifact_service.py`). The route catches `PREVIEW_FAILED` only for
  parquet read errors and returns it via `HTTPException` (or, after Batch E,
  via `CardreError`).

### 4. Migrate evidence route

In `sidecar/routes/evidence.py`, `_to_item:26` calls
`ArtifactPresentationService.summarise_artifact` (with `include_staleness=True`
and the run-step context) to get the shared `evidence_kind` and
`unsupported_kind`. The staleness flag and `staleness_reason` computation
(`:65-73`) stays in the route (it depends on the run step map), but the
artifact kind/summary no longer diverges from the artifact summary route.

### 5. Create `ResourceLocator`

New file `cardre/services/resource_locator.py`.

```python
from cardre.store import ProjectStore


class ResourceLocator:
    def __init__(self, registry: dict) -> None: ...

    def find_store_by_run_id(self, run_id: str,
                             *, prefer_project_id: str | None = None,
                             ) -> tuple[str, ProjectStore] | tuple[None, None]: ...

    def find_store_by_artifact_id(self, artifact_id: str, ...) -> ...: ...
    def find_store_by_comparison_id(self, comparison_id: str, ...) -> ...: ...
    def find_store_by_comparison_snapshot_id(self, snapshot_id: str, ...) -> ...: ...
    def find_store_by_branch_id(self, branch_id: str, ...) -> ...: ...
    def find_store_by_plan_id(self, plan_id: str, ...) -> ...: ...
```

Rules:

- When `prefer_project_id` is supplied, check only that store. Never scan
  other projects. This isolates explicit-project callers from cross-project
  collisions.
- When scanning, skip projects whose registered path is missing (today
  `runs.py:257` and `:271` do this, `comparisons.py:54` and `branches.py:71`
  do not). Standardize on always skipping, with a debug log.
- When the same ID exists in two stores, return a `Conflict` signal (or raise
  `CardreError(code="RESOURCE_ID_CONFLICT", context={"id": ..., "projects":
  [...]})` after Batch E). Callers that today silently return the first match
  now get a deterministic conflict instead of a wrong-project resolution.

### 6. Migrate cross-project route scans

Replace the registry-iteration loops in:

- `sidecar/routes/runs.py:253` (`get_run`), `:266` (`get_run_steps`),
  `:303` (`get_run_manifest`) — use `ResourceLocator.find_store_by_run_id`.
- `sidecar/routes/comparisons.py:52` (`get_branch_comparison`), `:84`
  (`refresh_branch_comparison`), `:108` (`get_comparison_snapshot`) — use
  `find_store_by_comparison_id` / `find_store_by_comparison_snapshot_id`.
  Add missing-path skipping (currently absent).
- `sidecar/routes/branches.py:60` (`get_branch`) — use
  `find_store_by_branch_id` when `project_id` is absent; keep the
  explicit-project fast path.
- `sidecar/routes/plans.py:43` (`get_plan`), `:128`
  (`get_workflow_guidance`) — use `find_store_by_plan_id`.
- `cardre/services/artifact_service.py:18` (`find_artifact`) — use
  `ResourceLocator.find_store_by_artifact_id`.

## Tests

### New: `tests/test_artifact_presentation_service.py`

- Same JSON evidence artifact reports the same `evidence_kind` through
  `summarise_artifact` (artifact summary route) and the evidence route's
  `_to_item`.
- Unsupported JSON kind gets identical `unsupported_kind=True` and the same
  warning/status from both paths.
- Missing artifact returns `None` from `summarise_artifact`; both routes
  return `ARTIFACT_NOT_FOUND`.
- Parquet preview failure preserves `PREVIEW_FAILED`.
- `preview_artifact` for JSON returns the shape via `_shape_value` logic,
  now living in the service.

### New: `tests/test_resource_locator.py`

- Missing registered project path does not crash global lookup; it is
  skipped with a debug log.
- Explicit `prefer_project_id` never scans other projects.
- Duplicate run ID across two stores returns a conflict, not the first
  match. Assert the error code (or signal) carries both project IDs.
- `find_store_by_branch_id` with explicit project skips the scan.
- `find_store_by_plan_id` finds the plan only in its owning project.

### Update: `tests/test_evidence_route.py` and `test_evidence_summaries.py`

- Assert the evidence route and artifact summary route agree on
  `evidence_kind` for the same artifact.

## Verification

```bash
pytest tests/test_artifact_presentation_service.py \
       tests/test_resource_locator.py \
       tests/test_evidence_route.py \
       tests/test_evidence_summaries.py
```

## Definition of done

1. `ArtifactPresentationService` owns artifact summary/preview shape logic;
   both artifact and evidence routes consume it.
2. `build_json_summary_preview` is deleted.
3. `ResourceLocator` owns cross-project ID lookup with consistent
   missing-path skipping and duplicate-ID conflict detection.
4. All cross-project route scans delegate to `ResourceLocator`.
5. Artifact summary and run evidence agree on `evidence_kind` for the same
   artifact.
6. All listed tests are green.

## Files touched

- `cardre/services/artifact_presentation_service.py` (new)
- `cardre/services/resource_locator.py` (new)
- `cardre/services/artifact_service.py`
- `sidecar/routes/artifacts.py`
- `sidecar/routes/evidence.py`
- `sidecar/routes/runs.py`
- `sidecar/routes/comparisons.py`
- `sidecar/routes/branches.py`
- `sidecar/routes/plans.py`
- `tests/test_artifact_presentation_service.py` (new)
- `tests/test_resource_locator.py` (new)
- `tests/test_evidence_route.py` (updated)
- `tests/test_evidence_summaries.py` (updated)

## Depends on

Batch A (recommended, for evidence route consistency). Coordinate with
Batch D (both touch `sidecar/routes/runs.py`).

## Unblocks

Batch H (parity tests include artifact/evidence presentation and
cross-project lookup).