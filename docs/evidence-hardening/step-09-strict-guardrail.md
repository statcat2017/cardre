# Step 09 — Strict Guardrail

File: `tests/test_artifact_guardrail.py`. Plus `Makefile` + CI jobs.

## Pre-req: All production migration steps (S3..S7) and S8 complete.

## Changes to `tests/test_artifact_guardrail.py`

### 1. Delete `_EXISTING_VIOLATORS`

The allowlist section (lines ~27-38 today) is removed entirely. Any
remaining entry means a production file was not migrated — fix in the
responsible step before this one runs.

### 2. Narrow approved patterns

```python
APPROVED_PATTERNS = {
    "cardre/artifacts.py",
    "cardre/evidence.py",
    "cardre/_evidence/",          # prefix match
    "cardre/modeling/serialization.py",
}
```
Note `cardre/artifacts.py` is added (the spec lists it; check whether
it exists in the repo — if it does and reads artifacts, approve; if
not, still list for forward consistency per spec §5).

### 3. Expand the pattern regex

Match all spec §10 patterns:
```python
DIRECT_READ_RE = re.compile(
    r"json\.loads\s*\([^)]*artifact_path[^)]*read_text"
    r"|artifact_path\([^)]*\)\.read_text\(\)"
    r"|json\.load\s*\(\s*open\s*\([^)]*artifact_path"
    r"|Path\([^)]*artifact_path[^)]*\)\.read_text\(\)"
    r"|pl\.read_parquet\([^)]*artifact_path"
    r"|pl\.scan_parquet\([^)]*artifact_path"
    r"|open\s*\([^)]*artifact_path"
)
```

### 4. Honour inline suppressions

Before flagging a line, check for the trailing comment
`# cardre-allow-artifact-read: <reason>` where reason ∈
{`dataset-frame-input`, `artifact-byte-download`,
`low-level-evidence-parser`, `serialization-compatibility-test`}.
Suppressed lines are NOT counted as violations; the guardrail prints
them in a separate "suppressed" summary so reviewers can audit them.

If a suppressed line carries an invalid reason, FAIL the guardrail
with a clear message "Invalid suppression reason: X. Allowed:
...".

### 5. Separate classifications

Provide separate assertion lists for:
- production source (`cardre/`, `sidecar/`) — assert empty.
- tests — assert ONLY in the three allowed test files.
- docs — ignored.
- approved low-level IO — printed but not failed.

### 6. Strict assertion

```python
def test_no_direct_artifact_reads_in_production():
    violations = [v["file"] for v in production_violations]
    assert violations == [], (
        "Production code must read artifacts via ArtifactEvidenceReader, "
        "not raw file reads. See "
        "docs/architecture/artifact-evidence-access.md.\n"
        + "\n".join(f"  {v['file']}:{v['line']}: {v['hint']}" for v in violations)
    )
```

The `hint` per violation should suggest the reader helper to use
(mirror the audit script from S1).

### 7. Test-side assertion

```python
def test_no_direct_artifact_reads_in_tests():
    allowed_test_files = {
        "tests/test_artifact_serialization.py",
        "tests/test_evidence_reader.py",
        "tests/test_legacy_artifact_compatibility.py",
    }
    violations = [v for v in test_violations if v["file"] not in allowed_test_files]
    assert violations == [], ...
```

## CI / Makefile

Add to `Makefile` (only if a Makefile exists — confirm; one does at
repo root):
```
test-evidence:
	pytest tests/test_evidence_reader.py tests/test_evidence_profiles.py tests/test_evidence_contract.py tests/test_legacy_artifact_compatibility.py

audit-artifact-reads:
	python scripts/audit_artifact_reads.py --production --fail-on production_violation

test-launch-core:
	pytest tests/test_scorecard_model.py tests/test_frozen_scorecard_bundle.py tests/test_reporting_acceptance.py tests/test_safety_rails.py tests/test_launch_mode.py
```

Add a CI job (`.github/workflows/...`) that runs:
- `make audit-artifact-reads`
- `make test-evidence`
- `make test-launch-core`
- `pytest tests/test_artifact_guardrail.py`

PR fails if any of:
- production direct-read count > 0 outside approved modules,
- new evidence kind lacks profile tests (add a guardrail test that
  every `EvidenceKind` enum member has an `EVIDENCE_PROFILES` entry +
  a fixture-backed parse test),
- new launch node outputs an artifact without an evidence profile
  (add a guardrail test scanning `cardre/nodes/build/**` for artifact
  registrations and asserting a matching profile exists),
- report/export code adds raw artifact interpretation.

## Acceptance criteria

- `_EXISTING_VIOLATORS` deleted.
- `tests/test_artifact_guardrail.py` passes with no allowlist.
- Adding a new `json.loads(store.artifact_path(...).read_text())` to
  e.g. `cardre/services/comparison_service.py` fails CI locally.
- CI runs the new jobs.

## Do NOT do

- Do not add to `APPROVED_PATTERNS` beyond the four listed. Anything
  else is a migration defect.
- Do not disable tests to make CI green.

## Verify

```
make audit-artifact-reads
make test-evidence
make test-launch-core
pytest tests/test_artifact_guardrail.py -v
# negative test: temporarily add a raw read in a production file and confirm guardrail fails
```