# Step 10 — Architecture Documentation

File: `docs/architecture/artifact-evidence-access.md` (new).

## Pre-req: S9 complete (so doc references the final guardrail + CI).

## Required sections (spec §9 PR10)

1. **Artifact vs Evidence distinction** — summary of CONTEXT.md &
   the spec's §5 Definitions. Artifacts are storage; evidence is the
   typed product-meaning built by `ArtifactEvidenceReader`.
2. **Approved read paths** — list the four approved modules:
   - `cardre/artifacts.py`
   - `cardre/evidence.py`
   - `cardre/_evidence/`
   - `cardre/modeling/serialization.py` (binary estimator IO)
3. **Forbidden patterns** — list the regex literals from spec §10
   with one-sentence "why" per pattern.
4. **Allowed inline suppressions** — the four reasons + when each is
   legitimate + a code example for each:
   - `dataset-frame-input` (e.g. LogisticRegressionNode reading WOE
     training parquet)
   - `artifact-byte-download` (sidecar download route streaming bytes)
   - `low-level-evidence-parser` (code inside `_evidence/` — though
     those files are in `APPROVED_PATTERNS` so suppression is rare)
   - `serialization-compatibility-test` (raw layout tests)
5. **How to add a new evidence kind** — checklist:
   - add `EvidenceKind` enum member in `_evidence/kinds.py`
   - add `SCHEMA_<KIND>` constant in `_evidence/schemas.py`
   - add typed dataclass + `from_json` in `_evidence/models.py`
   - add `EVIDENCE_PROFILES` entry in `_evidence/profiles.py`
   - add reader dispatch in `_evidence/reader.py::_to_typed`
   - add `tests/fixtures/evidence/<kind>.json|.parquet` + parse test in
     `tests/test_evidence_reader.py`
   - add `tests/test_evidence_profiles.py` parametrised entry
   - add a convenience method to `ArtifactEvidenceReader` if the kind
     is high-use
6. **How to write a node that consumes artifacts** — checklist with a
   copy-pasteable snippet:
   ```python
   reader = ArtifactEvidenceReader(store)
   try:
       model = reader.find(input_artifacts, EvidenceKind.MODEL_ARTIFACT)
   except EvidenceNotFoundError as exc:
       raise NodeInputError(
           "Model requires cardre.model_artifact.v1 evidence from the "
           "logistic regression step, but no matching artifact was "
           "found among inputs: "
           f"{[a.artifact_id for a in input_artifacts]}."
       ) from exc
   ```
   - Link to error spec §11 (or copy the table).
7. **How to write a report collector** — must reuse
   `ArtifactEvidenceReader`; no per-collector interpretation. Either
   call `reader.find(...)` per kind, or call the shared
   `collect_report_view` helper if S7 introduced one.
8. **How to write sidecar artifact previews** — use
   `reader.summarise_artifact(artifact_id)` /
   `summarise_step_outputs(run_step)` /
   `summarise_run_artifacts(run_id)`. Streaming downloads may use
   `store.artifact_path(art)` for byte streaming only, with the
   `artifact-byte-download` suppression. Never `json.loads` an
   artifact body in a route.
9. **How to write tests** — use
   `tests/helpers/evidence_assertions.py`
   (`assert_model_artifact`, ...) not raw dict assertions. Raw layout
   assertions live only in the three isolated serialization/compat
   test files.
10. **Legacy compatibility policy** — paraphrase spec §12.
    Legacy detection belongs in `cardre/_evidence/` (e.g.
    `reader._legacy_match`, `legacy.py`). Product code must not know
    whether evidence came from current schema or legacy fallback.

## Guardrail failure message link

`tests/test_artifact_guardrail.py` already references this doc by
path (per S9). Ensure the path matches exactly:
`docs/architecture/artifact-evidence-access.md`.

## Acceptance criteria

- A new contributor reading only this document can add a new evidence
  kind without copying a raw-read pattern.
- The guardrail failure message URL/path resolves.
- Doc references current module names; no broken links to modules
  that don't exist after the migration.

## Do NOT do

- Do not duplicate the full spec — this is an architecture/operator
  doc. Keep it under ~400 lines. Reference CONTEXT.md and the guardrail
  test rather than restating them verbatim.

## Verify

```
ls docs/architecture/artifact-evidence-access.md
pytest tests/test_artifact_guardrail.py  # to confirm the link is correct
```