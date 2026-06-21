.PHONY: test test-cov test-fail-fast typecheck lint lint-line-counts lint-artifact-reads

test:
	python3 -m pytest tests/ -q --tb=short

test-cov:
	python3 -m pytest tests/ --cov=cardre --cov=sidecar --cov-report=html

test-fail-fast:
	python3 -m pytest tests/ -x --tb=long

typecheck:
	cd frontend && npx tsc --noEmit

lint: lint-line-counts lint-artifact-reads

lint-line-counts:
	python3 scripts/check-line-counts.py

lint-artifact-reads:
	python3 scripts/scan-direct-artifact-reads.py
