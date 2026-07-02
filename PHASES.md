# Phase Plan: Merge v2 → main

| Phase | Name | Description |
|-------|------|-------------|
| 1 | Quick wins | Remove banned hack, dead LEGACY SQL, add exports table, fix manual_binning routes, fix comparison_service imports, collapse frontend schema.ts |
| 2 | Delete compat shims + repoint importers | Delete cardre/audit.py, cardre/evidence.py, cardre/errors.py Result/Ok/Degraded, cardre/evidence_locator.py, cardre/step_id.py. Repoint all 33+ importers to cardre.domain.* / cardre.execution.context / cardre.nodes.contracts / cardre._evidence.* |
| 3 | Clean up store repos | Delete dead methods in run_repo.py (save_step, get_artifact_ids_for_run, get_artifact_ids_for_producing_step), remove v1 branches in plan_repo.py, remove hasattr guards, move concurrent-run rejection to RunCoordinator |
| 4 | Extend EvidenceResolver return type | Change resolve() to return ResolvedEvidence bundling EvidenceEdge/EvidenceArtifact objects; update executor to consume pre-built evidence; add transaction-scoped insert methods to EvidenceRepository |
| 5 | Write missing Phase 1 tests | 10 test files for domain kernel + store schema invariants |
| 6 | Fix acceptance test | Replace skipped test_launch_pathway with real executor-driven test using a small test node |
| 7 | Merge gate | ruff check --fix, make preflight, scripts/pr-gate.sh --base main |
