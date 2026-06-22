# Step 06 — Migrate Services and Sidecar Routes

Files:
- `cardre/services/manual_binning_service.py`
- `cardre/services/comparison_service.py`
- `sidecar/routes/artifacts.py`
- `sidecar/routes/method_summary.py`
- `sidecar/routes/runs.py`

## Pre-req: S2 complete (the `summarise_*` helpers and typed
`COMPARISON_ARTIFACT` kind are available).

## Direct reads (from survey)

### `cardre/services/manual_binning_service.py`
- L292 `bin_def = json.loads(self._store.artifact_path(bin_artifact).read_text())`
  — BIN_DEFINITION. Replace with
  `ArtifactEvidenceReader(self._store).read(bin_artifact_id, EvidenceKind.BIN_DEFINITION)`.
- L293 `vs_def = json.loads(self._store.artifact_path(vs_artifact).read_text())`
  — SELECTION_DEFINITION. Same pattern.

### `cardre/services/comparison_service.py`
- L80 `path = store.artifact_path(art)` — Determine what's done with
  the path. If the service reads the file to extract comparison
  fields, replace with `reader.read(art.artifact_id, EvidenceKind.COMPARISON_ARTIFACT)`
  (added in S2). If it streams file bytes to the caller (download),
  this is an artifact-byte-download — keep it and add suppression
  `# cardre-allow-artifact-read: artifact-byte-download`.

### `sidecar/routes/artifacts.py`
Two cases (spec §9 PR6):
1. **Download / stream** — streaming raw bytes is the route's
   purpose. Add suppression
   `# cardre-allow-artifact-read: artifact-byte-download`.
2. **Preview / summary** — must use
   `reader.summarise_artifact(artifact_id)` (added in S2) and return
   safe metadata, never raw JSON. Audit the route for any
   `json.loads(...artifact_path...)` or
   `Path(store.artifact_path(...)).read_text()` and replace with
   summaries. If the route currently returns the full artifact body
   as JSON for the frontend, replace with `summarise_artifact` output
   and add a separate `/download` endpoint that streams bytes (if not
   already present).

### `sidecar/routes/method_summary.py`
Determine if it interprets artifact content semantically. If yes, it
must consume typed evidence summaries. Use
`reader.summarise_step_outputs(run_step)` for any "give me what this
step produced" surface. If it only proxies run step metadata that's
already in SQLite (no artifact payload read), remove the audit
violations via suppression comments only where genuinely byte-streaming.

### `sidecar/routes/runs.py`
Same rule. If the route serialises run manifest / run step records,
ensure any artifact content view goes through
`reader.summarise_run_artifacts(run_id)` or
`reader.read_run_manifest(artifact_id)` (S2 helper). Direct
`json.loads(store.artifact_path(...))` is forbidden.

## Required behaviour (spec §9 PR6)

- Sidecar routes must not interpret artifact contents directly.
- Routes may stream/download artifact bytes (explicit download
  purpose) — suppress.
- Artifact preview must use evidence summaries or approved preview
  helpers.
- Manual binning service must consume typed `BinDefinition`,
  `SelectionDefinition`, and `ManualBinningOverrides` evidence.

## Tests

- `tests/test_sidecar_api.py`:
  - Assert artifact preview endpoints return summarised metadata
    (no raw payload leak).
  - Assert download endpoints stream bytes.
- `tests/test_manual_binning_source.py`:
  - Assert behaviour via evidence models (not raw JSON dicts).

## Do NOT do

- Do not modify `reporting/` here (S7).
- Do not add any new typed model to `cardre/_evidence/` — if a model
  is missing, that's an S2 defect; raise it back to the orchestrator
  rather than define it here.

## Verify

```
python scripts/audit_artifact_reads.py --production --json
pytest tests/test_sidecar_api.py tests/test_manual_binning_source.py tests/test_branch_service.py
```