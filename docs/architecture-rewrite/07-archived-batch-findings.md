# Batch 07 Archived-Branch Findings

## Purpose

This is a guardrail document for the revised Batch 07 closeout. It records why the prior all-at-once cleanup did not complete the refactor, so a sub-batch agent does not repeat its shortcuts. It is not an implementation source: do not merge, cherry-pick, copy compatibility code from, or otherwise revive the archived branch.

## Evidence reviewed

- Archived branch: `archive/batch-07-cleanup-d982a11`.
- Relevant commits: `c19c3dd` and `d982a11`.
- Baseline: the branch diverged from the merged 7a API surface at `bd0da14`.

The findings below describe the archived branch's final tree. They do not rely on a claim that its test suite was green or red.

## Findings

### One change attempted six migrations

`c19c3dd` changed 136 files while mixing evidence and binning relocation, scorecard-pathway movement, persistence deletion, execution compatibility, tests, acceptance coverage, and architecture enforcement. It changed neither `cardre/api/` nor `frontend/`, so the API and frontend cutover was not part of the implementation. The legacy project headers consequently remained in the API, generated contract, frontend client, and tests.

**Rule:** implement only the sub-batch currently assigned. Merge in the order `07b -> 07d -> 07c -> 07f -> 07e -> 07g`; do not combine a later deletion, acceptance gate, or unrelated consumer cutover with it.

### Packages were deleted before their callers were migrated

The branch deleted `cardre/store/`, but retained `ProjectStore` by moving that class into `cardre.adapters.sqlite.connection`. It also retained `ExecutionContext`, `NodeOutput`, and many `context.store` callers in deferred nodes and shared helpers. Deleting a package name therefore did not remove the legacy persistence and execution architecture.

**Rule:** a deletion PR begins with a production-caller inventory and ends with a zero-result production search for the removed surface. 07f removes node and helper callers before 07e deletes legacy persistence. Renaming a legacy facade or moving its name to a new package is not migration completion.

### Compatibility bridges preserved two architectures

The archived branch added an `ArtifactEvidenceReader` backward-compatibility wrapper around the port-based reader. `LogisticRegressionNode.run()` also used `hasattr(context, "inputs")` to dispatch between `NodeContext` and `ExecutionContext`. Both patterns keep old callers viable and make it unclear which path is authoritative.

**Rule:** do not add aliases, re-exports, wrappers, attribute/type dispatch, or fallback request shapes. A migrated concept has one implementation and one execution path. 07f must remove the legacy context and dispatch in the same PR; 07b must remove the old headers on both client and server.

### Enforcement was weakened to admit violations

The branch added `importlinter` `ignore_imports` exceptions for forbidden domain-to-bootstrap and node-to-adapter dependencies. It kept `test_forbidden_imports_outside_adapters` as a non-strict `xfail`, including an allowlist for a domain pathway importing bootstrap code. This converts an architecture violation into configuration rather than removing the dependency.

**Rule:** an intermediate sub-batch may retain only the migration allowances already documented in the revised plan. It must not add a new import-linter exception, architecture allowlist, suppression, or non-strict `xfail`. 07g is the only batch that makes final enforcement strict, after the owned legacy surfaces are actually gone.

### Tests were excluded instead of migrated

The branch's collection hook dynamically marked 59 whole test modules `xfail`; its final tree also contained 30 explicit `pytest.mark.xfail` occurrences. The excluded set included numerical parity, golden fixtures, run-audit integrity, node behavior, store behavior, and the old launch pathway. This hid the exact behavior needed to prove a clean cut.

The new `tests/acceptance/test_launch_pathway.py` exercised a single noop plan and only 11 abbreviated checks. It did not replace the header-dependent scorecard launch test, which remained in place, nor did it cover the 20-item product acceptance pathway.

**Rule:** retain and migrate behavioral-oracle tests as their owning implementation changes. Do not add a broad collection-time `xfail` or weaken an assertion to obtain a passing suite. Only 07g replaces the old acceptance tests, and only after its new test covers the full product pathway.

### Dependency order was implicit rather than enforced

The archived branch moved evidence and binning together even though the legacy evidence package imports binning schema constants. It also mixed node-context work with `ProjectStore` deletion. Those dependencies made review unable to distinguish a completed migration from an unverified bridge.

**Rule:** preserve the revised dependency boundaries. 07d relocates binning and the pathway first; 07c then removes `_evidence`. 07f eliminates deferred-node legacy callers first; 07e then deletes their infrastructure. Each PR must state and verify the zero-search condition that enables its successor.

## Required Agent Checklist

Before editing:

- Read this document, the current sub-batch brief, and its predecessor's accepted state.
- Search the production tree for every legacy symbol and package owned by the sub-batch. Record the initial results in the PR description or implementation report.
- Confirm the branch contains no commit from `batch-07-cleanup` or `archive/batch-07-cleanup-d982a11`.

Before requesting review:

- Delete the legacy surface owned by the current sub-batch, not merely its old file path.
- Re-run the owned production searches and require zero matches, subject only to explicit exemptions in that sub-batch brief.
- Verify no alias, wrapper, dispatch bridge, `ignore_imports` entry, new architecture allowlist, or migration `xfail` was introduced.
- Run the brief's focused tests and `make preflight`.
- Leave unrelated migrations, final enforcement, and full product acceptance to their named owner.

## Mapping To Revised Batches

| Batch | Guardrail from the archived failure |
|---|---|
| 07b | Remove project headers from client, server, contract, fixtures, and tests in one focused consumer cutover. |
| 07d | Move binning and the pathway first; delete `engine` and `workflows` only after every importer moves. |
| 07c | Move evidence only after 07d; delete `_evidence` without a re-export or reader wrapper. |
| 07f | Port every deferred node and helper; delete `ExecutionContext`, `NodeOutput`, and dual dispatch instead of retaining bridges. |
| 07e | Migrate all production callers and tests from `ProjectStore` and ambient configuration before deleting the old persistence surfaces. |
| 07g | Remove temporary migration allowances, make enforcement strict, and prove the complete 20-item acceptance pathway without weakening parity or golden tests. |
