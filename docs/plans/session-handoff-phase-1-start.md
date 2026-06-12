# Session Handoff: Phase 1 Start

This handoff captures the decisions and artifacts produced immediately before
Phase 1 implementation begins.

## Current Direction

Cardre is being rebuilt as a local-first, auditable desktop credit scorecard
builder. The immediate next work is Phase 1A: engine and storage proof. Do not
start real scorecard modelling nodes until Phase 1A foundation tests are green.

## Key Decisions From This Session

- Phase 1 test data is confirmed:
  - UCI Statlog German Credit Data for small deterministic smoke tests.
  - UCI Default of Credit Card Clients for medium-size import/split/profiling and later correlation tests.
- Use `polars` and `pyarrow` immediately in Phase 1A.
- Parquet is the internal canonical tabular artifact format from the start.
- Every artifact records both:
  - `physical_hash`: raw artifact bytes.
  - `logical_hash`: canonical content hash for reproducibility/staleness.
- SQLite stores metadata only. No tabular blobs in SQLite.
- Raw public datasets stay under ignored `input/credit/` and are not committed.
- German Credit import is the first meaningful implementation target.
- Taiwan Default `.xls` import can be deferred unless easy; German Credit is enough for the first green path.
- Variable clustering is now part of the fixed scorecard pathway, between initial WOE/IV diagnostics and variable selection.
- Siddiqi-aligned process steps were added to the plan: population/segment definition, good/bad/indeterminate definitions, sample/performance windows, exclusions, development sample construction, prior-probability adjustment, gains/characteristic reports, and cutoff/strategy analysis.

## Files Added Or Updated

- `docs/plans/cardre-application-plan.md`: updated main plan with Siddiqi-aligned workflow and Phase 2/4/5 changes.
- `docs/plans/cardre-application-plan.txt`: refreshed public text copy of the main plan.
- `docs/plans/cardre-workflow-overview.html`: updated mobile workflow overview.
- `CONTEXT.md`: updated build-stream workflow and node-category glossary.
- `docs/data-sources/phase-1-credit-datasets.md`: human-readable Phase 1 dataset notes.
- `docs/data-sources/phase-1-datasets.json`: machine-readable Phase 1 dataset manifest with hashes.
- `docs/plans/phase-1-execution-plan.md`: high-level Phase 1 execution plan.
- `docs/plans/phase-1-technical-implementation-plan.md`: execution-ready implementation plan for a smaller agent.
- `README.md`: linked the Phase 1 plans.

## Local Dataset Downloads

These files were downloaded locally and are ignored by git:

```text
input/credit/uci-german-credit/raw/statlog-german-credit-data.zip
input/credit/uci-default-credit-card-clients/raw/default-credit-card-clients.zip
```

Verified archive hashes:

```text
e12d9d5def6845c0622634a1cd2ab87fa470668c4298f1ec52a4e403376a435b  input/credit/uci-german-credit/raw/statlog-german-credit-data.zip
56c885f84457f6680f8438f02bfcdac9579323d8a94465ee5f26e32baa727602  input/credit/uci-default-credit-card-clients/raw/default-credit-card-clients.zip
```

## Current Mobile URL

The workflow HTML was being served through localtunnel at:

```text
https://witty-cycles-bake.loca.lt/docs/plans/cardre-workflow-overview.html
```

This tunnel may not survive session closure. The source file is:

```text
docs/plans/cardre-workflow-overview.html
```

## Verification Already Run

- Manifest JSON validation succeeded:
  - `python3 -m json.tool docs/data-sources/phase-1-datasets.json`
- Existing standard-library tests passed:
  - `python3 -m unittest discover -s tests`
- `pytest` is not installed yet; Phase 1A dependency setup should add it.

## Existing Scaffold State

The current Python scaffold in `cardre/store.py`, `cardre/audit.py`, and
`cardre/pipeline.py` proves earlier concepts but does not yet match the final
Phase 1A storage/schema/fingerprint contract. Treat it as reference material to
reshape, not as final architecture.

## Next Implementation Step

Start with PR/work chunk 1 from `docs/plans/phase-1-technical-implementation-plan.md`:

1. Add Phase 1A dependencies to `pyproject.toml`:
   - `polars`
   - `pyarrow`
   - `pydantic`
   - `pytest`
2. Implement SQLite-backed `ProjectStore` and schema initialization.
3. Add tests proving a `.cardre` project creates:
   - `cardre.sqlite`
   - `datasets/`
   - `artifacts/`
   - `exports/`
   - `logs/`
4. Do not implement nodes before the schema and artifact registration contract is in place.

## Important Guardrails

- Do not commit raw datasets.
- Do not use pandas by default.
- Do not store tabular data in SQLite.
- Do not store stale as a database status.
- Do not allow fit nodes to consume test/OOT artifacts.
- Do not mutate historical run records.
