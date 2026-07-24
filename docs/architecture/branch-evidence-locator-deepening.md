# Deepen Branch Evidence Lookup

## Purpose

This implementation guide fixes a correctness defect in branch report readiness
and reporting. It is written for an implementation agent.

For a branch-owned Step, `ResolvedStepRef.resolved_branch_id` identifies the
Branch whose evidence must be preferred. Current readiness and reporting code
discard that value for `resolution == "exact"` and pass `None` to the Evidence
locator. In the Evidence locator interface, `None` means baseline/full-plan
scope, not "any Branch". A branch-owned Step can therefore resolve baseline
evidence while comparison resolves branch evidence.

The change deepens the Evidence locator module: resolved Step provenance crosses
one seam, the locator implementation owns scope selection, and callers no
longer reimplement it. This improves locality and lets readiness and reporting
gain leverage from one test surface.

## Scope

Change only these production modules:

- `cardre/application/evidence/evidence_resolver.py`
- `cardre/application/reporting/contracts.py`
- `cardre/adapters/reporting/_resolve.py`

Add or extend tests only in:

- `tests/application/evidence/test_explain_staleness.py`
- `tests/application/reporting/test_generate_report.py`

Do not modify these modules in this work item:

- `cardre/application/governance/refresh_comparison.py`
- `cardre/application/governance/create_comparison.py`
- `cardre/application/reporting/export_audit_pack.py`
- `cardre/application/evidence/explain_staleness.py`
- `CONTEXT.md`
- ADRs

Those modules already pass explicit evidence scope and do not discard a
`ResolvedStepRef`. They should retain the existing lower-level locator
interface until they have resolved Step provenance to pass through the seam.

## Invariants

The implementation must preserve all of these facts.

1. `ResolvedStepRef.resolved_branch_id` is the evidence scope for both values
   of `ResolvedStepRef.resolution`.
   - An `exact` reference is a Step owned by the requested Branch. Prefer that
     Branch's evidence.
   - An `ancestor` reference is a shared Step owned by an ancestor Branch.
     Prefer the ancestor Branch's evidence.
2. The existing fallback implementation remains authoritative:
   1. branch-scoped evidence edges
   2. baseline/full-plan evidence edges
   3. latest baseline Run for the PlanVersion
   4. latest successful Run across the Plan
3. Baseline evidence remains a fallback, never the first lookup for a resolved
   Branch reference.
4. `EvidenceLocator.resolve(...)` remains unchanged. It is the lower-level
   interface for callers that genuinely have a Step ID and explicit scope.
5. Do not add a new EvidenceAdapter. This work deepens the existing Evidence
   locator module; it does not introduce a second adapter at the evidence seam.
6. Do not change schemas, persistence, route handling, or Artifact formats.

## Intended Module Shape

`EvidenceLocator` keeps two deliberately small interfaces:

```text
explicit Step ID + explicit scope  -> resolve(...)
resolved Step provenance            -> resolve_ref(...)
```

`resolve_ref(...)` is a thin entry point, not a second lookup implementation.
Its implementation delegates immediately to `resolve(...)`. The depth remains
in the existing evidence-edge walk, fallback policy, fingerprint matching, and
`ResolvedEvidence` assembly.

The deletion test is the acceptance criterion: after migration, deleting the
two caller-side `resolution == "ancestor"` conditions must remove duplication
without moving scope logic to a third module.

## Production Changes

### 1. Add `EvidenceLocator.resolve_ref`

File: `cardre/application/evidence/evidence_resolver.py`

Add `ResolvedStepRef` as a type-only import. It avoids a runtime dependency
while retaining an explicit interface type.

```python
if TYPE_CHECKING:
    from cardre.branch_step_resolver import ResolvedStepRef
    from cardre.store.db import ProjectStore
    from cardre.store.run_step_repo import RunStepRepository
```

Add this method immediately before `resolve(...)`:

```python
    def resolve_ref(
        self,
        plan_version_id: str,
        ref: ResolvedStepRef,
        *,
        plan_id: str | None = None,
        fingerprint_match: StepSpec | None = None,
    ) -> ResolvedEvidence | None:
        """Resolve evidence for a resolved Branch Step reference.

        The reference's resolved Branch owns the first lookup. ``resolve``
        retains the canonical Branch-to-baseline-to-Plan fallback.
        """
        return self.resolve(
            plan_version_id,
            ref.step_id,
            branch_id=ref.resolved_branch_id,
            plan_id=plan_id,
            fingerprint_match=fingerprint_match,
        )
```

Implementation notes:

- Do not branch on `ref.resolution`. Both `exact` and `ancestor` references
  carry the correct owner in `ref.resolved_branch_id`.
- Do not duplicate any part of `resolve(...)`.
- Do not add `resolve_ref` to `__all__`; `__all__` exports module symbols, not
  methods.
- The `from __future__ import annotations` import already exists, so the
  `TYPE_CHECKING` import is sufficient for the annotation.

### 2. Migrate report readiness

File: `cardre/application/reporting/contracts.py`

In `check_per_step_evidence`, replace the caller-side scope translation and
the `resolve(...)` call:

```python
        branch_id = ref.resolved_branch_id if ref.resolution == "ancestor" else None
        from cardre.evidence_locator import EvidenceLocator
        resolved_evidence = EvidenceLocator(store).resolve(
            plan_version_id, ref.step_id, branch_id=branch_id,
        )
```

with:

```python
        from cardre.evidence_locator import EvidenceLocator
        resolved_evidence = EvidenceLocator(store).resolve_ref(
            plan_version_id,
            ref,
        )
```

Keep all subsequent `RunStep`, Step requirement, and Artifact validation logic
unchanged. This module should only decide whether required report evidence is
present; the locator owns which evidence is selected.

### 3. Migrate report collection

File: `cardre/adapters/reporting/_resolve.py`

In `_resolve_run_step`, replace:

```python
    branch_id = ref.resolved_branch_id if ref.resolution == "ancestor" else None
    resolved = EvidenceLocator(store).resolve(
        plan_version_id, ref.step_id, branch_id=branch_id,
    )
```

with:

```python
    resolved = EvidenceLocator(store).resolve_ref(
        plan_version_id,
        ref,
    )
```

Keep the inherited-evidence limitation unchanged. It describes the provenance
reported to users, not the locator's lookup scope:

```python
    if rs is not None and ref.resolution == "ancestor" and add_limitation is not None:
        ...
```

That condition must remain because it is report content, not a duplicate
evidence-selection policy.

## Test Implementation

### Test Fixture Requirement

Use a real `ProjectStore` and SQLite rows. Do not mock the locator's fallback
implementation in its direct tests.

Extend the existing `_seed_with_run_evidence(...)` fixture pattern in
`tests/application/evidence/test_explain_staleness.py` so one PlanVersion has:

| Evidence source | Run `branch_id` | `RunStep` ID | Purpose |
| --- | --- | --- | --- |
| baseline | `NULL` | `baseline_rs_id` | proves fallback exists |
| owned Branch | `branch-owned` | `owned_rs_id` | proves exact provenance wins |
| ancestor Branch | `branch-ancestor` | `ancestor_rs_id` | proves inherited provenance wins |

Every candidate must have an evidence edge for the same `plan_version_id` and
`step_id`. Give each candidate a distinct `run_step_id`; the assertions must
never rely solely on `source_label`.

A helper shaped like this is sufficient:

```python
def _add_successful_evidence(
    store,
    *,
    plan_version_id: str,
    step_id: str,
    parent_step_id: str,
    branch_id: str | None,
) -> tuple[str, str]:
    """Insert a succeeded Run, RunStep, and evidence edge.

    Return ``(run_id, run_step_id)``. Use a unique logical-output hash for
    each row only to make fixture debugging easier.
    """
    ...
```

Reuse the existing SQL column sets from `_seed_with_run_evidence(...)` rather
than inventing a second persistence shape.

### Direct Locator Tests

File: `tests/application/evidence/test_explain_staleness.py`

Import the existing domain reference type:

```python
from cardre.branch_step_resolver import ResolvedStepRef
from cardre.evidence_locator import EvidenceLocator
```

Add these cases to a `TestEvidenceLocatorResolvedRefs` class.

#### Exact Branch selects its own evidence

```python
def test_resolve_ref_prefers_exact_branch_evidence(tmp_path):
    store = _make_store(tmp_path)
    _, _, pv_id, step_id, _, _ = _seed_with_run_evidence(store)
    _, owned_rs_id = _add_successful_evidence(
        store,
        plan_version_id=pv_id,
        step_id=step_id,
        parent_step_id="step-root",
        branch_id="branch-owned",
    )
    ref = ResolvedStepRef(
        requested_branch_id="branch-owned",
        resolved_branch_id="branch-owned",
        canonical_step_id=step_id,
        step_id=step_id,
        resolution="exact",
    )

    resolved = EvidenceLocator(store).resolve_ref(pv_id, ref)

    assert resolved is not None
    assert resolved.run_step_id == owned_rs_id
    assert resolved.source_label == "branch"
```

This is the primary regression test. It fails against the current readiness and
reporting translation because those callers pass `None` for an exact reference.

#### Ancestor Branch selects ancestor evidence

```python
def test_resolve_ref_prefers_ancestor_branch_evidence(tmp_path):
    store = _make_store(tmp_path)
    _, _, pv_id, step_id, _, _ = _seed_with_run_evidence(store)
    _, ancestor_rs_id = _add_successful_evidence(
        store,
        plan_version_id=pv_id,
        step_id=step_id,
        parent_step_id="step-root",
        branch_id="branch-ancestor",
    )
    ref = ResolvedStepRef(
        requested_branch_id="branch-child",
        resolved_branch_id="branch-ancestor",
        canonical_step_id=step_id,
        step_id=step_id,
        resolution="ancestor",
    )

    resolved = EvidenceLocator(store).resolve_ref(pv_id, ref)

    assert resolved is not None
    assert resolved.run_step_id == ancestor_rs_id
    assert resolved.source_label == "branch"
```

#### Missing Branch evidence falls back to baseline

```python
def test_resolve_ref_falls_back_to_baseline_evidence(tmp_path):
    store = _make_store(tmp_path)
    _, _, pv_id, step_id, _, baseline_rs_id = _seed_with_run_evidence(store)
    ref = ResolvedStepRef(
        requested_branch_id="branch-without-run",
        resolved_branch_id="branch-without-run",
        canonical_step_id=step_id,
        step_id=step_id,
        resolution="exact",
    )

    resolved = EvidenceLocator(store).resolve_ref(pv_id, ref)

    assert resolved is not None
    assert resolved.run_step_id == baseline_rs_id
    assert resolved.source_label == "full_plan"
```

This confirms that the change alters precedence, not fallback availability.

### Consumer Tests

The direct tests prove the deep locator implementation. The consumer tests
prove that both callers cross its new interface and do not recreate scope
translation locally.

#### Readiness forwards the complete reference

File: `tests/application/reporting/test_generate_report.py`

Test `check_per_step_evidence(...)` directly. Use `monkeypatch` to replace
`EvidenceLocator.resolve_ref` with a spy that returns a known
`ResolvedEvidence`. The test must assert object identity for the reference:

```python
def test_per_step_readiness_passes_resolved_ref_to_locator(store, monkeypatch):
    from cardre.branch_step_resolver import ResolvedStepRef
    from cardre.evidence_locator import EvidenceLocator
    from cardre.readiness.step_requirements import check_per_step_evidence

    ref = ResolvedStepRef(
        requested_branch_id="branch-owned",
        resolved_branch_id="branch-owned",
        canonical_step_id="step-a",
        step_id="step-a",
        resolution="exact",
    )
    calls = []

    def resolve_ref(self, plan_version_id, received_ref, **kwargs):
        calls.append((plan_version_id, received_ref, kwargs))
        return None

    monkeypatch.setattr(EvidenceLocator, "resolve_ref", resolve_ref)
    blockers = []
    check_per_step_evidence(
        store,
        ["step-a"],
        {"step-a": ref},
        "plan-version-id",
        "branch",
        blockers,
    )

    assert calls == [("plan-version-id", ref, {})]
```

The expected blocker is not important in this test. Its purpose is to prove
the readiness module hands the unmodified reference to the locator interface.

#### Reporting forwards the complete reference

Also in `tests/application/reporting/test_generate_report.py`, test `_resolve_run_step(...)` directly with
the same spy pattern. Return a constructed `ResolvedEvidence` containing a
real or minimal `RunStep`, then assert the returned RunStep is the one supplied
by the locator.

```python
def test_reporting_passes_resolved_ref_to_locator(store, monkeypatch):
    from cardre.branch_step_resolver import ResolvedStepRef
    from cardre.evidence_locator import EvidenceLocator
    from cardre.reporting._resolve import _resolve_run_step

    # Construct ``ref`` with resolution="exact" and a non-empty
    # ``resolved_branch_id``. Make the fake locator record that exact object.
    # Return a ResolvedEvidence carrying a known branch RunStep.
    ...

    actual = _resolve_run_step(store, ref, "plan-version-id")

    assert actual is branch_run_step
    assert calls == [("plan-version-id", ref, {})]
```

Do not assert that an `exact` reference emits
`INHERITED_BRANCH_EVIDENCE`; it must not. Retain an existing or add a focused
ancestor test that confirms only `resolution == "ancestor"` emits that report
limitation after the migration.

## Negative Checks

Before marking the work complete, inspect the changed production files for
these unwanted shapes:

```python
# Do not leave either evidence-selection condition behind.
ref.resolved_branch_id if ref.resolution == "ancestor" else None

# Do not duplicate the locator implementation in resolve_ref.
get_edges_for_plan_step_branch(...)
```

The `ancestor` condition that creates the reporting limitation in
`cardre/adapters/reporting/_resolve.py` is allowed. It is not evidence selection.

## Verification

Run these commands after implementation:

```bash
pytest tests/test_evidence_locator.py tests/test_reporting.py
ruff check cardre/evidence_locator.py cardre/readiness/step_requirements.py cardre/reporting/_resolve.py tests/test_evidence_locator.py tests/test_reporting.py
make preflight
```

Expected outcomes:

- Exact Branch references select their Branch RunStep ahead of a baseline RunStep.
- Ancestor references select the ancestor Branch RunStep ahead of a baseline RunStep.
- A Branch with no evidence falls back to baseline evidence.
- Readiness and reporting pass the same `ResolvedStepRef` to the locator.
- Existing explicit-scope `resolve(...)` callers behave unchanged.
- No persistence migration, new domain term, or ADR is required.

## Review Checklist

- [ ] `resolve_ref(...)` delegates directly to `resolve(...)`.
- [ ] `resolve_ref(...)` uses `ref.resolved_branch_id` unconditionally.
- [ ] Readiness has no caller-side evidence scope translation.
- [ ] Reporting has no caller-side evidence scope translation.
- [ ] Reporting still records inherited provenance for ancestor references.
- [ ] Direct tests use distinct Branch and baseline RunStep IDs.
- [ ] Consumer tests prove both callers cross the provenance-aware locator interface.
- [ ] Focused tests, Ruff, and preflight pass.
