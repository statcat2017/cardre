# Batch 07 — Closeout Index

The original Batch 07 brief was superseded because it combined six independently risky migrations and encouraged temporary compatibility seams. The abandoned `batch-07-cleanup` work is archived for historical reference only; do not merge or cherry-pick it.

Implement the closeout as six ordered PRs:

1. [07b — Frontend API cutover](07b-frontend-api-cutover.md)
2. [07c — Evidence-package migration](07c-evidence-package-migration.md)
3. [07d — Binning and canonical-pathway migration](07d-binning-and-canonical-pathway-migration.md)
4. [07e — ProjectStore removal and test migration](07e-project-store-removal-and-test-migration.md)
5. [07f — Legacy execution-context removal](07f-legacy-execution-context-removal.md)
6. [07g — Final enforcement and full acceptance](07g-final-enforcement-and-full-acceptance.md)

Each sub-batch owns its deletion and verification. Do not add aliases, re-exports, dual dispatch, migration `xfail`s, or other compatibility layers between them. ADR-0003 permits this clean cut because Cardre has not launched.
