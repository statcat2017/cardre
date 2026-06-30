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
  1)
    printf '%s\n' "Running v2 phase 1 checks"
    ruff check
    python3 -m pytest tests/test_store.py tests/test_evidence.py tests/test_staleness.py tests/test_run_lifecycle.py tests/test_run_coordination_contract.py -q --tb=short
    ;;
  2)
    printf '%s\n' "Running v2 phase 2 checks"
    ruff check
    python3 -m pytest tests/test_manual_binning_source.py tests/test_manual_binning_phase1.py tests/test_manual_binning_gate.py tests/test_manual_binning_phase3.py tests/test_manual_binning_phase4.py -q --tb=short
    ;;
  3)
    printf '%s\n' "Running v2 phase 3 checks"
    ruff check
    python3 -m pytest tests/test_run_worker.py tests/test_run_orchestrator.py tests/test_run_coordination_contract.py tests/test_run_lifecycle.py -q --tb=short
    ;;
  4)
    printf '%s\n' "Running v2 phase 4 checks"
    ruff check
    python3 -m pytest tests/test_api_contracts.py tests/test_error_envelope.py tests/test_sidecar_api/ -q --tb=short
    (
      cd frontend
      npm ci
      npm run lint
      npm run test
      npx tsc --noEmit
    )
    ;;
  5)
    printf '%s\n' "Running v2 phase 5 checks"
    ruff check
    python3 -m pytest tests/test_launch_mode.py tests/test_reporting.py tests/test_reporting_acceptance.py tests/test_scorecard_model.py tests/test_frozen_scorecard_bundle.py tests/test_safety_rails.py -q --tb=short
    ;;
  6)
    printf '%s\n' "Running v2 phase 6 checks"
    ruff check
    CARDRE_GOVERNANCE=1 python3 -m pytest tests/test_branch_evidence_unified.py tests/test_branch_consistency.py tests/test_branch_service.py tests/test_api_contracts.py -q --tb=short
    ;;
  *)
    printf '%s\n' "Unknown v2 phase: $PHASE" >&2
    usage
    exit 2
    ;;
esac
