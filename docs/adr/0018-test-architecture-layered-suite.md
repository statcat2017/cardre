# ADR 0018 — Test architecture: invariants, port contracts, golden structures, and coverage gates

## Status

Accepted.

## Decision

Cardre's test suite is organized around a small set of deliberate patterns.
This ADR records the test architecture decisions adopted in the Batch 4C
remediation:

1. **Pure invariant suite** for domain rules that have no I/O.
2. **Critical port contract pattern** that runs each contract against both the
   real adapter and a minimal in-memory fake.
3. **Golden structural companion/comparator policy** that keeps golden
   fixtures lossless while staying independent of run-schedule volatility.
4. **Frontend coverage gate** of 60/60/60/50 (lines/statements/functions/
   branches) enforced in CI.
5. **Explicit scope deferral** of exhaustive repo-port contracts: not every
   port gets a contract test in this sprint.

## Context

The earlier test suite had a monolithic, workflow-dependent shape: a handful of
large end-to-end tests exercised one long pathway, so a single scheduling
change invalidated many unrelated assertions and coverage was concentrated in a
few files. The remediation (Batches 1–4C) split the suite into focused layers:

- **Invariants** live in `tests/domain/` (e.g. `test_invariants.py`) and assert
  pure, side-effect-free domain behaviour.
- **Port contracts** live in `tests/ports/` (e.g.
  `test_artifact_store_contract.py`) and exercise a port's observable contract.
- **Golden tests** in `tests/test_golden_*.py` assert round-trip losslessness
  and structural fidelity against checked-in fixtures under
  `tests/fixtures/`.
- **Frontend unit tests** live next to source under
  `frontend/src/**/__tests__/` and `frontend/src/**/*.test.{ts,tsx}`.

### Deciding the decisions

- **Pure invariant suite.** Domain rules that can be tested without I/O should
  be tested against pure inputs. `test_invariants.py` covers plan-topology
  validation and the run state machine as pure state-transition tables. This
  keeps the tests fast and deterministic and documents the rules as
  specifications.
- **Critical port contract pattern.** A port is the seam between the domain and
  an adapter. A contract test parametrized over the real adapter and an
  in-memory fake (both under `tests/ports/`) verifies that the observable
  behaviour the domain depends on is stable, and that the fake mirrors it.
  This catches both adapter regressions and contract drift without requiring
  heavyweight I/O in every test.
- **Golden structural companion/comparator.** Golden fixtures are committed and
  treated as immutable inputs. Tests assert round-trip losslessness (deserialize
  → re-serialize without dropping or mutating keys) rather than asserting a
  fragile exact serialization. The `test_golden_report_bundle.py` comparator
  diffs the report structure against the golden fixture while normalizing known
  non-deterministic fields, so the golden test no longer depends on a
  particular run-schedule ordering.
- **Frontend coverage gate.** Vitest thresholds of 60% lines/statements/
  functions and 50% branches are enforced via `npm run test:coverage`, which
  CI runs and `make preflight` invokes. Ordinary `npm test` remains available
  for targeted local runs and does not fail on global thresholds over unrun
  files.

### Threshold selection

Backend per-package floors are set comfortably below current measured coverage
so they act as regression guards rather than aspirational targets. As of this
ADR the floors are 75/80/80/80/70/75/75/70 (percent) for
domain/application/adapters/api/nodes/modeling/bootstrap/sidecar respectively,
with a global 60% backstop. These are recorded in
`scripts/check-coverage-thresholds.py`.

## Consequences

### Easier

- **Faster feedback.** Focused unit and contract tests run quickly and localize
  failures to a specific concern instead of an entire long pathway.
- **Deterministic golden checks.** Structural comparators ignore ordering and
  non-deterministic hashes, so golden tests are stable across scheduling
  changes.
- **Real coverage enforcement.** The frontend 60/60/60/50 gate is wired into CI
  and `make preflight`, and the backend per-package floors are enforced by
  `scripts/check-coverage-thresholds.py` in `make test-python-ci` and
  `preflight`.
- **Port contracts documented in code.** The parametrized contract tests make
  each port's observable behaviour explicit and executable.

### Harder

- **Golden fixtures must be maintained.** Changing a persisted schema requires
  regenerating the affected golden fixtures deliberately, not casually editing
  them.
- **Per-package floors must be kept honest.** Raising a floor in
  `scripts/check-coverage-thresholds.py` must accompany a real coverage
  increase; lowering one requires reopening this ADR.

## Scope deferral

Exhaustive coverage of every repo port is deferred to a future sprint. Some
ports have contract tests; those without one are still exercised indirectly
through application-level tests. This ADR records the intended pattern so
future work can extend `tests/ports/` incrementally without reopening the
architecture decision.
