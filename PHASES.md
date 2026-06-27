# Phase Plan: Branch Evidence Policy Unification

| Phase | Name | Description |
|-------|------|-------------|
| 1 | Unit-test EvidencePolicyService | Write U1-U6 tests against EvidencePolicyService to lock the contract before refactoring |
| 2 | Make executor.run_branch require branch_ctx | Refactor executor to be a pure consumer; update characterization tests |
| 3 | Wire execute_run to prepare ctx via EvidencePolicyService | Update async path to use unified policy; update test_run_orchestrator.py |
| 4 | Add RUN_SHORT_CIRCUITED diagnostic to sync path | Parity diagnostic emission; add S1-S2 tests |
| 5 | Delete branch_evidence.py | Remove duplicated resolver; update test_run_diagnostics.py |
| 6 | Add sync/async parity integration tests | Add P1-P4 tests through RunService |
| 7 | Docs + CI | Update execution-and-staleness.md; add governance CI job |
