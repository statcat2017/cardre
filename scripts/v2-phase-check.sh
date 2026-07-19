#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(git -C "$SCRIPT_DIR/.." rev-parse --show-toplevel)"
cd "$ROOT_DIR"

if [[ -z "${VIRTUAL_ENV:-}" && -f ".venv/bin/activate" ]]; then
  # shellcheck disable=SC1091
  source ".venv/bin/activate"
fi

PHASE="${1:-${PHASE:-}}"

usage() {
  printf '%s\n' "Usage: scripts/v2-phase-check.sh <phase-number>" >&2
  printf '%s\n' "       PHASE=<phase-number> make v2-phase-check" >&2
}

if [[ -z "$PHASE" ]]; then
  usage
  exit 2
fi

case "$PHASE" in
  store|1)
    printf '%s\n' "Running store-layer checks"
    ruff check
    python3 -m pytest tests/test_store_repos.py tests/test_store_run_step_lookup.py tests/test_store_manual_binning_reviews.py tests/test_store_schema_no_queryable_json.py tests/test_store_transaction.py -q --tb=short
    ;;
  evidence|2)
    printf '%s\n' "Running evidence-layer checks"
    ruff check
    python3 -m pytest tests/test_evidence_adapters.py tests/test_evidence_locator.py tests/test_evidence_repo_bulk.py tests/test_evidence_policy.py tests/test_evidence_edges_and_artifacts.py -q --tb=short
    ;;
  lifecycle|3)
    printf '%s\n' "Running run-lifecycle checks"
    ruff check
    python3 -m pytest tests/test_run_lifecycle.py tests/test_run_lifecycle_errors.py tests/test_run_step_writer.py tests/test_run_audit_integrity.py -q --tb=short
    ;;
  api|4)
    printf '%s\n' "Running API checks"
    ruff check
    python3 -m pytest tests/test_api_projects.py tests/test_api_plans.py tests/test_api_runs.py tests/test_api_branches.py tests/test_api_evidence.py tests/test_api_error_envelope.py -q --tb=short
    (
      cd frontend
      npm ci
      npm run lint
      npm run test
      npx tsc --noEmit
    )
    ;;
  pathway|5)
    printf '%s\n' "Running pathway checks"
    ruff check
    python3 -m pytest tests/test_launch_pathway.py tests/test_freeze_scorecard_bundle.py tests/test_api_scorecard_launch_pathway.py tests/test_reporting.py -q --tb=short
    ;;
  governance|6)
    printf '%s\n' "Running governance checks"
    ruff check
    CARDRE_GOVERNANCE=1 python3 -m pytest -m governance -q --tb=short --no-cov
    ;;
  *)
    printf '%s\n' "Unknown phase: $PHASE (use: store, evidence, lifecycle, api, pathway, governance)" >&2
    usage
    exit 2
    ;;
esac
