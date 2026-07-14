# Plan Review 013: Thermo-Nuclear Codebase Quality Audit

This is the first **code-quality audit** of the Cardre implementation (the
prior 012 reviews were forward-looking *plan* reviews). It is a
thermo-nuclear review: unusually strict, focused on implementation quality,
maintainability, abstraction quality, and codebase health. It actively
searches for "code judo" moves — restructurings that preserve behavior while
making the implementation dramatically simpler, smaller, more direct, and
more elegant.

## Scope and method

**Scope:** whole codebase at HEAD on `main`.

- ~35k LOC Python engine (`cardre/`), ~31 LOC sidecar, ~4.6k LOC frontend
  (TS/TSX, one 2.4k-line generated `schema.d.ts`), ~18k LOC tests, ~370 LOC
  Rust Tauri shell.
- 164 Python files across 12 packages. 22 files >500 lines, 4 >800, 1 >1k.

**Method:** six parallel deep audits, each scoped to a package cluster and
run with the full thermo-nuclear rubric (structural regressions → code-judo
opportunities → spaghetti/branching → boundary/type contracts → file-size →
modularity → legibility). Each subagent read the heavy files in full and
sampled lighter ones. ~80 raw findings were consolidated below into 7
cross-cutting themes and 30 cluster-specific findings.

## Verdict

**Do not approve.** Five presumptive blockers are present. The codebase is
salvageable — the right patterns already exist in pockets (`_classifier_base`,
`_training_utils`, `_bin_mask`, `_logit_helpers`, `selection_policy`,
parameterized SQL, generated OpenAPI types, the `RunLifecycle` context
manager) — but the typed-evidence layer is the load-bearing abstraction for
the whole engine and it is only ~50% used. That single root cause accounts
for the majority of the highest-conviction findings.

## Treatment classification

Not all findings are equally urgent. This audit separates **severity**
(how bad the quality problem is) from **treatment priority** (what order to
fix in). The sprint plan uses this classification to sequence work — see
[`docs/plans/thermo-nuclear-quality-sprint/README.md`](../plans/thermo-nuclear-quality-sprint/README.md).

| Treatment | Findings | Rationale | When |
|---|---|---|---|
| **Correctness risk — fix first** | T1a (missing diagnostics kinds), T1b (manual-binning raw dict), T7 (lossy bin-override round-trip), SE2 (non-atomic `to_node` half-applied failure), SE5 (non-atomic comparison refresh) | These can cause silent data loss, wrong results, or half-applied state. | Before any structural refactor. |
| **Architectural drag — fix after safety net** | T1c (three model-artifact representations), T2 (adapter boilerplate), T3 (dead reuse subsystem), T4 (node boilerplate), T5 (god-files), T6 (duplicated resolver), SE3 (string status machine), SE4 (coordinator re-query) | These make the codebase harder to reason about and invite future bugs, but current behaviour is correct. | After PR0 safety net + PR1 low-risk dedup. |
| **Hygiene — batch into small cleanup PRs** | K3 (`list[Any]` on aggregates), K4 (enum aliases), K5 (stale docstrings), SE6 (`_json_ready` dup), SE7 (`branch_id` triple-read), SE8 (pure re-export), A4 (errors.py doubled), A8 (`__version__` hardcode), A9 (sidecar argv), N4 (magic strings), N5 (reflection helper), F8 (dead styles), F9 (asymmetric state), F10 (no timeout) | Low semantic risk, high annoyance factor. | Parallel with architectural work. |
| **Spec / product decision required** | T3 (branch evidence reuse) | Deletion vs implementation is a product decision, not a code-quality one. ADRs 0004/0005/0013 and `branch-evidence-policy-unification.md` describe the intended design. | Decide before deleting. |
| **Frontend / Tauri — independent** | F1-F7, F10 | No backend dependency; can run any time. | Any time. |

---

## Cross-cutting themes (highest conviction)

These span multiple clusters and are the blockers.

### T1 — The typed-evidence layer is half-used: `_raw` dict access pervades the engine

**Severity:** blocker · **Category:** structural-regression · **Code-judo?** YES

The `_evidence` package defines typed dataclasses (`ModelArtifact`,
`ScoreScaling`, `ExclusionSummary`, `SelectionDefinition`, `BinDefinition`,
etc.) with `from_json`/`to_dict`. But the consuming layers routinely bypass
them via `getattr(typed, "_raw", {})` then `.get("coefficients", {})` /
`.get("base_score", 600)` / `.get("rows_before", 0)`.

`_raw` access counts (grep-verified):

- `cardre/nodes/build/scoring_export.py`: **47**
- `cardre/nodes/calibrate.py`: **22**
- `cardre/reporting/collector.py`: **14** (round-trips typed models back through `_raw`)
- `cardre/nodes/build/freeze.py`: 10
- `cardre/services/comparison_service.py`: 8
- `cardre/nodes/build/selection.py`, `prep.py`: 7 each
- 13 more files with 1-6 each

**T1a — four diagnostics kinds have no `EvidenceKind` at all.** `coefficient_sign`,
`separation`, `vif`, `calibration` have schema constants in
`_evidence/schemas.py` but no enum member, no typed model, no adapter. So
`collector.py` hosts a *second*, parallel untyped JSON reader
(`_read_raw_json_by_step`, with `import json` inside a method body) that
competes with the canonical `ArtifactEvidenceReader`. Location:
`cardre/reporting/collector.py:979-991` + 4 callers at 871, 897, 923, 947.

**T1b — `MANUAL_BINNING_OVERRIDES` has no typed model.** Its adapter
(`_evidence/adapters/binning.py:78`) returns the raw dict. This forces
`collector.py:787-795` into `data.to_dict() if hasattr(data, "to_dict") else
getattr(data, "_raw", data)` duck-typing.

**T1c — three parallel "model artifact" representations.**
`modeling/schema.py:ModelArtifactV1` (320 LOC, full typed),
`_evidence/models/model.py:ModelArtifact` (152 LOC, different shape), and the
raw `dict[str, Any]` that `build_model_artifact` actually emits and every
`apply_*` adapter actually consumes. `modeling/adapters.py:6-9` even
documents the boundary violation ("#218"). None of the three round-trips
cleanly.

**Why it matters:** The typed layer is paying its full maintenance cost (40
adapter classes, 10 typed model modules, a reader, a registry) while
delivering zero safety — every consumer duck-types a dict. Adding a model
field requires editing every consumer's `.get()` defaults. A schema change
in `ModelArtifactV1` will not be caught anywhere.

**The code-judo move:** Make the typed classes the *only* access path.

1. Add typed models + `EvidenceKind` members + adapters for the 4 diagnostics
   and `ManualBinningOverrides`.
2. Add typed properties on `ModelArtifact`/`ScoreScaling` for every field
   currently read via `_raw.get(...)`; normalize `base_odds` to float once at
   parse time (delete the 6+ call sites of `parse_base_odds` in consumers).
3. Unify on `ModelArtifactV1` as the single model-artifact type; retire the
   `_evidence/models/model.py:ModelArtifact` and the raw-dict
   `build_model_artifact` path (or accept dicts everywhere and delete both
   dataclasses — but pick one).
4. Remove `_raw` from all node/reporting/service code (keep it internal to
   adapters).

**Impact:** `_read_raw_json_by_step` and its 4 callers collapse to canonical
typed reads. The `hasattr`/`getattr` duck-typing in
`_collect_manual_interventions` disappears. ~150 `_raw` accesses across 20
files become typed attribute access. The `import json` inside a method body
disappears.

### T2 — EvidenceAdapter classes are 90% boilerplate

**Severity:** major · **Category:** code-judo-opportunity · **Location:**
`cardre/_evidence/adapters/`

Every adapter is a two-method class. `match` is byte-for-byte identical in
30+ classes (and already factored into a module-level `_match` helper in 6 of
8 adapter files — `binning.py` inlines the same 8 lines instead of calling
it). `parse` in ~30 of 40 classes is exactly:

```python
def parse(self, path, art, store):
    data = read_json_payload(path)
    return SomeModel.from_json(data, artifact_id=art.artifact_id)
```

The `EvidenceAdapter` Protocol is `@runtime_checkable` but `get_adapter`
dispatches by `EVIDENCE_ADAPTERS[kind]`, never via `isinstance`. The
`kind`/`profile` class attrs are read by nobody.

**Code-judo:** Replace `EVIDENCE_ADAPTERS: dict[EvidenceKind,
type[EvidenceAdapter]]` with `dict[EvidenceKind, AdapterSpec]` where
`AdapterSpec = dataclass(profile=_Profile, parse=Callable)`. Delete all 40
classes; keep the Protocol for the ~3 adapters that do real work in `parse`
(`WoeTable`, `IvTable`, `ScoredDataset`). ~600 LOC → ~120 LOC. The
duplicated `_match` helpers and the registry all disappear.

### T3 — Dead/unreachable evidence-reuse subsystem (~600 LOC)

**Severity:** blocker · **Category:** structural-regression · **Code-judo?**
YES

`ExecutionActionPlanner` ONLY ever emits `action="execute"`. There is no
production path to `"reuse"` or `"skip"`, and `evidence_source` is always
`None`. Confirmed: zero production callers of `EvidenceResolver(`.

Consequently unreachable from production:

- `cardre/execution/executor.py:228-264` — the `if action.action == "reuse":`
  branch (~37 lines)
- `cardre/execution/executor.py:422-498` — `_reuse_run_step` (~77 lines)
- `cardre/execution/run_step_writer.py:178-285` — `write_reused_run_step`
  (~108 lines)
- `cardre/services/evidence_resolver.py` — entire `EvidenceResolver` class +
  `EvidencePolicyService.prepare_branch_evidence`/`resolve_parent_evidence`/
  `check_to_node_current`/`BranchRunEvidence`/`ShortCircuitResult` (~165 LOC;
  only `check_branch_current` is live, for the short-circuit decision)
- `cardre/execution/executor.py:164-165,212-213,219-220` —
  `precomputed_outputs`/`precomputed_records` params threaded through but
  never supplied

**Why it matters:** The `_execute_actions` loop *looks* like it handles
three modes when production only ever hits one. The dead "reuse" branch
duplicates the execute block almost verbatim, so any change to the execute
path risks the dead branch silently drifting. `BranchRunEvidence` has 12
fields, only 4 ever set. `prepare_branch_evidence` probes staleness via
`list(steps)[0]` — one arbitrary step — and reuses that single explanation
for every step.

**Code-judo:** Decide-and-delete. Drop the `"reuse"`/`"skip"` branches and
`evidence_source`/`precomputed_*` from `_StepAction` and `_execute_actions`;
delete `_reuse_run_step`, `write_reused_run_step`, `EvidenceResolver`,
`BranchRunEvidence`, `prepare_branch_evidence`, `resolve_parent_evidence`,
`check_to_node_current`, `ShortCircuitResult`. Keep
`EvidencePolicyService.check_branch_current` only (or fold its one live
method into `StalenessService`). The action enum collapses to a single mode;
`_execute_actions` becomes a flat `for action in actions: execute(action)`.
~600 LOC deleted.

If branch reuse is genuinely imminent, wire it instead — but the current
state (plausible-looking code that can never fire) is the worst option.

### T4 — Boilerplate duplication across nodes (the codebase already knows the dedup pattern but only uses it in 6 of 34 files)

**Severity:** blocker · **Category:** code-judo-opportunity

The same 4 idioms are copy-pasted across 15+ node files:

1. **Target-metadata extraction (15 copies).** The 4-line "read
   `MODELLING_METADATA`, extract `target_column`/`good_values`/`bad_values`
   as str sets" dance, with two drifting idioms
   (`meta.good_values if meta is not None else []` vs `meta.good_values if
   meta else []`). `_training_utils._extract_target_metadata` already
   exists and centralizes this — only `_classifier_base`/`tuning` use it.
   Locations: `analyse.py:194-198,656-659,810-813`;
   `diagnostics.py:444-448`; `feature_selection.py:119-125,369-373,556-558,726-728`;
   `fairness.py:70-76`; `ensembles.py:178-181,383-386`;
   `calibrate.py:309-312`; `reject_inference.py:69-75,373-375`.

2. **"model artifact must be readable as MODEL_ARTIFACT" guard (11 copies,
   6 lines each = ~66 LOC).** Identical try/except/raise, with the node name
   hardcoded in each message — which has already caused a copy-paste bug
   (`fairness.py:322,326` raise "fairness_report requires..." in
   `ProxyRiskReportNode`; `:487` warns "fairness analysis" in
   `AlternativeDataManifestNode`). Locations: `explainability.py:153-162,591-600`;
   `build/models.py:418-427,536-541`; `fairness.py:88-97,318-327`.

3. **`data_arts = [a for a in context.input_artifacts if a.role in
   ("train","test","oot")]` (6+ copies, with variants like
   `("input","train")`).** Locations: `validate/analyse.py:222,661,816`;
   `validate/apply.py:87`; `fairness.py:78`; `build/diagnostics.py:451`.

4. **Selection-definition merge (2 copies, 16 lines each).**
   `feature_selection.py:272-288` (filter) and `457-472` (embedded) —
   near-identical `try/except` over a 3-way `or` fallback, differing only in
   the key name.

**Code-judo:** The codebase *already has* the right patterns:
`_classifier_base.py` (template-method base for 6 classifier nodes),
`_training_utils._extract_target_metadata`/`_prepare_training_data`/
`_write_estimator`, `_bin_mask.py`, `_logit_helpers.py`. The problem is only
~6 of 34 node files use them.

Promote three canonical helpers:

- `context.target_metadata() -> TargetMeta` (or a `NodeContext` wrapper) —
  replaces 15 inline copies.
- `reader.require_model(model_art, node_type)` — replaces 11 six-line guards
  and eliminates the copy-paste-name drift that caused the fairness bug.
- `context.data_artifacts()` + a `ROLES_DATA = ("train","test","oot")`
  constant — replaces 6+ comprehensions.

~400 LOC deleted, and an entire class of drift bug eliminated.

### T5 — God-files and god-functions

**Severity:** major · **Category:** file-size + spaghetti-growth

| File | Lines | Issue |
|---|---|---|
| `cardre/reporting/collector.py` | **1337** | God-class with ~20 near-identical `_collect_*` methods sharing one "resolve → read-or-limitation → map" shape. `collect()` is a 210-line orchestrator of 15 `if ref := ...: self._collect_X(...)` lines. Past 1k with no decompositional seams. |
| `cardre/nodes/prep.py` | **1199** | 9 unrelated nodes (import, profile, validate, split, metadata, exclude, sample, treatment) in one file. Embeds `GERMAN_CREDIT_COLUMNS` — a 22-entry UC Irvine demo-dataset schema — in production code, re-exported from `cardre.nodes.__init__` and registered as a launch-tier node (`cardre.import_fixture_uci_german_credit`). |
| `cardre/nodes/validate/analyse.py` | 909 | `ValidationMetricsNode.run()` is a **280-line god-function** doing 7 unrelated things (metadata read, frozen-bundle detect, sample gates, per-role AUC/Gini/KS/calibration/cutoff loop with inline polars, PSI, gate evaluation, artifact write, raise). |
| `cardre/nodes/build/clustering.py` | 747 | `VariableClusteringNode.run()` is a **230-line god-function** with 4-level nested branching (WOE/raw × method × sufficient/insufficient). Plus an impossible `try/except ImportError` catching numpy-missing (numpy is imported at module top). |
| `cardre/nodes/calibrate.py` | 596 | `run()` is a 300-line numbered 11-step orchestration; step `#5` comment duplicated on lines 402 and 404; in-place mutation of `model["intercept"]`/`model["coefficients"]` (non-atomic). |

**Code-judo moves:**

- **collector.py (with T1):** Extract a `SectionCollector` protocol
  (`canonical_step_id`, `kinds`, `build(bundle, ref, evidence,
  add_limitation)`); register one instance per section; `collect()` becomes a
  loop over the registry. The 15 `if ref:` lines become one loop. Group into
  `reporting/sections/`. File drops under 500 lines. Combine with T1 (typed
  evidence) and T6 (dedup step-resolver) and the file drops under 400.
- **prep.py:** Split into `prep/{import,profile,split,metadata,treatment}.py`;
  move `_numeric_stats` to `_dataset_quality.py`; relocate
  `ImportGermanCreditNode`+`GERMAN_CREDIT_COLUMNS` to `cardre/examples/` or
  `tests/fixtures/`, demote to deferred tier. Each file <300 lines.
- **ValidationMetricsNode.run / VariableClusteringNode.run:** Extract pure
  helpers (`_compute_role_metrics`, `_compute_psi_stability`,
  `_evaluate_gates`; `_resolve_candidates`, `_cluster_columns`). Each
  `run()` becomes ~50-80 lines. Delete the impossible `ImportError` catch.

### T6 — Duplicated step-resolution helpers + `ResolvedStepRef` exists in 3 forms

**Severity:** major · **Category:** modularity · **Code-judo?** YES

Both `collector.py:86-154` and `readiness/check.py:26-94` open with the
comment `# Inlined step resolution helpers (formerly cardre.step_id)` and
reproduce ~70 identical lines (`_ResolvedStepRef`/`ResolvedStepRef`
dataclass + `resolve_step_for_branch` + `resolve_required_steps`). The
"formerly cardre.step_id" comment admits the helpers were extracted to a
module and then re-inlined into two places.

Additionally, `ResolvedStepRef` exists in **three** forms: the collector's
private `_ResolvedStepRef` dataclass, the `reporting/schema.py:19` Pydantic
`ResolvedStepRef`, and the readiness `ResolvedStepRef` dataclass. Every
`_collect_*` uses a `_to_schema_ref(ref)` converter — except `_collect_woe_iv`
(`collector.py:527-533`) which manually reconstructs the Pydantic model
field-for-field, dropping `artifact_ids` silently.

**Dead weight:** `artifact_ids` is declared on both dataclasses but never
assigned anywhere (every constructor omits it).
`LimitationCode.MISSING_RUN_MANIFEST_COLLECTOR` is aliased to the exact same
string as `MISSING_RUN_MANIFEST` — a duplicate `StrEnum` value that breaks
the enum's uniqueness invariant.

**Code-judo:** Restore a single `cardre/branch_step_resolver.py` module
owning `ResolvedStepRef` + the two functions. Delete ~140 lines total, the
`_to_schema_ref` converter, and the manual reconstruction at 527-533. Three
types + a converter collapse to one type used everywhere. Delete
`artifact_ids` and `MISSING_RUN_MANIFEST_COLLECTOR`.

### T7 — `BinDefinition` is an `Any`-typed shadow wrapping `LifecycleBinDefinition`

**Severity:** major · **Category:** boundary-type · **Code-judo?** YES ·
**Location:** `cardre/_evidence/models/binning.py:23-69`

`BinDefinition` carries both `variables: list[BinVariable]` (flat dicts via
`list[dict[str, Any]]`) **and** `_lifecycle: Any` (a
`LifecycleBinDefinition` parsed in `from_json`). Every property (`rejected`,
`warnings`, `source`, `to_dict`) is `if self._lifecycle is not None: return
self._lifecycle.X`. So the typed `BinVariable` list is dead weight whenever
the lifecycle exists (always, in production), and `to_dict` returns the
lifecycle payload, not the BinVariables. The `_lifecycle: Any` field erases
the type of the lifecycle that `definition.py` carefully defined.

Related: `engine/binning/definition.py:431-548` — `validate_overrides`/
`apply_overrides` ignore the typed `LifecycleBin`/`LifecycleVariable`
defined two screens above and operate on `bin_def: JsonDict` with hand-built
merged-bin dict literals. The merged bins (lines 466-478) are missing
`kind`/`woe`/`iv`/`bad_rate`/`row_pct` fields that `LifecycleBin.from_dict`
expects — **the round-trip is lossy**.

And: `engine/binning/definition.py:273-324` — `normalize` is a 40-line
field-by-field copy that `dataclasses.replace(self,
schema_version=SCHEMA_BIN_DEFINITION)` does in one line.

**Code-judo:** Make `BinDefinition` a thin typed alias for
`LifecycleBinDefinition` (or retire it). Rewrite `apply_overrides`/
`validate_overrides` to take/return `LifecycleBinDefinition` and construct
merged bins via `dataclasses.replace`/`LifecycleBin(...)` — fixes the silent
field-drop bug. Replace `normalize` with `dataclasses.replace`. ~40 LOC → 1
for `normalize`; the `Any`-typed shadow disappears.

---

## Cluster-specific findings

### Reporting & Readiness

#### R1 — `readiness/check.py` 8-branch if/elif cascade

**Severity:** major · **Category:** code-judo-opportunity · **Location:**
`cardre/readiness/check.py:206-398`

Eight branches each open with the identical `any(art and
art.metadata.get("schema_version") == <X> for row in store.execute("SELECT
artifact_id FROM artifact_lineage WHERE run_step_id = ? AND direction =
'output'", (rs.run_step_id,)).fetchall() if (art :=
store.get_artifact(row["artifact_id"])))` block, differing only in expected
schema and `LimitationCode`. The exact SQL string appears 8 times in this
file. The `final-woe-iv` branch inlines a 25-line champion-mode monotonicity
check with a bare `except Exception` that swallows all.

**Code-judo:** drive from `_STEP_REQUIREMENTS: dict[str, StepRequirement]`
(expected_schema, expected_role, missing_code, extra_check). The 190 lines
collapse to ~40 table + ~20 loop. Replace the bare `except Exception` with
typed catches.

#### R2 — `readiness/dto.py` hand-rolls DTOs next to Pydantic models

**Severity:** major · **Category:** boundary-type · **Location:**
`cardre/readiness/dto.py:10-104`

`ReadinessBlocker`/`ReadinessWarning` are copy-paste twins (identical
fields, `_normalize`, `__init__`, `to_dict`); `_normalize` silently falls
back to raw string on invalid `LimitationCode` (defeats the enum).
`reporting/schema.py` uses Pydantic for the same job one directory over.

**Code-judo:** collapse to one Pydantic `ReadinessFinding` with `severity:
Literal["blocker","warning"]`; use a validator that rejects bad codes;
delete `to_dict`.

#### R3 — `report_mode: str` everywhere, only `"branch"`/`"champion"` valid

**Severity:** moderate · **Category:** boundary-type · **Location:**
`cardre/reporting/schema.py:610`; `cardre/reporting/collector.py:184,419`;
`cardre/readiness/check.py:119,189,247,318,401,464`; `cardre/readiness/dto.py:65`

A typo like `"champoion"` silently flows through readiness as the `else`
branch and through the collector's single `== "branch"` check. Define
`ReportMode = Literal["branch","champion"]`.

#### R4 — Split ownership of `reproducibility`/`run_status`

**Severity:** moderate · **Category:** spaghetti-growth · **Location:**
`cardre/reporting/collector.py` — `_collect_run_status` (1212-1227) +
`_read_canonical_manifest` (1281-1286); `_read_canonical_manifest` (1281-1282)
+ `_collect_reproducibility` (1152-1163)

`_collect_run_status` creates `bundle.run_status`, then
`_read_canonical_manifest` reaches back in to set
`execution_mode`/`target_step_id`. `_read_canonical_manifest` sets
`reproducibility.manifest_hash`/`pathway_hash`, then
`_collect_reproducibility` destroys-and-rebuilds the entire
`bundle.reproducibility` object, copying the two hashes across. Two methods
own each field; reordering the calls in `collect()` would silently break the
hashes.

**Code-judo:** have `_read_canonical_manifest` return a `ManifestDigest`
consumed by the two owners; the destroy-and-rebuild disappears.

#### R5 — `report_status` never says `"blocked"` even with blocker limitations

**Severity:** minor · **Category:** boundary-type · **Location:**
`cardre/reporting/collector.py:402`

`bundle.summary.report_status = "complete_with_warnings" if self.limitations
else "complete"`. The collector freely appends `severity="blocker"`
limitations. Make it a computed property derived from limitation severities:
`"blocked"` if any blocker, else `"complete_with_warnings"` if any, else
`"complete"`.

#### R6 — `renderer_html.py` hardcodes 13-key `RedundancyReviewInfo` default fallback

**Severity:** minor · **Category:** spaghetti-growth · **Location:**
`cardre/reporting/renderer_html.py:56-65`

Duplicates the schema's defaults; if the schema changes, this disagrees
silently. Pass the `ReportBundle` model (or trust the template guards) and
delete the block.

### Services & Execution

#### SE1 — Stale-run recovery duplicated inline + as a dead method

**Severity:** major · **Category:** spaghetti-growth · **Location:**
`cardre/services/run_coordinator.py:444-462` (live inline) vs `489-511` (dead
`_maybe_recover_stale_run`)

The two copies have already drifted (the dead one wraps in a transaction,
the live one doesn't). The dead method has zero production callers.

**Code-judo:** delete the dead method; extract the live sweep into
`_sweep_stale_running_runs(plan_version_id) -> list[str]`.

#### SE2 — `to_node` half-applies "failed" then raises

**Severity:** major · **Category:** boundary-type · **Location:**
`cardre/services/run_coordinator.py:298-301`; `cardre/execution/executor.py:177-199`
(dead `run_to_node`)

A non-atomic write-then-raise that flips a freshly-created "running" run to
"failed" with no manifest or lifecycle finalisation. The double-gate (once
at `run()`, once at `_execute_existing_running_run`) with inconsistent
handling means a future path bypassing `run()`'s check would silently mark
"failed" with no diagnostic. `executor.run_to_node` is dead in production
(only tests call it).

**Code-judo:** delete the `to_node` branch in the executor; scope validation
is one function called from `run()`.

#### SE3 — Run status is an ad-hoc string state machine checked in 5+ places

**Severity:** major · **Category:** spaghetti-growth · **Location:**
`cardre/services/run_coordinator.py:205-210,376-390`;
`cardre/execution/worker.py:120-133`;
`cardre/execution/run_lifecycle.py:383`

`"running"`/`"failed"`/`"succeeded"`/`"interrupted"`/`"cancelled"` as bare
literals. `finish(...)` called from 4 layers with no single owner — a run
can be flipped to "failed" by a stale-sweep AND a worker failure AND a
lifecycle exception, racing on the same row. Introduce `RunStatus` enum +
single `RunRepository.transition(run_id, to_status, *, expected_from=...)`.

#### SE4 — Coordinator re-derives state the executor already computed

**Severity:** major · **Category:** structural-regression · **Location:**
`cardre/services/run_coordinator.py:308-348`

`run_plan_version` returns only `run_id`, swallowing the executor's
`(has_failure, outputs, records)`; the coordinator re-queries
`RunStepRepository.get_for_run` **twice** (once inside the `with` to compute
`has_failure`, once after to build `executed_ids`). The `execution_mode` dict
(`{"branch"->"branch", "full_plan"->"full_plan"}`) is an identity map with a
fallthrough that silently rewrites unknown scopes to `full_plan` — a cast in
disguise.

**Code-judo:** make `run_plan_version` return a typed
`PlanExecutionResult`; the re-queries and `has_failure` scan disappear;
`_execute_existing_running_run` shrinks to "open lifecycle → execute →
finalise from result → return summary".

#### SE5 — `comparison_service.refresh_comparison` non-atomic per-challenger

**Severity:** major · **Category:** structural-regression · **Location:**
`cardre/services/comparison_service.py:486-542`

Separate transaction per challenger with a stray per-iteration `UPDATE
branch_comparisons SET latest_snapshot_id=...`. If the third challenger
fails, the first two snapshots commit, `latest_snapshot_id` points at the
second, orphan artifacts litter the store, the third is silently lost.

**Code-judo:** wrap the whole refresh in one transaction; one final
`latest_snapshot_id` UPDATE; build contents concurrently if independent.

#### SE6 — `_json_ready` duplicated verbatim

**Severity:** moderate · **Category:** modularity · **Location:**
`cardre/execution/executor.py:45-65` vs `cardre/execution/step_runner.py:41-59`

Two copies of a non-trivial recursive JSON-coercion that feeds
`execution_fingerprint` staleness compares; they've already drifted in
structure. Move to `cardre/execution/fingerprints.py`.

#### SE7 — `branch_id` resolved three times per persisted step

**Severity:** moderate · **Category:** spaghetti-growth · **Location:**
`cardre/execution/executor.py:393-398, 480-484, 535-539`

Three reads of the same column for the same run, with a `X if X else Y`
fallback suggesting `branch_id` kwarg and run-row `branch_id` can disagree.
Resolve once, pass down.

#### SE8 — `dispatcher.py` is a 24-line pure re-export

**Severity:** minor · **Category:** modularity · **Location:**
`cardre/execution/dispatcher.py`

Re-exports `worker.py`. Delete it; add the names to `execution/__init__.py`
if needed.

### Nodes (beyond T4/T5)

#### N1 — `BinningNode` is a thin dispatcher over `FineClassingNode`/`AutoBinningFitNode`

**Severity:** major · **Category:** code-judo-opportunity · **Location:**
`cardre/nodes/build/binning.py:336-360`

Three node types, three parameter schemas for two implementations; the
`replace(context, validated_params=...)` hack signals the sub-nodes shouldn't
be `NodeType` subclasses. The same two implementations live behind
`cardre.binning` (canonical), `cardre.fine_classing`, `cardre.auto_binning_fit`
(legacy aliases).

**Code-judo:** make `FineClassingNode`/`AutoBinningFitNode` plain functions;
one node type, one schema, two method-functions; the `replace(context)` hack
disappears.

#### N2 — `ModelExplainabilityNode` has 4 near-identical compute methods with swallowed `except Exception`

**Severity:** major · **Category:** spaghetti-growth · **Location:**
`cardre/nodes/explainability.py:275-497`

`_compute_permutation_importance`/`_compute_stability_analysis`/
`_compute_pdp`/`_compute_shap` each repeat the 7-line estimator-deserialization
block; every method swallows all exceptions and returns `None` (a corrupt
estimator artifact is indistinguishable from "SHAP not installed").
`_load_estimator` already exists in `ensembles.py:32` — reuse it. Narrow the
`except` to `ImportError`/`FileNotFoundError`/`joblib.InvalidJoblibException`.

#### N3 — `VotingEnsembleNode`/`WeightedEnsembleNode` compute ensemble predictions and discard them

**Severity:** major · **Category:** spaghetti-growth · **Location:**
`cardre/nodes/ensembles.py:218-225, 442, 516-545`

`np.mean(prob_matrix, axis=1)`, `majority.astype(float)`, `prob_matrix @
weights` — all results discarded, no assignment. The ensemble artifact is
metadata-only; the comment at line 547 says `StackingEnsembleNode` "is
deferred". `_optimize_weights` is a 500-iteration random Dirichlet grid
search (non-convex heuristic masquerading as optimization). Either finish
the ensemble or remove from registry.

#### N4 — Magic strings for schema versions and column names scattered

**Severity:** moderate · **Category:** boundary-type · **Location:**
`cardre/nodes/build/models.py:291`; `cardre/nodes/build/features.py:351,373`;
`cardre/nodes/build/freeze.py:114-119`; `cardre/nodes/validate/analyse.py:321`

`build/models.py:291` uses inline `"cardre.model_artifact.v1"` literal while
`SCHEMA_MODEL_ARTIFACT` constant is imported and used 3 lines later.
`build/freeze.py:114-119` re-implements `"N:M"` base-odds parsing inline
instead of calling canonical `parse_base_odds` from `_logit_helpers.py`. Add
a `cardre/columns.py` for canonical output columns
(`PREDICTED_BAD_PROBABILITY`, `SCORE`, etc.).

#### N5 — `_typed_definition_payload` is a generic 4-way reflection escape hatch

**Severity:** minor · **Category:** boundary-type · **Location:**
`cardre/nodes/feature_selection.py:26-39`

Tries `getattr(existing_typed, "_raw")`, then `asdict`, then `to_dict`, then
returns `{}`. Returns `{}` on failure, which downstream mutates
(`existing["selected"] = ...`) — a failed read looks like a successful empty
merge. Define a `TypedEvidence.to_payload() -> dict` protocol; drop the
helper.

### Store, API & Sidecar

#### A1 — `ProjectStore` carries a parallel delegate API

**Severity:** major · **Category:** code-judo-opportunity · **Location:**
`cardre/store/db.py:272-334` (~60 lines)

14 convenience methods each doing `from cardre.store.X_repo import
XRepository; return XRepository(self).<method>(...)`. A literal second API on
top of the repository classes; the lazy imports hide a circular-import
workaround. Some routes use `ProjectStore.get_run`, others use
`RunRepository(store).get(...)` with no rule.

**Code-judo:** delete the entire delegate block; `ProjectStore` becomes
connection + transaction + raw execute.

#### A2 — Repository pattern is ~30% boilerplate

**Severity:** major · **Category:** code-judo-opportunity · **Location:**
`cardre/store/{plan_repo,branch_repo,run_repo,artifact_repo,comparison_repo,evidence_repo,run_step_repo,step_repo,project_repo,manual_binning_repo}.py`

8+ copies of `return None if row is None else dict(row)`; the `branch_id IS
NULL` vs `branch_id = ?` conditional-SQL pattern repeated 5 times across two
files; `BranchRepository.get_comparison` (172-177) is byte-for-byte identical
to `ComparisonRepository.get_comparison` (43-47).

**Code-judo:** tiny `Repository` base (`table`, `pk`, `get`, `list`,
`_row_to_obj` hook) + `_branch_filter(branch_id)` helper + move champion
accessors out of `BranchRepository` into `ChampionRepository`. ~300-400 LOC
removed.

#### A3 — API routes do business logic that belongs in services

**Severity:** major · **Category:** spaghetti-growth · **Location:**
`cardre/api/routes/runs.py:33-54,111-145`; `cardre/api/routes/exports.py:14-41`;
`cardre/api/routes/reports.py:16-62`; `cardre/api/routes/node_types.py:16-46`;
`cardre/api/routes/projects.py:38-88`

`list_runs` builds `RunSummary` dataclasses inline; `list_run_evidence` runs
the entire edge-artifact join in the handler; `exports.py` and `reports.py`
walk the filesystem parsing `export-<run_id>`/`manifest-<run_id>` dir names,
bypassing the existing `ExportService`/`ReportService` and reaching into
`store.root`; `node_types.py:33-46` hardcodes a 7-entry fallback node catalog
(with a dead `_` tuple element). Move all to services; routes become thin.

#### A4 — `errors.py` doubles itself

**Severity:** moderate · **Category:** code-judo-opportunity · **Location:**
`cardre/api/errors.py:29-101`

`ErrorCode(StrEnum)` with 34 codes, then 35 module-level constants shadowing
each one. Adding a code requires editing both. Delete one or the other (~35
LOC).

#### A5 — Repo return types inconsistently dict-or-object

**Severity:** minor · **Category:** boundary-type · **Location:**
`cardre/store/db.py:272-334`; `cardre/api/routes/_run_mappings.py:32-35`

`get_run` returns dict, `get_run_steps` returns `list[RunStep]`,
`get_artifact` returns `ArtifactRef | None`. The `_value(obj, key, default)`
polymorphic helper in `_run_mappings.py` exists purely to paper over this.
Pick one (typed objects preferred) — the `_value` helper and the `Mapping |
obj` parameter types collapse to direct attribute access.

#### A6 — `_run_mappings.py` only half-used

**Severity:** minor · **Category:** modularity · **Location:**
`cardre/api/routes/champion.py:41-49`; `cardre/api/routes/artifacts.py:31-39`;
`cardre/api/routes/manual_binning.py:35-47`

Champion, artifact, manual-binning-review all inline their mapping with
`.get(field, default)` ladders. Move all to the mapping module; defaults
stop drifting.

#### A7 — `active_step_id` smuggled through `runs.metadata_json`

**Severity:** moderate · **Category:** spaghetti-growth · **Location:**
`cardre/store/run_repo.py:86-105`

An operational field queried by `RunCoordinator` is stored as JSON, accessed
via `json.loads`/`json.dumps`, can't be indexed/filtered. Add a column; bump
schema version.

#### A8 — `create_project` route hardcodes `cardre_version="0.2.0"`

**Severity:** minor · **Category:** spaghetti-growth · **Location:**
`cardre/api/routes/projects.py:145`

While `_run_mappings.py` imports `__version__` and `project_to_response`
falls back to it. A version bump leaves this route reporting the old
version. Drop the arg.

#### A9 — `sidecar/__main__.py` re-parses `sys.argv` for port

**Severity:** minor · **Category:** legibility · **Location:**
`sidecar/__main__.py:13-27`

Duplicates `CardreConfig.api_port`; the `argv` param is never used by any
caller. Collapse 14 lines to 4.

### Domain Kernel & Engine

#### K1 — `EvidenceLocator` + `EvidenceResolver` overlap and should merge

**Severity:** moderate · **Category:** modularity · **Location:**
`cardre/evidence_locator.py:206-212` vs `cardre/services/evidence_resolver.py:230-235`

Identical `_plan_id_for_version` methods in both; the resolver's 4 policies
are mostly identity-forwarding (2 of 4 just call the locator). With T3
deleting the dead resolver surface, fold the one live diagnostic emission
into the locator. Two classes, two files, two duplicated methods → one.

#### K2 — `artifacts.py` triplicates the register-and-dedup dance

**Severity:** moderate · **Category:** spaghetti-growth · **Location:**
`cardre/artifacts.py:27-67,70-109,112-151`; `cardre/modeling/serialization.py:23-72`

`write_json_artifact`/`write_parquet_artifact`/`write_csv_artifact` share
~90% of their body; `write_estimator_artifact` does it a fourth time
*without* temp-file atomicity and *without* dedup-return. The csv function
swallows temp-cleanup in `try/except BaseException` while json does not.
Extract `_register_bytes_artifact(store, *, bytes_writer, logical_hash,
stem, media_type, directory, metadata)`; reconcile `write_estimator_artifact`
to gain atomicity+dedup.

#### K3 — `JsonDict`/`list[Any]` on domain aggregates

**Severity:** minor · **Category:** boundary-type · **Location:**
`cardre/domain/run.py:115-121`; `cardre/_evidence/models/binning.py:16`

`RunStepEvidenceView` types `input_artifacts`/`output_artifacts`/
`evidence_edges` as `list[Any]` while `ArtifactRef`/`EvidenceEdge` are
defined in the same package. `execution_fingerprint` shape is a de-facto
protocol enforced only by string-key reads. Introduce `ExecutionFingerprint`
record; type the three lists. Cheapest type win in the codebase.

#### K4 — `EvidenceKind` has 2 silent alias pairs

**Severity:** minor · **Category:** modularity · **Location:**
`cardre/_evidence/kinds.py:10-52`

`WOE_APPLICATION_EVIDENCE`/`APPLY_WOE_EVIDENCE` (both `"apply_woe_evidence"`),
`SCORE_APPLICATION_EVIDENCE`/`APPLY_MODEL_EVIDENCE` (both
`"apply_model_evidence"`). Python's `Enum` makes the second an alias to the
first; `EVIDENCE_PROFILES`/`EVIDENCE_ADAPTERS` register all four, two
silently no-op. Delete the alias members or document them.

#### K5 — Stale "Phase 2" migration docstrings

**Severity:** minor · **Category:** legibility · **Location:**
`cardre/_evidence/adapters/_base.py:9-13`

Reference a `_legacy_match` method that no longer exists on the reader;
describe a completed migration as future work. Rewrite.

### Frontend & Tauri

#### F1 — `firstQueryError` parallel-array index dance

**Severity:** major · **Category:** code-judo-opportunity · **Location:**
`frontend/src/components/ProjectView.tsx:20-39, 162-170`

`QUERY_SOURCES` 7-tuple must stay positionally aligned with 7 queries; even
has a defensive `QUERY_SOURCES[i] ?? \`query_${i}\`` fallback admitting the
contract isn't enforced.

**Code-judo:** derive the source label from the query's own `queryKey[0]`;
delete `QUERY_SOURCES`, `firstQueryError`, and the fallback in one move.

#### F2 — `ApiError.code` is loose `string`, not a union of `ErrorCodes`

**Severity:** major · **Category:** boundary-type · **Location:**
`frontend/src/api/client.ts:20-41`

The JSON-parse path invents `"HTTP_ERROR"` (not in `errorCodes.ts`).
`useRunWatch`'s `switch (err.code)` gets no exhaustiveness checking. Type
`code` as `ErrorCodes[keyof ErrorCodes]`; validate at parse time.

#### F3 — `useRunWatch` has three separate prose switches for one concept

**Severity:** major · **Category:** spaghetti-growth · **Location:**
`frontend/src/hooks/useRunWatch.ts:181-216` (catch) vs `94-128`
(`deriveMessage`)

The catch block hardcodes the same strings `deriveMessage` owns, bypassing
it; the public `error` field and `message` field can disagree.

**Code-judo:** one `Record<ErrorCodes, RunWatchStatus>` lookup sets only
`status`; `deriveMessage` owns all prose; ~30 lines collapse.

#### F4 — Error-to-string ternary copied verbatim in 4 places

**Severity:** major · **Category:** modularity · **Location:**
`frontend/src/components/ProjectView.tsx:126,150`;
`frontend/src/components/WelcomeScreen.tsx:38`;
`frontend/src/hooks/useManualBinningReview.ts:51-59`

`err instanceof ApiError ? err.detail : err instanceof Error ? err.message :
String(err)`. Add `toErrorMessage(err: unknown): string` to `client.ts`;
replace all four.

#### F5 — Shadow interface types bypass the generated schema

**Severity:** moderate · **Category:** boundary-type · **Location:**
`frontend/src/components/RunDetailsPanel.tsx:3-25`;
`frontend/src/components/PlanSidebar.tsx:3-11`;
`frontend/src/components/VersionPanel.tsx:3-19`

Hand-define subsets of `components["schemas"]["RunResponse"]` etc.;
`Run.latest_error` typed `Record<string,unknown> | null` then accessed
`.message`/`.code` on `unknown`. Import `Pick<RunResponse, ...>` from the
generated schema; delete ~30 lines of shadow declarations.

#### F6 — `RunWatchStatus` has 13 cases; `stuck` is unreachable, `deriveStatus`'s `default` is unreachable noise

**Severity:** moderate · **Category:** spaghetti-growth · **Location:**
`frontend/src/hooks/useRunWatch.ts:25-38, 72-92, 94-128`

Nothing sets `stuck`; `deriveStatus`'s default `return "running"` is dead
because `RunResponse.status` is a schema enum with every member cased.
Either implement `stuck` or delete it; tighten `deriveStatus` to switch on
the schema enum for exhaustiveness.

#### F7 — `useRunWatch` does too much; `useManualBinningReview` bypasses react-query

**Severity:** moderate · **Category:** modularity · **Location:**
`frontend/src/hooks/useRunWatch.ts` (262 lines);
`frontend/src/hooks/useManualBinningReview.ts:11, 68-95, 107-118`

`useRunWatch` owns polling + state + status derivation + retry policy +
terminal-callback dedup (`completedRunIdsRef` works around polling not
stopping synchronously). `useManualBinningReview` is the only consumer
importing `fetchJson` directly (bypasses `api` + react-query) and hand-rolls
`baseUrl` (a second source of truth vs `window.__API_URL__`).

**Code-judo:** adopt react-query's `refetchInterval` for run polling
(deletes interval ref, teardown, `polling` state, `completedRunIdsRef`);
move the 3 manual-binning endpoints into `api`; convert the hook to thin
`useQuery`/`useMutation` wrappers.

#### F8 — `styles.ts` ~30% dead

**Severity:** minor · **Category:** legibility · **Location:**
`frontend/src/styles.ts:7, 16-18, 24, 34-38`

`surfaceMuted`, `blueBg`, `blueText`, `greenBg`, `fontMono`, `panelStyle`
unreferenced. Delete.

#### F9 — `App.tsx` back-button asymmetric state

**Severity:** minor · **Category:** spaghetti-growth · **Location:**
`frontend/src/App.tsx:20-30`

`onBack` clears `projectId` but not `projectPath`; works only because
`WelcomeScreen` re-reads localStorage.

**Code-judo:** model project as one `useState<{id, path} | null>`; the
set-together/clear-together invariant becomes unbreakable.

#### F10 — `main.rs` `wait_for_health` has no per-request timeout

**Severity:** minor · **Category:** spaghetti-growth · **Location:**
`frontend/src-tauri/src/main.rs:34-58, 122-225`

`reqwest::blocking::get` with no timeout — a hung sidecar that accepts TCP
but never responds blocks indefinitely, consuming all 15s in one call.
`find_free_port` has a documented TOCTOU race. Add
`Client::builder().timeout(Duration::from_secs(2))`. The unused
`running`/ctrl-c `AtomicBool` is dead code (set but never read) — delete or
wire to graceful shutdown.

---

## Approval verdict

**Do not approve.** Per the thermo-nuclear skill's approval bar, five
presumptive blockers are present:

1. **T1** — typed-evidence layer half-used; `_raw` dict access pervades 20
   files; 4 diagnostics kinds + `MANUAL_BINNING_OVERRIDES` have no typed
   model; 3 parallel model-artifact representations. Plausible code-judo
   move exists (make typed classes the only access path) that would delete
   the `_read_raw_json_by_step` parallel reader, the `hasattr`/`getattr`
   duck-typing, and ~150 `_raw` accesses.
2. **T3** — ~600 LOC of dead/unreachable evidence-reuse subsystem
   (`EvidenceResolver`, reuse action branches, `write_reused_run_step`,
   `BranchRunEvidence`). Misleads readers; the dead branch duplicates the
   live one and will drift.
3. **T4** — boilerplate duplication across 15+ node files (target-metadata
   15×, model-readable guard 11×, role-filter 6×); the dedup pattern
   already exists in `_classifier_base`/`_training_utils` but is applied to
   only 6 of 34 files. Has already caused a copy-paste bug (`fairness.py`
   raises "fairness_report requires..." in `ProxyRiskReportNode`).
4. **T5 / collector.py** — file at 1337 lines (past 1k) with no
   decompositional seams; god-class with ~20 near-identical methods and a
   210-line orchestrator. Clear decomposition available (section-collector
   registry + T1 typed evidence + T6 dedup step-resolver → under 400 lines).
5. **T5 / prep.py** — file at 1199 lines (past 1k) mixing 9 unrelated nodes
   + a UC Irvine demo-dataset schema (`GERMAN_CREDIT_COLUMNS`) embedded in
   production launch-tier code and re-exported as public API.

The codebase is not broken — it's well-structured at the macro level (clean
layering, parameterized queries, generated OpenAPI types, a real
`_classifier_base` template-method pattern, pure helpers in
`execution/fingerprints`/`topology`/`step_graph`, a sound `RunLifecycle`
context manager). But the typed-evidence layer is the load-bearing
abstraction for the whole engine, and it's only ~50% used. Fixing T1
unlocks T2 (adapter collapse), unblocks the collector decomposition (T5),
and removes the `_raw` escapes from 20 node files. That single threaded fix
is the highest-leverage move.

---

## Findings index

| ID | Severity | Category | Location | Sprint PR |
|---|---|---|---|---|
| T1 | blocker | structural-regression | 20 files (see above) | PR2, PR3a, PR3b, PR3c |
| T2 | major | code-judo-opportunity | `cardre/_evidence/adapters/` | PR2 |
| T3 | blocker | structural-regression | `services/evidence_resolver.py`, `execution/executor.py`, `execution/run_step_writer.py` | PR4 |
| T4 | blocker | code-judo-opportunity | 15+ node files | PR6 |
| T5 | major | file-size + spaghetti-growth | `reporting/collector.py`, `nodes/prep.py`, `nodes/validate/analyse.py`, `nodes/build/clustering.py`, `nodes/calibrate.py` | PR5, PR6 |
| T6 | major | modularity | `reporting/collector.py`, `readiness/check.py` | PR1 |
| T7 | major | boundary-type | `_evidence/models/binning.py`, `engine/binning/definition.py` | PR2, PR7 |
| R1 | major | code-judo-opportunity | `readiness/check.py:206-398` | PR5 |
| R2 | major | boundary-type | `readiness/dto.py` | PR5 |
| R3 | moderate | boundary-type | `reporting/schema.py:610` + 7 | PR5 |
| R4 | moderate | spaghetti-growth | `reporting/collector.py` | PR3c |
| R5 | minor | boundary-type | `reporting/collector.py:402` | PR5 |
| R6 | minor | spaghetti-growth | `reporting/renderer_html.py:56-65` | PR5 |
| SE1 | major | spaghetti-growth | `services/run_coordinator.py` | PR8 |
| SE2 | major | boundary-type | `services/run_coordinator.py`, `execution/executor.py` | PR8 |
| SE3 | major | spaghetti-growth | 5 files (see above) | PR8 |
| SE4 | major | structural-regression | `services/run_coordinator.py:308-348` | PR8 |
| SE5 | major | structural-regression | `services/comparison_service.py:486-542` | PR8 |
| SE6 | moderate | modularity | `execution/executor.py`, `execution/step_runner.py` | PR1 |
| SE7 | moderate | spaghetti-growth | `execution/executor.py` | PR8 |
| SE8 | minor | modularity | `execution/dispatcher.py` | PR1 |
| N1 | major | code-judo-opportunity | `nodes/build/binning.py` | PR6 |
| N2 | major | spaghetti-growth | `nodes/explainability.py:275-497` | PR6 |
| N3 | major | spaghetti-growth | `nodes/ensembles.py` | PR6 |
| N4 | moderate | boundary-type | `nodes/build/models.py`, `features.py`, `freeze.py`, `analyse.py` | PR6 |
| N5 | minor | boundary-type | `nodes/feature_selection.py:26-39` | PR6 |
| A1 | major | code-judo-opportunity | `store/db.py:272-334` | PR9 |
| A2 | major | code-judo-opportunity | 10 repo files | PR9 |
| A3 | major | spaghetti-growth | 5 route files | PR9 |
| A4 | moderate | code-judo-opportunity | `api/errors.py:29-101` | PR9 |
| A5 | minor | boundary-type | `store/db.py`, `_run_mappings.py` | PR9 |
| A6 | minor | modularity | 3 route files | PR9 |
| A7 | moderate | spaghetti-growth | `store/run_repo.py:86-105` | PR9 |
| A8 | minor | spaghetti-growth | `api/routes/projects.py:145` | PR9 |
| A9 | minor | legibility | `sidecar/__main__.py` | PR9 |
| K1 | moderate | modularity | `evidence_locator.py`, `services/evidence_resolver.py` | PR4 |
| K2 | moderate | spaghetti-growth | `artifacts.py`, `modeling/serialization.py` | PR2 |
| K3 | minor | boundary-type | `domain/run.py`, `_evidence/models/binning.py` | PR1 |
| K4 | minor | modularity | `_evidence/kinds.py` | PR1 |
| K5 | minor | legibility | `_evidence/adapters/_base.py` | PR1 |
| F1 | major | code-judo-opportunity | `ProjectView.tsx:20-39` | PR10 |
| F2 | major | boundary-type | `api/client.ts:20-41` | PR10 |
| F3 | major | spaghetti-growth | `useRunWatch.ts:181-216` | PR10 |
| F4 | major | modularity | 4 files | PR10 |
| F5 | moderate | boundary-type | 3 component files | PR10 |
| F6 | moderate | spaghetti-growth | `useRunWatch.ts:25-38` | PR10 |
| F7 | moderate | modularity | `useRunWatch.ts`, `useManualBinningReview.ts` | PR10 |
| F8 | minor | legibility | `styles.ts` | PR10 |
| F9 | minor | spaghetti-growth | `App.tsx:20-30` | PR10 |
| F10 | minor | spaghetti-growth | `main.rs` | PR10 |

The sprint plan resolving every finding lives at
[`docs/plans/thermo-nuclear-quality-sprint/README.md`](../plans/thermo-nuclear-quality-sprint/README.md).

## Resolution

All findings resolved as of 2026-07-14. See
[`docs/plans/thermo-nuclear-quality-sprint/decision-log.md`](../plans/thermo-nuclear-quality-sprint/decision-log.md)
for structural decisions and deferred follow-ups.

| Finding | PR(s) | Resolution |
|---|---|---|
| T1 | PR2, PR3 | Typed evidence layer completed: 4 diagnostics kinds added, `MANUAL_BINNING_OVERRIDES` typed model, `_raw` access removed from all node/reporting/comparison code. |
| T2 | PR2 | 40 adapter classes collapsed to `AdapterSpec` table. |
| T3 | PR4 | Dead evidence-reuse subsystem deleted (~600 LOC). ADRs updated. |
| T4 | PR6 | Canonical node helpers promoted (`target_metadata`, `require_model`, `data_artifacts`, `train_artifact`, `read_dataframe`). 89+ boilerplate sites replaced. Fairness copy-paste bug fixed. |
| T5 | PR5, PR6 | `collector.py` 1337→240 lines via section registry. `prep.py` split into 5 files. `ValidationMetricsNode.run` <100 lines. `VariableClusteringNode.run` <80 lines. German-credit fixture deleted. |
| T6 | PR1 | Shared `branch_step_resolver.py` module restored. `_json_ready` centralized. `dispatcher.py` deleted. |
| T7 | PR2, PR7 | Binning override seam hardened with current-schema fixtures and lossless round-trip tests. `BinDefinition._lifecycle` forwarders removed. |
| R1 | PR5 | 8-branch if/elif cascade replaced with `_STEP_REQUIREMENTS` table. |
| R2 | PR5 | `ReadinessFinding` Pydantic model with `severity`/`code` fields. |
| R3 | PR5 | `ReportMode = Literal["branch","champion"]` defined. |
| R4 | PR3c | `ManifestDigest` returned from `_read_canonical_manifest`, consumed by two owners. |
| R5 | PR5 | `report_status` computed from limitation severities. |
| R6 | PR5 | Hardcoded default fallback deleted from `renderer_html.py`. |
| SE1 | PR8 | Dead `_maybe_recover_stale_run` deleted; live sweep extracted to `_sweep_stale_running_runs`. |
| SE2 | PR8 | `to_node` branch in executor deleted; coordinator retains a `to_node` guard that transitions to FAILED and raises `RunScopeNotAvailableForLaunch`. |
| SE3 | PR8 | `RunStatus` enum + `_VALID_TRANSITIONS` table + atomic `transition()` writer. |
| SE4 | PR8 | `PlanExecutionResult` returned from executor; coordinator no longer re-queries. |
| SE5 | PR8 | Comparison refresh wrapped in one outer transaction with one final `latest_snapshot_id` UPDATE. |
| SE6 | PR1 | `_json_ready` centralized in `execution/fingerprints.py`. |
| SE7 | PR8 | `branch_id` resolved once, passed down. |
| SE8 | PR1 | `dispatcher.py` deleted. |
| N1 | PR6, PR318 | `BinningNode` dispatcher collapsed — delegates to `_run_fine_classing`/`_run_optbinning` module-level functions. `FineClassingNode` and `AutoBinningFitNode` removed from registry. |
| N2 | PR6 | Estimator-load dedup via `_load_estimator`; `except Exception` narrowed to typed catches. |
| N3 | PR6 | Ensemble dead code removed from registry. |
| N4 | PR6 | Magic strings replaced with constants; `parse_base_odds` used consistently. |
| N5 | PR6, PR11 | Local helper retained in `feature_selection.py`; `_raw` fallback removed in PR11. `to_payload()` protocol not added. |
| A1 | PR9 | `ProjectStore` delegate API deleted (16 methods). |
| A2 | PR9 | Repository boilerplate reduced; `ChampionRepository` extracted; `get_comparison` deduped. |
| A3 | PR9 | Scoped: `list_run_evidence` → `EvidenceRepository`, exports listing → `export_listing.py`, `list_runs` → `RunCoordinator.list_for_project`. |
| A4 | PR9 | `errors.py` deduped — 35 shadowing constants deleted. |
| A5 | PR9 | Scoped: `_value` polymorphic helper deleted. Full typed hydration deferred. |
| A6 | PR9 | Centralised response mappers for champion, artifact, manual-binning. |
| A7 | PR9 | `active_step_id` column + schema migration 100→101. |
| A8 | PR9 | `create_project` no longer hardcodes `cardre_version`. |
| A9 | PR9 | Sidecar argv cleanup — uses `CARDRE_API_PORT` env var. |
| K1 | PR4 | `EvidenceLocator` + `EvidenceResolver` overlap resolved by deleting the resolver. |
| K2 | PR2 | `_register_bytes_artifact` extracted; `write_estimator_artifact` gains atomicity+dedup. |
| K3 | PR1 | `list[Any]` on domain aggregates typed. |
| K4 | PR1 | Silent alias pairs documented. |
| K5 | PR1 | Stale docstrings rewritten. |
| F1 | PR10 | Positional `QUERY_SOURCES`/`firstQueryError` removed. |
| F2 | PR10 | `ApiError.code` typed as `ErrorCode` union; validated at parse time. |
| F3 | PR10 | Dead `useRunWatch` hook deleted (never wired into any component). |
| F4 | PR10 | Shared `toErrorMessage` helper added; 4 inline ternaries replaced. |
| F5 | PR10 | Shadow component interfaces replaced with generated schema types. |
| F6 | PR10 | Dead `stuck` status deleted; `deriveStatus` tightened. |
| F7 | PR10 | Dead `useRunWatch`/`useManualBinningReview` hooks deleted. |
| F8 | PR10 | Dead styles deleted from `styles.ts`. |
| F9 | PR10 | Project state made symmetric (single `{id, path} | null`). |
| F10 | PR10 | Tauri health-check timeout added; dead `AtomicBool` removed. |