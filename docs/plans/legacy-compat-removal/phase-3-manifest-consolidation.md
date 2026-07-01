# Phase 3 — Manifest Consolidation (Single Canonical Manifest)

**Sprint:** `docs/plans/legacy-compat-removal-sprint.md`
**Phase goal:** Collapse the dual-manifest contract into one. `write_manifest()`
writes exactly one manifest — the canonical `RunManifest` model — and
registers it as the `run_manifest` artifact. Every consumer (reporting
collector, sidecar route, evidence reader) reads the same file. The legacy
artifact write is removed.

**This is the highest-risk phase of the sprint.** The canonical payload is
structurally richer than the legacy one. Read the whole document before
editing.

## Authority

ADR 0003 — artifacts may be reshaped freely; no compat required. The code
itself says the canonical `manifest.json` is authoritative while the legacy
artifact exists "for backwards compatibility" (`run_lifecycle.py:199-203`).

A pre-sprint audit confirmed the divergence is **already active**:
- **Reporting collector** reads the canonical `manifest.json` directly
  (`cardre/reporting/collector.py:820-884`, path built at `:827`).
- **Sidecar route** `GET /project/{id}/runs/{run_id}/manifest` reads the
  *legacy* registered artifact (`sidecar/routes/runs.py:136-155`).
- **Evidence reader** `read_run_manifest()` reads the *legacy* registered
  artifact (`cardre/_evidence/reader.py:390-396`; profile at
  `cardre/_evidence/profiles.py:223-228`).
- The canonical manifest is **not registered** in the artifact registry — it
  is written via `Path.write_text()` at `run_lifecycle.py:262-267` with no
  `store.register_artifact()` call.
- Manifest version strings differ: legacy `"1.0.0"` vs canonical
  `"cardre.run_manifest.v1"`.

## Decision (locked)

**Register the canonical manifest as the `run_manifest` artifact.** Keep the
sidecar response model (`RunManifestEvidence`) unchanged in shape — only swap
the underlying artifact content. This is the lowest-risk option: registry
consumers (sidecar route, evidence reader, tests) keep working via
`list_artifacts()` filtering by `artifact_type == "run_manifest"`, but now
find the canonical payload.

The canonical file stays at `exports/manifest-{run_id}/manifest.json` so the
reporting collector's direct-path read keeps working unchanged.

## Files

### Read first (do not edit)
- `cardre/run_lifecycle.py:24` — `MANIFEST_VERSION = "1.0.0"` (legacy).
- `cardre/run_lifecycle.py:27-31` — `compute_manifest_hash()`.
- `cardre/run_lifecycle.py:104-157` — `write_manifest()` (legacy write at
  146-153, canonical call at 155-157).
- `cardre/run_lifecycle.py:185-267` — `_write_canonical_manifest()` (build at
  241-259, hash at 260, write at 262-267).
- `cardre/run_lifecycle.py:290-312` — `finalise_run()` (calls `write_manifest`).
- `cardre/run_lifecycle.py:437-482` — `RunLifecycle.finalise()`.
- `cardre/artifacts.py:25-55` — `write_json_artifact()` (writes file +
  registers). Note `ArtifactRef` has `path`, `artifact_type`, `role`,
  `media_type`, `metadata`, `physical_hash`, `logical_hash`, `artifact_id`.
- `cardre/audit.py` — `ArtifactRef`, `relative_path`, `physical_hash`,
  `json_logical_hash`.
- `cardre/reporting/schema.py:430-448` — `RunManifest` model
  (`manifest_version="cardre.run_manifest.v1"`, `manifest_hash=""`).
- `cardre/reporting/collector.py:820-884` — `_read_canonical_manifest()`
  (reads `exports/manifest-{run_id}/manifest.json`).
- `cardre/_evidence/profiles.py:223-228` — RUN_MANIFEST profile
  (`schema_version=SCHEMA_RUN_MANIFEST`, `required_keys={"manifest_version",
  "run_id", "steps"}`).
- `cardre/_evidence/reader.py:349-420` — `_legacy_match()` RUN_MANIFEST branch
  (filters by `artifact_type=="run_manifest"` + payload keys).
- `sidecar/routes/runs.py:136-155` — `get_project_run_manifest()` (reads via
  registry → `reader.read_run_manifest()`).
- `tests/test_manifest.py` — full file (asserts both manifests exist).
- `tests/test_run_lifecycle.py`, `tests/test_executor.py`,
  `tests/test_run_coordination_contract.py`, `tests/test_evidence_reader.py`
  — read the legacy artifact via `list_artifacts()`.

### Modify
- `cardre/run_lifecycle.py` — remove legacy write; register canonical.
- `cardre/_evidence/profiles.py` — add `"cardre.run_manifest.v1"` handling.
- `sidecar/routes/runs.py` — verify/adjust for canonical payload.
- `cardre/reporting/collector.py` — optionally simplify (no change required).
- Tests listed above.

## Steps

### Step 1 — Register the canonical manifest as the `run_manifest` artifact

In `_write_canonical_manifest()` (`cardre/run_lifecycle.py:185-267`), after
writing the file (line 267), register an `ArtifactRef` pointing at the
canonical path. Do **not** use `write_json_artifact()` (it would write a
second file); construct the ref manually:

```python
from cardre.audit import ArtifactRef, relative_path, physical_hash

    # existing write (line 262-267):
    manifest_path.write_text(
        manifest.model_dump_json(indent=2, by_alias=False)
    )
    # NEW: register the canonical manifest as the run_manifest artifact
    phys = physical_hash(manifest_path)
    canonical_payload = json.loads(manifest_path.read_text())
    logical = json_logical_hash(canonical_payload)
    store.register_artifact(ArtifactRef(
        artifact_id=str(uuid.uuid4()),
        artifact_type="run_manifest",
        role="audit",
        path=relative_path(manifest_path, store.root),
        physical_hash=phys,
        logical_hash=logical,
        media_type="application/json",
        metadata={
            "schema_version": manifest.manifest_version,   # "cardre.run_manifest.v1"
            "run_id": run_id,
        },
    ))
```

`uuid` and `json` are already imported in `run_lifecycle.py` (used by
`write_manifest`). Confirm by reading the imports at the top of the file.
`json_logical_hash` is already imported (line 27-31 uses it).

**Read the actual `ArtifactRef`/`ArtifactRepository.register` signatures first**
to confirm the constructor field names and whether `register_artifact` accepts
a path outside `artifacts/`. The canonical path is under `exports/`, not
`artifacts/` — if the registry rejects that, the fallback is to also write a
thin copy under `artifacts/` via `write_json_artifact`, but prefer the
single-file + manual-register approach.

### Step 2 — Remove the legacy artifact write

In `write_manifest()` (`cardre/run_lifecycle.py:104-157`), delete lines
146-153 (the `write_json_artifact(..., artifact_type="run_manifest", ...)`
call). Keep the `_write_canonical_manifest(...)` call at 155-157 — it now does
the registration (Step 1).

If `write_manifest()` no longer uses the legacy `payload` for the artifact
write, check whether `payload` is still needed by `_write_canonical_manifest`
(the last arg at line 156-157). If `_write_canonical_manifest` only uses
`payload.get("steps")` for action labels, keep passing it; otherwise simplify.

Also remove `MANIFEST_VERSION = "1.0.0"` (line 24) and `build_manifest_payload()`
(lines 50-101) if nothing else uses them. Grep before deleting:
```bash
rg -n "MANIFEST_VERSION|build_manifest_payload" cardre/ sidecar/ tests/
```

### Step 3 — Make the evidence reader resolve the canonical payload via Phase 1

The RUN_MANIFEST profile (`cardre/_evidence/profiles.py:223-228`) has
`schema_version=SCHEMA_RUN_MANIFEST` which equals `"cardre.run_manifest.v1"`.
The canonical manifest's metadata now carries
`schema_version="cardre.run_manifest.v1"` (Step 1). The reader's Phase 1 match
(`_evidence/reader.py:268-278`) filters artifacts by
`a.metadata.get("schema_version") in schema_versions` — so the canonical
artifact should now match in Phase 1 and never reach `_legacy_match`.

Verify the RUN_MANIFEST profile's `required_keys` (`{"manifest_version",
"run_id", "steps"}`) are present in the canonical `RunManifest` model
(`schema.py:430-448`): `manifest_version` ✓, `run_id` ✓, `steps` ✓. Good —
the Phase 2 payload check should pass.

**Run the evidence reader tests now:**
```bash
. .venv/bin/activate
pytest tests/test_evidence_reader.py -q
```

If `read_run_manifest()` fails to parse the richer canonical payload, inspect
the RUN_MANIFEST branch in `_legacy_match()` (`reader.py` RUN_MANIFEST block)
and the `read_run_manifest` parse path (`reader.py:176-177`, `:600-601`). The
parse logic must accept the canonical shape. **Do not remove the RUN_MANIFEST
branch from `_legacy_match()` in this phase** — leave it as a safety net;
Phase 5 removes branches only for the Phase-4-fixed writers, and RUN_MANIFEST
is handled by the profile change, not a writer fix. If the branch becomes
unreachable, note it for a follow-up.

### Step 4 — Verify the sidecar route reads the canonical payload

`sidecar/routes/runs.py:136-155` reads via `store.list_artifacts()` filtered
by `artifact_type == "run_manifest"`, then `reader.read_run_manifest(...)`.
With Step 1, the registry now returns the canonical artifact. The route maps
it to a `RunManifestEvidence` response model.

Read `RunManifestEvidence` (grep for its definition) and confirm it can be
populated from the canonical payload. The canonical has *more* fields than the
legacy, so the mapping should still work (extra canonical fields are ignored
by a thinner model). If `RunManifestEvidence` expects the legacy
`manifest_version: "1.0.0"` and rejects `"cardre.run_manifest.v1"`, update the
response model's validator/field to accept the canonical version string — or
map `manifest_version` to the canonical value in the route.

Run:
```bash
pytest tests/test_run_lifecycle.py tests/test_executor.py \
       tests/test_run_coordination_contract.py -q
```

### Step 5 — Update tests that assert the dual-manifest shape

`tests/test_manifest.py:95-152`
(`test_manifest_json_written_alongside_run_manifest`) asserts **both** the
legacy artifact (via `list_artifacts()`) and the canonical `manifest.json`
exist. Rewrite it to assert a **single** manifest:
- Exactly one `artifact_type == "run_manifest"` artifact is registered.
- That artifact's `path` points at `exports/manifest-{run_id}/manifest.json`.
- Reading that path yields the canonical `RunManifest` JSON with
  `manifest_version == "cardre.run_manifest.v1"` and a non-empty
  `manifest_hash`.
- The hash is stable for identical content (preserve the determinism test).

`tests/test_manifest.py:154-242` (hash-differs, path-in-tests) — keep, but
adjust any assertion that reads the legacy artifact to read the canonical one.

Lifecycle/executor/coordination/evidence-reader tests that filter
`list_artifacts()` by `artifact_type=="run_manifest"` and then assert on the
payload — update their payload assertions to the canonical shape:
`manifest_version == "cardre.run_manifest.v1"`, presence of `manifest_hash`,
`plan_id`, `RunManifestStep` fields (`canonical_step_id`, etc.). Do **not**
just delete these assertions; rewrite them to the canonical shape so coverage
is preserved.

### Step 6 — Reporting collector (verify, optionally simplify)

`cardre/reporting/collector.py:820-884` reads the canonical path directly.
This still works (the file is still at that path). No change required. If you
want, you may simplify it to use registry discovery now that the canonical is
registered, but this is optional and adds risk — skip unless a test forces it.

## Verification commands

```bash
. .venv/bin/activate

# Confirm no second manifest artifact is written.
rg -n "artifact_type=\"run_manifest\"|artifact_type='run_manifest'" cardre/run_lifecycle.py
# Should match ONLY the registration in _write_canonical_manifest (Step 1),
# NOT a write_json_artifact call.

# Focused suites.
pytest tests/test_manifest.py tests/test_run_lifecycle.py \
       tests/test_executor.py tests/test_run_coordination_contract.py \
       tests/test_evidence_reader.py -q
pytest tests/reporting/test_run_status.py -q

# Full preflight.
ruff check --fix
make preflight
```

## Definition of done for this phase

- [ ] `write_manifest()` writes exactly one manifest (no legacy
      `write_json_artifact(..., artifact_type="run_manifest", ...)` call).
- [ ] `_write_canonical_manifest()` registers the canonical file as a
      `run_manifest` artifact via `store.register_artifact(ArtifactRef(...))`.
- [ ] The canonical manifest is discoverable via `list_artifacts()` filtered
      by `artifact_type == "run_manifest"`.
- [ ] `MANIFEST_VERSION = "1.0.0"` and `build_manifest_payload()` are removed
      if unused (grep-confirmed).
- [ ] Evidence reader `read_run_manifest()` resolves the canonical payload
      (Phase 1 schema match on `schema_version="cardre.run_manifest.v1"`).
- [ ] Sidecar `GET /project/{id}/runs/{run_id}/manifest` returns the canonical
      manifest mapped to `RunManifestEvidence` (or the response model is
      updated to accept the canonical version string).
- [ ] Reporting collector still reads the canonical path successfully.
- [ ] `test_manifest.py` asserts a single canonical manifest, not both.
- [ ] All lifecycle/executor/coordination/evidence-reader tests green with
      payload assertions updated to the canonical shape.
- [ ] `ruff check` clean.
- [ ] `make preflight` green.
- [ ] PR raised via `scripts/pr-gate.sh`; CI green.

## Failure mode

- **`list_artifacts()` does not find the canonical manifest:** the
  `register_artifact` call in Step 1 failed silently or the `path` is wrong.
  Confirm `relative_path(manifest_path, store.root)` returns a string the
  registry stores, and that `ArtifactRepository.register` (in
  `cardre/store/artifact_repo.py`) accepts a path under `exports/`. If the
  registry hard-codes `artifacts/`, switch to `write_json_artifact` for a thin
  registered copy and keep the canonical `exports/` file for the collector —
  but report this as a deviation from the plan.
- **`read_run_manifest()` raises on the richer payload:** the parse logic
  expected the legacy `"1.0.0"` shape. Read `reader.py` around lines 176-177
  and 600-601; update the parser to accept `manifest_version` ==
  `"cardre.run_manifest.v1"` and the `RunManifestStep` structure. Do not
  remove the `_legacy_match` RUN_MANIFEST branch — just make Phase 1 reach it.
- **A test asserts `manifest_version == "1.0.0"`:** rewrite to
  `"cardre.run_manifest.v1"` (canonical).
- **`RunManifestEvidence` rejects the canonical version string:** update the
  response model's field/validator to accept `"cardre.run_manifest.v1"`, or map
  it in the route. Under ADR 0003 this is an allowed breaking change.
- **Reporting collector breaks:** it reads the canonical path directly and
  the file is unchanged — it should not break. If it does, you accidentally
  moved the canonical file; restore the `exports/manifest-{run_id}/manifest.json`
  path.