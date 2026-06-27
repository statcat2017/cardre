# Phase Plan — Normalized Artifact Lineage

| Phase | Name | Description |
|-------|------|-------------|
| 1 | Schema | Add `artifact_lineage` table, indexes, bump `STORE_SCHEMA_VERSION` to 5 |
| 2 | Migration | Backfill from existing `run_steps` JSON arrays in `run_migrations()` |
| 3 | Dual-write | Populate lineage in `RunRepository.save_step` inside a transaction |
| 4 | Query rewrites | Rewrite `list_for_project`, `get_artifact_ids_for_run`, `get_artifact_ids_for_producing_step`, and sidecar route to use lineage table with SQL push-down |
| 5 | Tests | Add `tests/test_artifact_lineage.py` covering backfill, listing, filtering, duplicates, query shape |
