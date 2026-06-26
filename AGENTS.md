GitHub token: stored in `.opencode/github-token`

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

Test commands:
- `npm run test -- src/api src/hooks src/components/__tests__/ProjectView` — frontend robustness tests
- `pytest tests/` — backend tests (slow; use `-k stale` for lifecycle tests)
