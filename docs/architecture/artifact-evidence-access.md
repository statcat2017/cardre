# Artifact Evidence Access

This document describes the final artifact/evidence boundary enforced by the
guardrail in `tests/test_artifact_guardrail.py` and `scripts/audit_artifact_reads.py`.

See `CONTEXT.md` and the evidence specs in `cardre/_evidence/` for the source
of truth. This page is the operator-facing guide.

## Artifact vs Evidence

- An artifact is storage: a file on disk plus metadata in the store.
- Evidence is a typed interpretation of an artifact, produced by
  `ArtifactEvidenceReader`.
- Production code should consume evidence, not raw files.

The main rule is simple: if code needs meaning, it should go through the reader.
If code only needs bytes, it may stream bytes without interpreting them.

## Approved Read Paths

Only these modules may perform direct artifact I/O:

- `cardre/artifacts.py`
- `cardre/domain/evidence.py`
- `cardre/_evidence/`
- `cardre/modeling/serialization.py`

Why:

- `cardre/artifacts.py` owns artifact write helpers and low-level store plumbing.
- `cardre/domain/evidence.py` exposes typed evidence APIs.
- `cardre/_evidence/` contains the parser, profiles, schemas, and typed models.
- `cardre/modeling/serialization.py` handles binary estimator IO and integrity checks.

## Forbidden Patterns

The guardrail scans for these direct-read shapes:

- `json.loads(...artifact_path(...).read_text())`
  - Forbidden because it bypasses typed parsing and couples callers to JSON layout.
- `artifact_path(...).read_text()`
  - Forbidden because it reads raw JSON text in production code.
- `json.load(open(...artifact_path...))`
  - Forbidden because it mixes file opening with direct JSON interpretation.
- `Path(...artifact_path...).read_text()`
  - Forbidden because it is the same raw-text read under a different spelling.
- `pl.read_parquet(...artifact_path...)`
  - Forbidden in production when used to interpret evidence JSON or report layout.
- `pl.scan_parquet(...artifact_path...)`
  - Forbidden in production when used to interpret evidence schema directly.
- `open(...artifact_path...)`
  - Forbidden unless the code is a low-level byte-streaming adapter or evidence parser.

## Allowed Inline Suppressions

Only these reasons are allowed on a line comment of the form
`# cardre-allow-artifact-read: <reason>`:

- `dataset-frame-input`
  - Legitimate when a node is consuming a dataset artifact as tabular input.
  - Example: a modelling node reading the train parquet before building features.
- `artifact-byte-download`
  - Legitimate when a route or export helper streams artifact bytes without interpreting them.
  - Example: a sidecar download endpoint copying the file to an HTTP response.
- `low-level-evidence-parser`
  - Legitimate only inside `cardre/_evidence/` or other approved low-level IO code.
  - Example: the reader opening a file before typed parsing.
- `serialization-compatibility-test`
  - Legitimate only in isolated compatibility tests that assert persisted raw layout.
  - Example: a test that checks a JSON artifact still round-trips to the expected dict.

## Adding A New Evidence Kind

When introducing a new evidence type, update all of these:

1. Add an `EvidenceKind` enum member in `cardre/_evidence/kinds.py`.
2. Add a `SCHEMA_<KIND>` constant in `cardre/_evidence/schemas.py`.
3. Add a typed dataclass and `from_json` in `cardre/_evidence/models/` (in the appropriate family module, e.g. `models/binning.py`, `models/model.py`). Re-export it from `cardre/_evidence/models/__init__.py`.
4. Add an `EVIDENCE_PROFILES` entry in `cardre/_evidence/profiles.py`.
5. Add an `AdapterSpec` entry in the `EVIDENCE_ADAPTERS` table in `cardre/_evidence/adapters/__init__.py`. Most adapters are a one-liner `AdapterSpec(profile=..., parse=lambda path, art, store: Model.from_json(...))`. Only add a custom class if the parse logic is non-trivial (e.g. `WoeTable`, `IvTable`, `ScoredDataset`).
6. Add fixture-backed parse coverage in `tests/test_evidence_adapters.py`.
7. Add a parametrized profile assertion in `tests/test_evidence_profiles.py`.

Minimal parser rule: prefer schema/version validation first, then role/type/media/profile validation inside `cardre/_evidence/`, never bespoke parsing in product nodes.

## Writing A Node That Consumes Artifacts

Use the reader first and fail clearly if the evidence is missing:

```python
reader = ArtifactEvidenceReader(store)
try:
    model = reader.find(input_artifacts, EvidenceKind.MODEL_ARTIFACT)
except EvidenceNotFoundError as exc:
    raise NodeInputError(
        "Model requires cardre.model_artifact.v1 evidence from the "
        "logistic regression step, but no matching artifact was found."
    ) from exc
```

If the node needs dataset rows, read parquet as a dataset frame and treat that
as input data, not evidence interpretation.

## Writing A Report Collector

Report collectors must reuse `ArtifactEvidenceReader`.

- Call `reader.find(...)` or `reader.read(...)` per needed evidence kind.
- Do not add custom per-collector JSON parsing.
- If a shared collector helper exists, prefer it over bespoke layout logic.

## Writing Sidecar Artifact Previews

For previews and summaries:

- Use the adapter registry directly: `get_adapter(kind).match()` / `.parse()`.
- The reader's `summarise_*` methods have been removed; summaries are no longer
  produced through `ArtifactEvidenceReader`.

The Phase 4 evidence routes at:
- ``GET /runs/{run_id}/steps/{step_id}/evidence``
- ``GET /runs/{run_id}/evidence``

also use ``ArtifactEvidenceReader`` via ``_to_item``, routing summarised
evidence to the frontend without exposing raw artifact paths.

For byte streaming only, `store.artifact_path(art)` is acceptable with the
`artifact-byte-download` suppression. Do not `json.loads` artifact bodies in a route.

## Writing Tests

- Use `tests/helpers/evidence_assertions.py` for typed assertions.
- Use raw dict assertions only in the three isolated compatibility files:
  - `tests/test_artifact_serialization.py`
  - `tests/test_evidence_reader.py`
  - `tests/test_legacy_artifact_compatibility.py`

This keeps layout assertions local and keeps production tests focused on typed behavior.

## Legacy Compatibility Policy

Legacy detection belongs in `cardre/_evidence/`.

- Product code must not know whether an artifact matched by schema or by role/type/media profile.
- If a legacy shape exists, teach the adapter/profile/model about it.
- Do not reintroduce raw JSON fallback in nodes or services.

## Guardrail Link

The guardrail failure message points here:

`docs/architecture/artifact-evidence-access.md`

That path must remain valid because the audit test references it directly.
