.PHONY: test test-cov test-fail-fast test-evidence test-python-ci typecheck typecheck-python lint lint-line-counts lint-artifact-reads audit-artifact-reads arch-check preflight

# Coverage threshold. Restored to 60% after Batch 05 closeout composed
# execution-path tests landed (SubmitRun → ExecuteRun → FinalizeRun).
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
	python3 -m pytest tests/test_evidence_adapters.py tests/test_evidence_repo_bulk.py tests/test_evidence_edges_and_artifacts.py tests/application/evidence -q --tb=short

typecheck:
	cd frontend && npx tsc --noEmit

typecheck-python:
	python3 -m mypy --config-file mypy.ini --explicit-package-bases cardre

lint: lint-line-counts lint-artifact-reads arch-check

arch-check:
	lint-imports

preflight:
	ruff check
	python3 -m mypy --config-file mypy.ini --explicit-package-bases cardre
	python3 scripts/check-line-counts.py
	python3 scripts/check_doc_references.py
	python3 scripts/check-sidecar-naming.py
	$(MAKE) arch-check
	python3 -m pytest tests/ -q --tb=short --cov-fail-under=$(PYTEST_COV_FAIL_UNDER)
	$(MAKE) lint-artifact-reads
	# Frontend checks — full gates restored for Batch 07b closeout.
	cd frontend && npm ci && npm run lint && npm run format:check && npm test
	cd frontend && npm run build && npx tsc --noEmit
	python3 scripts/generate-openapi-types.py
	git diff --exit-code -- frontend/src/api/openapi.json frontend/src/api/schema.d.ts
	python3 scripts/generate-error-codes.py
	git diff --exit-code -- frontend/src/api/errorCodes.ts

lint-line-counts:
	python3 scripts/check-line-counts.py

lint-artifact-reads: audit-artifact-reads

audit-artifact-reads:
	python3 scripts/audit_artifact_reads.py --production --fail-on production_violation
