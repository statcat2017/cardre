# PR 5 — Canonical run-manifest + collapse DB schema to baseline 101

**Sprint:** `docs/plans/legacy-compat-collapse.md`
**Depends on:** PR 4
**Risk:** High
**Authority:** ADR 0003; user decision (collapse DB to baseline 101, remove runner).

## Goal

One run-manifest representation (`cardre.run_manifest.v1`), written once, registered once as the `run_manifest` artifact. One DB schema (101) with no migration runner — opening a v100 (or any non-101) store raises `SchemaVersionError`.

## Files to read first (do not edit)

- `cardre/execution/run_lifecycle.py` — `MANIFEST_VERSION = "1.0.0"` (:30), `step_action` (:38-42), `build_manifest_payload` (:45-88), `write_manifest` (:91-137), `RunFinalisation` (:145-155), `finalise_run` (:158-180), `RunLifecycle` (:188-362), `assert_run_audit_integrity` (:365-460).
- `cardre/reporting/schema.py` — `RunManifestStep` (:407-426), `RunManifest` (:429-447).
- `cardre/reporting/collector.py` — `_read_canonical_manifest` (:129-195) (reads `exports/manifest-{run_id}/manifest.json`, validates via `RunManifest.model_validate`, recomputes `manifest_hash`).
- `cardre/store/_schema_version.py` — `check_and_migrate` (:16-69), `_run_migrations` (:72-101).
- `cardre/store/schema.py` — `V2_STORE_SCHEMA_VERSION = 101` (:13), docstring (:1-9).
- `cardre/store/db.py` — `open()` (:66-92), stale docstring at :83-85 ("Hard-errors on schema_version != 100" — false; it migrates 100→101).
- `cardre/domain/artifacts.py` — `ArtifactRef`, `json_logical_hash` (for manifest hash computation).
- `cardre/artifacts.py` — `write_json_artifact`, `physical_hash`, `relative_path` (to register the manifest).
- `cardre/store/artifact_repo.py` — `ArtifactRepository.register` (confirm it accepts a path under `exports/`).
- `tests/test_run_lifecycle.py`, `tests/test_run_audit_integrity.py`, `tests/test_manifest.py` (if present), `tests/test_store_repos.py` (migration test at :705-752).

## Code instructions

### Part A — Canonical run manifest

#### Step A1 — Replace `build_manifest_payload` with a canonical builder

In `cardre/execution/run_lifecycle.py`:

- Line 30: `MANIFEST_VERSION = "1.0.0"` → `MANIFEST_VERSION = "cardre.run_manifest.v1"`.

- Replace `build_manifest_payload` (lines 45-88) with a canonical builder that emits the `RunManifest` shape. Use the `RunManifest` + `RunManifestStep` Pydantic models from `cardre/reporting/schema.py`. The builder needs access to the plan-step lookup (for `canonical_step_id`, `category`, `parent_step_ids`, `params`) and evidence edges (for `input_artifact_ids`/`output_artifact_ids`), so it must accept the `store`:

  ```python
  def build_manifest_payload(
      *,
      store: ProjectStore,
      run_id: str,
      plan_version_id: str,
      run_record: JsonDict,
      run_steps: list[Any],
      execution_mode: str,
      final_status: str,
      finished_at: str,
      branch_id: str | None = None,
      target_step_id: str | None = None,
      in_scope_step_ids: list[str] | None = None,
  ) -> JsonDict:
      from cardre.reporting.schema import RunManifest, RunManifestStep
      from cardre.store.plan_repo import PlanRepository
      from cardre.store.run_step_repo import RunStepRepository

      plan_repo = PlanRepository(store)
      plan_steps = {ps.step_id: ps for ps in plan_repo.get_version_steps(plan_version_id)}

      steps: list[RunManifestStep] = []
      for rs in run_steps:
          ps = plan_steps.get(rs.step_id)
          steps.append(RunManifestStep(
              step_id=rs.step_id,
              canonical_step_id=ps.canonical_step_id if ps else "",
              branch_id=ps.branch_id if ps else None,
              node_type=rs.execution_fingerprint.get("node_type", ""),
              node_version=rs.execution_fingerprint.get("node_version", ""),
              category=ps.category if ps else "",
              status=rs.status.value if hasattr(rs.status, "value") else rs.status,
              action=step_action(rs),
              is_carried_forward=bool(rs.execution_fingerprint.get("cardre_step_carried_forward")),
              started_at=rs.started_at,
              finished_at=rs.finished_at,
              params=ps.params if ps else {},
              params_hash=rs.execution_fingerprint.get("params_hash", ""),
              parent_step_ids=ps.parent_step_ids if ps else [],
              input_artifact_ids=[],   # query evidence_artifacts for this run_step
              output_artifact_ids=[],   # query evidence_artifacts for this run_step
              warnings=rs.warnings,
              errors=rs.errors,
              execution_fingerprint=rs.execution_fingerprint,
          ))

      manifest = RunManifest(
          manifest_version=MANIFEST_VERSION,
          manifest_hash="",  # filled after hash
          run_id=run_id,
          plan_version_id=plan_version_id,
          plan_id=run_record.get("plan_id", ""),
          project_id=run_record.get("project_id", ""),
          branch_id=branch_id,
          started_at=run_record["started_at"],
          finished_at=finished_at,
          status=final_status,
          execution_mode=execution_mode,
          cardre_version=__version__,
          pathway_hash="",  # filled if available
          artifact_root="",  # filled if available
          target_step_id=target_step_id,
          in_scope_step_ids=in_scope_step_ids or [],
          steps=steps,
          diagnostics=[],  # query run diagnostics if desired
      )
      payload = manifest.model_dump()
      # Compute manifest_hash over the payload with manifest_hash=""
      payload_for_hash = dict(payload)
      payload_for_hash["manifest_hash"] = ""
      payload["manifest_hash"] = json_logical_hash(payload_for_hash)
      return payload
  ```

  Read `cardre/store/run_step_repo.py` and `cardre/store/artifact_repo.py` / `evidence_artifacts` to populate `input_artifact_ids`/`output_artifact_ids` per step (query `evidence_edges` + `evidence_artifacts` for each `run_step_id`). If this is complex, leave them as `[]` for this PR and note it as follow-up — the audit check only validates `run_id`/`plan_version_id`/`status`/hash.

  Read `cardre/domain/run.py` to confirm the `RunStep` field names (`started_at`, `finished_at`, `warnings`, `errors`, `execution_fingerprint`).

#### Step A2 — Register the manifest as the `run_manifest` artifact

In `write_manifest` (lines 91-137), after writing the file (line 135-137), register the artifact:

```python
from cardre.domain.artifacts import ArtifactRef, json_logical_hash
from cardre.artifacts import physical_hash, relative_path
import uuid

phys = physical_hash(manifest_path)
logical = json_logical_hash(payload)  # payload already has manifest_hash set
store.register_artifact(ArtifactRef(
    artifact_id=str(uuid.uuid4()),
    artifact_type="run_manifest",
    role="audit",
    path=relative_path(manifest_path, store.root),
    physical_hash=phys,
    logical_hash=logical,
    media_type="application/json",
    metadata={"schema_version": MANIFEST_VERSION, "run_id": run_id},
))
```

Read `cardre/artifacts.py` and `cardre/store/artifact_repo.py` first to confirm:
- `physical_hash` and `relative_path` exist (or their real names).
- `ArtifactRepository.register` / `store.register_artifact` accepts a path under `exports/` (not just `artifacts/`). If it hard-codes `artifacts/`, the fallback is to write a thin registered copy under `artifacts/run-manifest-{run_id}.json` via `write_json_artifact` AND keep the canonical file at `exports/manifest-{run_id}/manifest.json` for the collector. Report any deviation.

Update the `write_manifest` signature to pass `store` through to `build_manifest_payload` (it already has `store`).

#### Step A3 — Update `assert_run_audit_integrity`

In `cardre/execution/run_lifecycle.py` (lines 365-460):
- The existing `run_id`/`plan_version_id`/`status` checks (lines 433-460) stay.
- Add a `manifest_version` check:
  ```python
  if manifest.get("manifest_version") != "cardre.run_manifest.v1":
      raise RunLifecycleError(
          f"Manifest version mismatch: expected 'cardre.run_manifest.v1', "
          f"got {manifest.get('manifest_version')!r}",
          code="MANIFEST_VERSION_MISMATCH",
          context={"run_id": run_id, "manifest_version": manifest.get("manifest_version")},
      )
  ```
- Add a `manifest_hash` self-consistency check (recompute with `manifest_hash=""` and compare).

#### Step A4 — Verify the reporting collector

`cardre/reporting/collector.py` `_read_canonical_manifest` (lines 129-195) already reads the canonical file and validates via `RunManifest.model_validate`. With the writer now emitting the canonical shape, this works unchanged. **Verify only** — run the reporting tests.

#### Step A5 — Update tests

- `tests/test_run_lifecycle.py`: assert `manifest_version == "cardre.run_manifest.v1"`, non-empty `manifest_hash`, `RunManifestStep` fields (`canonical_step_id`, etc.). Remove any assertion on `"1.0.0"`.
- `tests/test_run_audit_integrity.py`: update the manifest fixture at :55 to emit `"manifest_version": "cardre.run_manifest.v1"` and a valid `manifest_hash` (recompute with `manifest_hash=""`).
- `tests/test_manifest.py` (if present): assert exactly one `artifact_type == "run_manifest"` artifact is registered, its `path` points at `exports/manifest-{run_id}/manifest.json`, and reading that path yields `manifest_version == "cardre.run_manifest.v1"`.
- Any test that filters `list_artifacts()` by `artifact_type == "run_manifest"`: now finds the canonical artifact. Update payload assertions to the canonical shape.

### Part B — Collapse DB schema

#### Step B1 — Replace `check_and_migrate` with a strict check

In `cardre/store/_schema_version.py`, replace the body of `check_and_migrate` (lines 16-69) with:

```python
def check_and_migrate(conn: sqlite3.Connection) -> None:
    """Verify schema family and version. No migrations are supported.

    The app requires the current schema version exactly. Older stores
    are rejected with SchemaVersionError; recreate the project.
    """
    conn.execute(
        "CREATE TABLE IF NOT EXISTS store_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)"
    )
    try:
        rows = conn.execute(
            "SELECT key, value FROM store_meta WHERE key IN ('schema_family', 'schema_version')"
        ).fetchall()
    except sqlite3.OperationalError as exc:
        raise SchemaVersionError(
            "Store schema metadata is missing or corrupt. "
            "Recreate this project with the current app."
        ) from exc

    meta = {row["key"]: row["value"] for row in rows}
    family = meta.get("schema_family")
    if family != V2_STORE_SCHEMA_FAMILY:
        raise SchemaVersionError(
            f"Store schema family {family!r} does not match app family "
            f"{V2_STORE_SCHEMA_FAMILY!r}. Recreate this project with the current app."
        )

    version_text = meta.get("schema_version")
    if version_text is None:
        raise SchemaVersionError(
            "Store schema version is missing. Recreate this project with the current app."
        )

    try:
        stored_version = int(version_text)
    except ValueError as exc:
        raise SchemaVersionError(
            f"Store schema version {version_text!r} is invalid. "
            "Recreate this project with the current app."
        ) from exc

    if stored_version != V2_STORE_SCHEMA_VERSION:
        raise SchemaVersionError(
            f"Store schema version {stored_version} is not supported by this app "
            f"(expected {V2_STORE_SCHEMA_VERSION}). Recreate this project with the current app."
        )
```

Delete `_run_migrations` (lines 72-101) entirely.

Keep the function name `check_and_migrate` (it's called from `db.py:open()`); just change its behaviour. (Optionally rename to `check_schema_version` and update the one caller — but keeping the name minimizes churn.)

#### Step B2 — Update schema docstring

In `cardre/store/schema.py` (lines 1-9), replace the docstring with:
```
"""SQL schema for the Cardre v2 project store.

Current schema version: 101. Older versions are not supported; opening
a v100 (or other) store raises SchemaVersionError. Recreate the project
with the current app.
"""
```
Keep `V2_STORE_SCHEMA_FAMILY = "cardre-v2"` and `V2_STORE_SCHEMA_VERSION = 101`.

#### Step B3 — Fix stale docstring in `db.py`

In `cardre/store/db.py` (lines 83-85), replace the "Hard-errors on schema_version != 100" comment with:
```
Rejects stores whose schema version is not the current app version
(see ``_schema_version.check_and_migrate``).
```

#### Step B4 — Update tests

- Delete `tests/test_store_repos.py::TestSchemaMigration::test_v100_store_migrated_to_v101_adds_active_step_id` (lines 705-752).
- **Add** a test in the same file (or `tests/test_canonical_contract.py`):
  ```python
  def test_v100_store_rejected(self, tmp_path):
      # Seed a v100 store (schema_version=100), open it, assert SchemaVersionError.
      # Mirror the setup of the deleted migration test, but assert the error.
      from cardre.domain.errors import SchemaVersionError
      # ... create store, set schema_version=100 ...
      with pytest.raises(SchemaVersionError):
          ProjectStore.open(store_path)
  ```
- `tests/test_store_rejects_v1_project.py` already asserts `STORE_VERSION_INCOMPATIBLE` for a family mismatch — verify it still passes.
- `tests/test_store_repos.py::test_run_repo_set_active_step` (line 259) uses the 101 column — it still works (the column exists in the baseline schema). No change.

#### Step B5 — Add guard tests

Add to `tests/test_canonical_contract.py`:
```python
def test_run_manifest_canonical_shape():
    # After a run, the manifest has manifest_version="cardre.run_manifest.v1",
    # non-empty manifest_hash, RunManifestStep fields (canonical_step_id, etc.).
    # Use an existing run fixture (tests/conftest.py) to run a small plan,
    # then read exports/manifest-{run_id}/manifest.json and assert.
    ...

def test_db_rejects_v100_store():
    from cardre.domain.errors import SchemaVersionError
    # Seed v100, open, assert SchemaVersionError.
    ...
```

## Verification

```bash
. .venv/bin/activate
rg -n "MANIFEST_VERSION|build_manifest_payload|_run_migrations" cardre/
# MANIFEST_VERSION exists once (= cardre.run_manifest.v1); _run_migrations gone.
rg -n "\"1\.0\.0\"" cardre/execution/run_lifecycle.py
# Zero matches.
ruff check --fix
pytest tests/test_run_lifecycle.py tests/test_run_audit_integrity.py \
       tests/test_store_repos.py tests/test_store_rejects_v1_project.py \
       tests/test_reporting.py tests/test_canonical_contract.py -q
make preflight
scripts/pr-gate.sh
```

## Definition of done

- [ ] `MANIFEST_VERSION == "cardre.run_manifest.v1"`.
- [ ] `build_manifest_payload` emits the `RunManifest` shape with `manifest_hash`.
- [ ] The manifest file is registered as the `run_manifest` artifact (discoverable via `list_artifacts()`).
- [ ] `assert_run_audit_integrity` validates `manifest_version` + `manifest_hash` self-consistency.
- [ ] `_run_migrations` deleted; `check_and_migrate` is a strict family+version check.
- [ ] `test_v100_store_migrated_to_v101` deleted; `test_v100_store_rejected` added.
- [ ] Stale `db.py` docstring corrected.
- [ ] `ruff check` clean; `make preflight` green; PR gate green.

## Failure mode

- **`ArtifactRepository.register` rejects `exports/` path:** switch to writing a thin registered copy under `artifacts/run-manifest-{run_id}.json` via `write_json_artifact` AND keep the canonical file at `exports/manifest-{run_id}/manifest.json` for the collector. Report this as a deviation in the PR description.
- **`manifest_hash` mismatch in collector:** the collector recomputes the hash with `manifest_hash=""` and compares. Ensure `build_manifest_payload` computes the hash the same way (`json_logical_hash` over the dict with `manifest_hash=""`). Read `cardre/domain/artifacts.py:json_logical_hash` to confirm the canonicalization (sorted keys).
- **`RunStep` field name mismatch:** `RunStep` may use `started_at`/`finished_at` or different names. Read `cardre/domain/run.py` and `cardre/store/run_step_repo.py` to confirm.
- **Migration test setup reused:** the deleted `test_v100_store_migrated_to_v101` has setup code for seeding a v100 store. Reuse it for `test_v100_store_rejected` but flip the assertion to `pytest.raises(SchemaVersionError)`.
- **`test_store_rejects_v1_project` breaks:** it tests a *family* mismatch (`cardre-v1` vs `cardre-v2`), which the new strict check still rejects. Verify the error code matches.