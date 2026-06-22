.PHONY: test test-cov test-fail-fast test-evidence test-launch-core typecheck lint lint-line-counts lint-artifact-reads audit-artifact-reads

test:
	python3 -m pytest tests/ -q --tb=short

test-cov:
	python3 -m pytest tests/ --cov=cardre --cov=sidecar --cov-report=html

test-fail-fast:
	python3 -m pytest tests/ -x --tb=long

test-evidence:
	python3 -m pytest tests/test_artifact_serialization.py tests/test_evidence_reader.py tests/test_evidence_profiles.py tests/test_evidence_contract.py tests/test_legacy_artifact_compatibility.py

test-launch-core:
	python3 -m pytest tests/test_scorecard_model.py tests/test_frozen_scorecard_bundle.py tests/test_reporting_acceptance.py tests/test_safety_rails.py tests/test_launch_mode.py

typecheck:
	cd frontend && npx tsc --noEmit

lint: lint-line-counts lint-artifact-reads

lint-line-counts:
	python3 scripts/check-line-counts.py

lint-artifact-reads:
	python3 scripts/scan-direct-artifact-reads.py

audit-artifact-reads:
	python3 scripts/audit_artifact_reads.py --production --fail-on production_violation
