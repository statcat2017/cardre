# CI Graph Simplification, Parallelisation, and Caching

## Status

Accepted

## Context

The current `.github/workflows/ci.yml` runs nine jobs on every push to `main`
and every PR against `main`. Several structural issues add wall-clock time and
runner-minute cost without adding safety:

1. **Serial chains gate parallelisable work.** `build-sidecar` and
   `check-api-contracts` both declare `needs: [test-python]`, even though
   neither consumes test results. `check-tauri` then `needs: [build-sidecar]`,
   producing a three-deep serial chain (tests → sidecar build → tauri check)
   that could otherwise run in two depths. The only true data dependency in
   the graph is `check-tauri` consuming the sidecar artifact.

2. **Redundant work inside jobs.** `test-frontend` runs `npx tsc --noEmit`
   even though it already `needs: [typecheck-frontend]`, which runs the same
   check. `artifact-read-guardrail` reinstalls the same Python environment as
   `test-python` and runs `tests/test_artifact_guardrail.py`, which
   `test-python`'s `pytest tests/` already collects.

3. **No pip cache.** Each of the four Python jobs runs
   `pip install -e ".[sidecar,test]"` from a cold wheel cache. `setup-python`
   supports `cache: pip` natively; the dependency file (`pyproject.toml`) is
   stable enough that cache hits should be near 100% on incremental PRs.

4. **No concurrency cancellation.** Pushing two commits to a PR branch queues
   two full CI runs; the older run is not cancelled. With nine jobs each
   setting up Python or Node from scratch, this wastes significant runner
   minutes.

5. **No least-privilege token.** The workflow has no top-level `permissions:`
   block, so the `GITHUB_TOKEN` defaults to write-all on repos where that is
   still the default. None of the jobs require write access.

6. **Two single-step lint jobs.** `check-line-counts` and
   `check_doc_references` are each one shell command in their own job. Each
   pays the full checkout + runner-startup cost for a script that runs in
   under a second.

## Decision

1. **Parallelise the graph; gate via required status checks, not via `needs`.**
   Remove `needs: [test-python]` from `build-sidecar` and
   `check-api-contracts`. Keep only the genuine data dependency:
   `check-tauri` `needs: [build-sidecar]` (it downloads the built artifact).
   Branch protection on `main` enforces that all jobs must pass before merge,
   which is the actual safety property we want — the `needs` chain was
   over-serialising without adding protection.

2. **Fold the artifact-read guardrail into `test-python`.** Delete the
   `artifact-read-guardrail` job. Move `make audit-artifact-reads` into
   `test-python` as a pre-test step so the production-read audit is enforced
   in the same job. `test_artifact_guardrail.py` is already collected by
   `pytest tests/`. Drop `make test-evidence` and `make test-launch-core`
   from CI entirely — they are strict subsets of the full suite already run.

3. **Drop redundant `npx tsc --noEmit` from `test-frontend`.** It already
   `needs: [typecheck-frontend]`, which runs the typecheck. `test-frontend`
   becomes `npm ci && npm test` only.

4. **Merge the two lint jobs into one `lint` job** with two steps, mirroring
   the `Makefile` `lint` target. Both scripts run in a single checkout.

5. **Enable `cache: pip` on every `actions/setup-python@v5` step**, keyed on
   `pyproject.toml`. Enable `cache: npm` (already present) on Node steps.

6. **Add a top-level `concurrency` block** with
   `cancel-in-progress: true`, grouped by ref. New pushes to a PR branch
   cancel superseded runs.

7. **Add top-level `permissions: { contents: read }`.** No job requires more.

8. **Add `timeout-minutes` per job** to bound runner-minute exposure on
   hangs (PyInstaller and `cargo check` are the historical offenders).

### Resulting graph

```
lint ────────────────┐
typecheck-frontend ──┤
test-python ─────────┼──> (merge gate via branch-protection required checks)
build-sidecar ───────┤
check-api-contracts ─┘
check-tauri (needs build-sidecar)
test-frontend (needs typecheck-frontend)
```

Six jobs, down from nine. Maximum serial depth: two (build-sidecar →
check-tauri), down from three.

## Consequences

- **Faster:** wall-clock CI time drops from three serial heavy stages to at
  most two. Pip cache hits cut ~30–60s per Python job. Concurrency
  cancellation prevents redundant runs on rapid PR pushes.
- **Easier:** fewer jobs to reason about; the graph matches the actual data
  dependencies.
- **Harder:** branch protection on `main` must be configured with the correct
  set of required status checks (all six job names). This is a one-time
  GitHub settings change, documented in the PR description.
- **Risk:** if branch protection is misconfigured, a failing `test-python`
  could merge alongside a green `build-sidecar`. Mitigated by requiring all
  six checks as required status checks before merge.
- **Risk:** folding `audit-artifact-reads` into `test-python` means an audit
  failure now fails the whole test job rather than a dedicated job. The
  failure message is still attributable via the step name. Acceptable
  trade-off for removing a redundant environment setup.