.PHONY: test test-cov test-fail-fast test-evidence test-launch-core test-governance test-python-ci typecheck typecheck-python lint lint-line-counts lint-artifact-reads audit-artifact-reads preflight v2-phase-check

# Next target: 65 after more characterization tests land.
PYTEST_COV_FAIL_UNDER ?= 60

test:
	python3 -m pytest tests/ -q --tb=short

test-cov:
	python3 -m pytest tests/ --cov=cardre --cov=sidecar --cov-report=html

test-python-ci:
	python3 -m pytest tests/ -q --tb=short --cov-fail-under=$(PYTEST_COV_FAIL_UNDER)

test-fail-fast:
	python3 -m pytest tests/ -x --tb=long

test-evidence:
	python3 -m pytest tests/test_evidence_adapters.py tests/test_evidence_locator.py tests/test_evidence_repo_bulk.py tests/test_evidence_policy.py tests/test_evidence_edges_and_artifacts.py -q --tb=short

test-launch-core:
	python3 -m pytest tests/test_launch_pathway.py tests/test_api_scorecard_launch_pathway.py tests/test_freeze_scorecard_bundle.py -q --tb=short

test-governance:
	CARDRE_GOVERNANCE=1 python3 -m pytest -m governance -q --tb=short --no-cov

typecheck:
	cd frontend && npx tsc --noEmit

typecheck-python:
	python3 -m mypy

lint: lint-line-counts lint-artifact-reads

preflight:
	ruff check
	python3 -m mypy
	python3 scripts/check-line-counts.py
	python3 scripts/check_doc_references.py
	python3 scripts/check-sidecar-naming.py
	python3 -m pytest tests/ -q --tb=short --cov-fail-under=$(PYTEST_COV_FAIL_UNDER)
	$(MAKE) test-governance
	$(MAKE) lint-artifact-reads
	cd frontend && npm ci && npm run lint && npm run format:check && npm run build && npx tsc --noEmit && npm test
	python3 scripts/generate-openapi-types.py
	git diff --exit-code -- frontend/src/api/openapi.json frontend/src/api/schema.d.ts

v2-phase-check:
	bash scripts/v2-phase-check.sh "$(PHASE)"

lint-line-counts:
	python3 scripts/check-line-counts.py

lint-artifact-reads: audit-artifact-reads

audit-artifact-reads:
	python3 scripts/audit_artifact_reads.py --production --fail-on production_violation
