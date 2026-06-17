.PHONY: test test-cov test-fail-fast typecheck

test:
	python3 -m pytest tests/ -q --tb=short

test-cov:
	python3 -m pytest tests/ --cov=cardre --cov=sidecar --cov-report=html

test-fail-fast:
	python3 -m pytest tests/ -x --tb=long

typecheck:
	cd frontend && npx tsc --noEmit
