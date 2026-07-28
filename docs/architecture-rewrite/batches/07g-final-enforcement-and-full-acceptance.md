# Batch 07g — Final Enforcement and Full Acceptance

## Objective

Prove the clean cut is complete. This is the only Batch 07 PR that makes final architecture enforcement blocking and runs the complete user-facing acceptance pathway after 07b, 07d, 07c, 07f, and 07e land.

## Scope

- Configure strict import-boundary enforcement with no unmatched-package escape hatch.
- Remove the migration `xfail` from `test_forbidden_imports_outside_adapters` and make the final banned-symbol/path set pass.
- Verify removed API headers, evidence packages, binning/workflow packages, `ProjectStore`, and legacy execution context have no production references.
- Finalize `tests/acceptance/test_launch_pathway.py` and remove superseded acceptance tests only after its coverage is equivalent.
- Update completion documentation only after every required gate passes.

## Prohibited

- No new compatibility shim, architecture exception, suppression, or non-strict `xfail`.
- No weakening of parity, contract, governance, artifact-read, OpenAPI, or coverage checks.
- No feature work.

## Acceptance

- Strict architecture/import checks pass and no legacy package or identifier is present.
- Full backend suite, frontend tests/typecheck/build, Tauri checks, and numerical parity suite pass.
- The 20-item product acceptance pathway passes through the new API.
- `make preflight` passes before the PR gate is run.
