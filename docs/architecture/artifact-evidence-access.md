# Artifact Evidence Access

This document describes the final artifact/evidence boundary enforced by the
guardrail in `scripts/audit_artifact_reads.py`.

See `CONTEXT.md` and the evidence specs in `cardre/domain/evidence/` and `cardre/adapters/evidence/` for the source
of truth. This page is the operator-facing guide.

## Artifact vs Evidence

- An artifact is storage: a file on disk plus metadata in the store.
- Evidence is a typed interpretation of an artifact, produced by
  `EvidenceReader` (`cardre/adapters/evidence/reader.py`).
- Production code should consume evidence, not raw files.

The main rule is simple: if code needs meaning, it should go through the reader.
If code only needs bytes, it may stream bytes without interpreting them.

## Approved Read Paths

Only these modules may perform direct artifact I/O:

- `cardre/domain/evidence/` and `cardre/adapters/evidence/`
- `cardre/adapters/filesystem/artifact_store.py`

Why:

- `cardre/adapters/filesystem/artifact_store.py` owns artifact write helpers and low-level store plumbing, including binary estimator IO.
- `cardre/domain/evidence/` and `cardre/adapters/evidence/` contains the parser, profiles, schemas, and typed models.

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
  - Example: an export endpoint copying the file to an HTTP response.
- `low-level-evidence-parser`
  - Legitimate only inside `cardre/domain/evidence/` and `cardre/adapters/evidence/` or other approved low-level IO code.
  - Example: the reader opening a file before typed parsing.

## Adding A New Evidence Kind

When introducing a new evidence type, update all of these:

1. Add an `EvidenceKind` enum member in `cardre/domain/evidence/kinds.py`.
2. Add a `SCHEMA_<KIND>` constant in `cardre/domain/evidence/schemas.py`.
3. Add a typed dataclass and `from_json` in `cardre/domain/evidence/models/` (in the appropriate family module, e.g. `models/binning.py`, `models/model.py`).
4. Add an `EVIDENCE_PROFILES` entry in `cardre/adapters/evidence/profiles.py`.
5. Add an `AdapterSpec` entry in the `EVIDENCE_ADAPTERS` table in `cardre/adapters/evidence/parsers.py`. Most adapters are a one-liner `AdapterSpec(profile=..., parse=lambda path, art, store: Model.from_json(...))`. Only add a custom class if the parse logic is non-trivial (e.g. `WoeTable`, `IvTable`, `ScoredDataset`).
6. Add fixture-backed parse coverage in `tests/test_evidence_adapters.py`.

Minimal parser rule: the current versioned schema is the single accepted shape.
Adapters validate schema first, then role/type/media, and reject anything that
is not the canonical identity (see ADR 0015). No fallback readers or legacy-shape
branches may be added.
## Writing A Node That Consumes Artifacts

Nodes receive typed evidence through `InputCollection`
(`cardre/application/execution/input_collection.py`). `by_role` returns
`ArtifactRef`s; `by_kind` returns already-parsed typed evidence. Fail clearly if
the evidence is missing:

```python
models = context.inputs.by_kind(EvidenceKind.MODEL_ARTIFACT)
if not models:
    raise EvidenceNotFoundError(
        EvidenceKind.MODEL_ARTIFACT,
        candidate_artifact_ids=[],
    )
model = models[0]  # already a typed ModelArtifactV1
```

To read a specific `ArtifactRef` as typed evidence, use `read(artifact, kind)`:

```python
model_art = context.inputs.require("model", self.node_type)
model = context.inputs.read(model_art, EvidenceKind.MODEL_ARTIFACT)
```

If the node needs dataset rows, read parquet as a dataset frame (`read_dataframe`)
and treat that as input data, not evidence interpretation.

## EvidenceReader

The reader is constructed with the artifact reader and the artifact/run-step
repositories:

```python
reader = EvidenceReader(
    store,            # ArtifactReader (resolves artifact paths)
    uow.artifacts,    # ArtifactRepoPort
    uow.run_steps,    # RunStepRepoPort
)
```

Use `reader.find(artifacts, kind)`, `reader.find_optional(...)`,
`reader.read(artifact_id, kind)`, or `reader.read_dataframe(artifact)`.
`reader.read_optional` returns `None` on not-found (ambiguity is still an error).
Do not call `reader` internals or re-implement matching in product code.

## Writing A Report Collector

Report collectors reuse `EvidenceReader`.

- Call `reader.find(...)` or `reader.read(...)` per needed evidence kind.
- Do not add custom per-collector JSON parsing.
- If a shared collector helper exists, prefer it over bespoke layout logic.

## Writing Evidence Routes

Evidence routes live under `cardre/api/routes/evidence.py` and are project-scoped:

- `GET /projects/{project_id}/steps/{step_id}/evidence` — staleness explanation
  for a step.

For previews and summaries, use `EvidenceReader.find` / `read` for typed evidence.
The reader's `summarise_*` methods have been removed.

For byte streaming only, `store.resolve_path(art)` is acceptable with the
`artifact-byte-download` suppression. Do not `json.loads` artifact bodies in a route.

## Writing Tests

- Use `tests/test_evidence_adapters.py` for typed matching and parsing assertions
  against the canonical evidence identities.
- Use `tests/domain/evidence/` for typed model `from_json` round-trips and strict
  schema rejection.

## Legacy Compatibility Policy

There is no legacy-shape support. Per ADR 0015, only the current canonical
schema identity is accepted by `EvidenceReader`. Do not teach adapters,
profiles or models about older shapes, and do not reintroduce raw JSON fallback
in nodes, services, or adapters.

## Guardrail Link

The guardrail failure message points here:

`docs/architecture/artifact-evidence-access.md`

That path must remain valid because the audit test references it directly.
