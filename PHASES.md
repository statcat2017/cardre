# v2 Implementation Phases — Retrospective

All 8 phases are complete on the `v2` branch. The table below records what
each phase delivered and where the decision log lives.

| Phase | Name | Status | Description |
|-------|------|--------|-------------|
| 1 | Domain kernel + relational store | ✅ Done | Domain kernel with zero I/O deps; clean relational schema (evidence_edges, evidence_artifacts, plan_step_edges); store_meta version check; no queryable JSON arrays. [Log](docs/plans/v2/decision-logs/phase-1.md) |
| 2 | Manual-binning domain + minimal API/UI spike | ✅ Done | Delete compat shims; repoint 33 importers; PlanMutationService with draft-version creation; minimal API skeleton; UI spike end-to-end. [Log](docs/plans/v2/decision-logs/phase-2.md) |
| 3 | Execution layer | ✅ Done | RunCoordinator (single entrypoint); per-step evidence persistence inside run transaction; execute_created_run recovers from runs table; RunStep/RunStepEvidenceView split; staleness reads evidence_edges. [Log](docs/plans/v2/decision-logs/phase-3.md) |
| 4 | Full project-scoped API + frontend types | ✅ Done | 13 route modules under /projects/{id}; plans/plan-versions distinct; governance via Depends(); generated frontend types; consistent error envelope. [Log](docs/plans/v2/decision-logs/phase-4.md) |
| 5 | Launch scorecard pathway + reporting + exports | ✅ Done | 13-node launch DAG wired; test_launch_pathway.py (executor-level smoke test); report/export services ported from v1. [Log](docs/plans/v2/decision-logs/phase-5.md) |
| 6 | Governance + deferred nodes + final cleanup | ✅ Done | Branch/comparison/champion services; deferred ML nodes; tests_v1/ deleted; full make preflight green. [Log](docs/plans/v2/decision-logs/phase-6.md) |
| 7 | Project scope guards + launch execution restoration | ✅ Done | Post-hoc fix phase: registry-safety health check; finish_run backstop; policy/docs alignment; sidecar hardening. [Log](docs/plans/v2/decision-logs/phase-7.md) |
| 8 | v2 acceptance completion | ✅ Done | Closes Phase 3/4 DoD gaps: runs-table request columns (real columns, not metadata_json); POST /projects bootsraps fresh store; manual-binning lifecycle proof; full scorecard API acceptance test (test_api_scorecard_launch_pathway.py); 4 bug fixes; retroactive decision logs. [Log](docs/plans/v2/decision-logs/phase-8.md) |

**Original plan vs reality:** The original plan described 6 phases with a
merge gate at the end of Phase 6. In reality:
- Phase 7 was added post-hoc to fix launch execution and sidecar hardening gaps.
- Phase 8 closes acceptance-test gaps (runs-table columns, POST /projects
  bootstrap, manual-binning lifecycle proof, API-level acceptance test).
- The 13-node DAG described in the original plan became 15 nodes after
  `DefineModellingMetadataNode` and `FrozenScorecardBundleNode` were added.
- Decision logs (Principle 12) were not written during the original build;
  they were written retroactively in Phase 8.
- `test_launch_pathway.py` is the executor-level smoke test; the API-level
  acceptance test is `test_api_scorecard_launch_pathway.py`.
