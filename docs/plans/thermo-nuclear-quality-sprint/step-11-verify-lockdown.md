# PR11 — Verify, lock-down, decision log

**Findings:** All (verification step)
**Batch:** I (last, after all prior batches merged)
**Depends on:** all prior PRs
**Behaviour change:** No

## Goal

Verify the entire sprint. Every finding is resolved. `make preflight` is
green. The audit script confirms zero `_raw` accesses in production
node/reporting code. Docs are updated. A decision log records the
structural decisions.

## Tasks

### 1. Run the full gate

```bash
. .venv/bin/activate
ruff check --fix
make preflight
cd frontend && npm run typecheck && npm test
cd ..
pytest tests/ -q
```

All must pass. If any fail, trace to an incomplete prior PR and return
to that PR.

### 2. Audit `_raw` accesses

```bash
rg '_raw' cardre/nodes cardre/reporting cardre/services/comparison_service.py --type py -c
```

Expected: 0 in every file. If any remain, complete the migration (PR3*
or a follow-up).

### 3. Audit dead-subsystem removal

```bash
rg 'EvidenceResolver|BranchRunEvidence|ShortCircuitResult|prepare_branch_evidence|resolve_parent_evidence|check_to_node_current|write_reused_run_step|_reuse_run_step|precomputed_outputs|precomputed_records' cardre --type py
```

Expected: 0 (all deleted by PR4).

### 4. Audit adapter boilerplate

```bash
rg '^class .*Adapter' cardre/_evidence/adapters --type py | wc -l
```

Expected: ≤3.

### 5. Audit file sizes

```bash
find cardre -name '*.py' -not -path '*/__pycache__/*' | xargs wc -l | awk '$1>1000 && $2!="total"'
```

Expected: 0 files over 1000 lines.

### 6. Audit god-functions

Verify `ValidationMetricsNode.run` < 100 lines and
`VariableClusteringNode.run` < 80 lines.

### 7. Audit German-credit fixture

```bash
rg 'GERMAN_CREDIT_COLUMNS' cardre/nodes cardre/nodes/__init__.py cardre/nodes/registry.py
```

Expected: 0.

### 8. Audit frontend

```bash
cd frontend && npm run typecheck
rg 'firstQueryError|QUERY_SOURCES|code:\s*string|stuck' src --type ts --type tsx
rg 'any' src/api/client.ts
```

### 9. Run the full audit script

```bash
python scripts/audit_quality.py --json
```

All metrics at target. Include the final counts in the PR description.

### 10. Update documentation

1. `docs/architecture/artifact-evidence-access.md` — update with new
   evidence kinds (4 diagnostics + `ManualBinningOverrides`).
2. `docs/reference/evidence-kinds.md` — update with the new kinds.
3. `docs/reference/node-catalogue.md` — if `ImportGermanCreditNode` was
   demoted/removed, update.
4. `CONTEXT.md` — if the `EvidenceAdapter` design changed (table vs
   classes), update.
5. `docs/README.md` — if new docs were added, update the index.
6. `docs/plan-reviews/013-thermo-nuclear-codebase-review.md` — add a
   "## Resolution" section with a table cross-referencing each finding
   to the PR that resolved it.

### 11. Write the decision log

Create `docs/plans/thermo-nuclear-quality-sprint/decision-log.md`:

- **Adapter table vs classes** (T2/PR2) — why the table replaced 40
  classes.
- **`ModelArtifactV1` typed properties first, retirement later** (T1c/PR2)
  — why properties were added before consumers were migrated, and when
  the duplicate representations will be retired.
- **Reuse-subsystem deletion** (T3/PR4) — the product decision (Option A
  or B), why, and what docs/ADRs were updated.
- **Section-collector registry** (T5/PR5) — why the registry replaced
  the god-class.
- **`RunStatus` enum + transition** (SE3/PR8) — why the string state
  machine was replaced.
- **`prep.py` split + German-credit relocation** (T5/PR6) — why the
  fixture was moved out of production launch-tier code.
- **`BinningNode` dispatcher collapse** (N1/PR6) — why the sub-nodes
  became functions.
- **react-query adoption for run polling** (F7/PR10) — why the hand-rolled
  polling was replaced.

Each entry: date, finding ID, decision, rationale, PR number.

### 12. Update the review document

In `docs/plan-reviews/013-thermo-nuclear-codebase-review.md`, append:

```
## Resolution

All findings resolved as of <date>. See
`docs/plans/thermo-nuclear-quality-sprint/decision-log.md` for structural
decisions.

| Finding | PR | Resolution |
|---|---|---|
| T1 | PR2, PR3a, PR3b, PR3c | ... |
| T2 | PR2 | ... |
| ... | ... | ... |
```

### 13. Retire duplicate model-artifact representations (if safe)

If all consumers are migrated off `_raw` and the golden model artifact
round-trip tests pass:

1. Delete `cardre/_evidence/models/model.py:ModelArtifact` (or alias to
   `ModelArtifactV1`).
2. Change `build_model_artifact` to return `ModelArtifactV1` (or emit a
   dict that round-trips cleanly through `ModelArtifactV1.from_dict`).
3. Update `cardre/modeling/adapters.py` `apply_*` to take
   `ModelArtifactV1`.
4. Delete the boundary violation comment at `adapters.py:6-9` ("#218").
5. Run the full test suite + golden diffs.

**If this is too risky for one PR, defer to a follow-up PR after the
sprint.** The sprint's DoD is "typed properties exist and consumers use
them" — full retirement of the duplicate representation is a bonus.

## Acceptance criteria

- [ ] `make preflight` green.
- [ ] `cd frontend && npm run typecheck && npm test` green.
- [ ] `pytest tests/ -q` green.
- [ ] All audit commands (tasks 2-8) return expected counts.
- [ ] `scripts/audit_quality.py --json` all metrics at target.
- [ ] `docs/plans/thermo-nuclear-quality-sprint/decision-log.md` exists.
- [ ] `docs/plan-reviews/013-thermo-nuclear-codebase-review.md` has a
  "## Resolution" section.
- [ ] No file in `cardre/` exceeds 1000 lines.
- [ ] (Bonus, if safe) `_evidence/models/model.py:ModelArtifact` retired
  or aliased.

## Do not

- Do not implement new features. This is verification + documentation.
- Do not force the model-artifact retirement if the round-trip tests
  fail — defer it.