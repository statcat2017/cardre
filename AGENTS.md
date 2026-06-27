GitHub token: stored in `.opencode/github-token`

## Pull Requests — MANDATORY CI gate

**Never request PR review until CI is green.** This is enforced, not advisory.

The ONLY permitted way to open a PR, refresh it, or check CI is:

```
scripts/pr-gate.sh            # push + open/locate PR + poll CI until green/red
scripts/pr-gate.sh --no-open   # PR already exists; only poll CI
scripts/pr-gate.sh --timeout 600
scripts/pr-gate.sh --base main
```

The gate script:
1. pushes the current branch to origin,
2. opens a PR if none exists for the branch (or locates the existing one),
3. polls the GitHub Checks API until every check suite completes,
4. on **red**: downloads each failing job's logs to
   `.opencode/pr-gate-logs/<pr-number>/<job>.log`, prints a red banner,
   and exits non-zero. You MUST then read those log files, fix the failures,
   push, and rerun the gate. Do not ask the user to review.
5. on **green**: prints a `CI GREEN` / `Ready for human review` banner with
   the PR URL and exits 0. Only at this point may you tell the user a PR is
   ready for review.

**Direct PR/CI commands are blocked** by `.opencode/plugins/pr-gate.js` and
will be rewritten to a failed command that redirects you here. This includes:
`gh pr create|view|ready|merge|review|checks|...`, `hub pull-request`, and
`curl` against any `/pulls`, `/check-suites`, `/check-runs`, or
`/commits/<sha>/check-*` endpoint. Do not try to "peek" at CI status and then
claim green — the gate owns that.

If the gate times out (CI still running after `--timeout`), exit code 3: do
not claim ready. Re-run with a longer timeout once CI is likely finished.

Logs from the last red run live under `.opencode/pr-gate-logs/<pr-number>/`
and are safe to read with the Read tool when investigating failures.

## scikit-learn Master Skill

Installed skills:
- `sklearn-advanced` (advanced architecture, custom estimators, pipeline patterns)
- `sklearn-pipeline-builder` (pipeline building guidance)
- `sklearn-explainability` (model interpretability, SHAP, permutation importance)

These are combined into the `sklearn-master` skill at `.opencode/skills/sklearn-master/SKILL.md` and registered globally at `~/.config/opencode/skills/sklearn-master/SKILL.md`.

Use when working with scikit-learn for classification, regression, feature engineering, hyperparameter tuning, model interpretation, or production deployment.

## Robustness Testing

Canonical API error codes (from `frontend/src/api/client.ts`):
- `SIDECAR_UNREACHABLE` — fetch network rejection
- `REQUEST_TIMEOUT` — fetch did not resolve within timeoutMs
- `REQUEST_ABORTED` — caller signal aborted
- `EMPTY_OK_BODY` — 200 with empty body (not allowed)
- `EMPTY_ERROR_RESPONSE` — non-2xx with empty body
- `MALFORMED_JSON_RESPONSE` — 200 with invalid JSON
- `HTML_ERROR_RESPONSE` — non-2xx with HTML body
- `NON_JSON_ERROR_RESPONSE` — non-2xx with non-JSON body
- Server codes (e.g. `RUN_EXECUTION_FAILED`) — from `detail.code`
- `NODE_NOT_AVAILABLE_FOR_LAUNCH` — deferred node instantiated in launch mode
- `OPTIONAL_DEPENDENCY_NOT_INSTALLED` — node's optional dep group missing
- `PLAN_CONTAINS_UNAVAILABLE_NODES` — plan has unavailable nodes; rejected before run

Test commands:
- `npm run test -- src/api src/hooks src/components/__tests__/ProjectView` — frontend robustness tests
- `pytest tests/` — backend tests (slow; use `-k stale` for lifecycle tests)
