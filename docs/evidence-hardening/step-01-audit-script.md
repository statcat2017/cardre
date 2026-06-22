# Step 01 — Audit Script

Target PRs in this step: `scripts/audit_artifact_reads.py` (new) + CI hook.

## Goal

Create a strict audit script that scans tracked Python source files for
direct artifact reads and classifies each occurrence. This script is the
authoritative tool that drives every later migration step. It must run
independently of the guardrail test.

## Context you must read first

- `scripts/scan-direct-artifact-reads.py` — existing ratchet scanner with a
  baseline. Your new script supersedes the *classification* behaviour but
  does NOT delete the ratchet script; the guardrail test in Batch E will
  decide which one CI calls.
- `tests/test_artifact_guardrail.py` — `_EXISTING_VIOLATORS` is the
  allowlist you must NOT remove in this step. Your script classifies, it
  does not enforce.
- `cardre/_evidence/reader.py` — the typed reader production code must
  use. Your script's "good" output should point developers here.

## Patterns the script must detect (from spec §10)

- `store.artifact_path(...).read_text()`
- `json.loads(store.artifact_path(...).read_text())`
- `json.load(open(store.artifact_path(...)))`
- `Path(store.artifact_path(...)).read_text()`
- `pl.read_parquet(store.artifact_path(...))`
- `pl.scan_parquet(store.artifact_path(...))`
- `open(store.artifact_path(...))`

## Classifications (output columns)

`file`, `line number`, `pattern type`, `classification`

Classifications:
- `approved_low_level_io` — file path starts with one of
  `cardre/artifacts.py`, `cardre/evidence.py`, `cardre/_evidence/`,
  `cardre/modeling/serialization.py`.
- `production_violation` — file under `cardre/` or `sidecar/` and not
  approved and not suppressed.
- `test_violation` — file under `tests/` that asserts raw artifact
  layout (excluding `test_artifact_serialization.py`,
  `test_evidence_reader.py`, `test_legacy_artifact_compatibility.py`).
- `documentation_reference` — file under `docs/` or `.md` files.
- `false_positive` — line carries the suppression comment with an
  allowed reason, OR the read is clearly a dataset frame input that the
  regex misclassified (guard with explicit suppression comment).

## Inline suppression

Honour `# cardre-allow-artifact-read: <reason>` on the same line.
Allowed reasons (spec §10):
`dataset-frame-input`, `artifact-byte-download`,
`low-level-evidence-parser`, `serialization-compatibility-test`.
Any other reason is reported as `production_violation` with the
suppression ignored, plus a separate `invalid_suppression` warning
column.

## CLI surface (spec §9 PR1)

- `python scripts/audit_artifact_reads.py` — default: scan all,
  print human-readable compact summary.
- `python scripts/audit_artifact_reads.py --production` — only
  production source.
- `python scripts/audit_artifact_reads.py --tests` — only tests.
- `python scripts/audit_artifact_reads.py --json` — machine-readable
  JSON list, one object per match.
- `--approved-modules <comma-list>` override (for testing).
- Exit code 0 always (the script reports; CI jobs decide pass/fail
  based on the JSON). Add `--fail-on production_violation` mode for CI.

## Use `git ls-files`

Use `git ls-files -- "*.py"` and filter, do not walk the filesystem,
so untracked scratch files do not pollute the audit.

## Print the helper

When a production violation is reported, include in the JSON object:
`"suggested_reader": "reader.find(<artifacts>, EvidenceKind.<KIND>)"`
and link to `docs/architecture/artifact-evidence-access.md` (this file
is authored in S10; just emit the relative path string).

## Acceptance criteria

- Run against the current repo. The script lists every match returned
  by `grep -n "artifact_path(" cardre sidecar tests` today (~78+ lines
  from the survey you can rerun).
- Docs are excluded by default.
- Production vs test vs approved classification is correct.
- `--json` output is stable enough for downstream PRs to diff
  before/after counts.
- Add a small `tests/test_audit_artifact_reads.py` smoke test that runs
  the script against a fixture tree and asserts key classifications.

## Out of scope for this step

- Do NOT modify `tests/test_artifact_guardrail.py`.
- Do NOT touch any production file in `cardre/` or `sidecar/`.
- Do NOT add or remove schema constants in `_evidence/`.

## How to verify

```
python scripts/audit_artifact_reads.py --production --json | python -m json.tool | head
python scripts/audit_artifact_reads.py --tests --json | python -m json.tool | head
pytest tests/test_audit_artifact_reads.py
```