# Plan Review 010: Final Round Engine Spec Corrections Review

This is very close to a proper v0 product/architecture spec. I’d stop iterating the concept after this and move into implementation specs.

My verdict: green light, with a few important corrections before you freeze it.

---

## The plan is now strong

The biggest improvements are excellent:

- Node type vs step distinction is now clear.
- Two-stream build/validate pathway is a strong way to make leakage prevention visible.
- SQLite metadata + Parquet/JSON artifacts is the right storage split.
- Physical hash vs logical hash is a mature reproducibility model.
- Phase 1A / 1B split fixes the earlier risk of building the app shell before proving the engine.
- Manual binning as core v0 functionality is the right decision for scorecard credibility.
- Apache 2.0 is a sensible open-source choice for regulated/corporate adoption.
- Non-goals are clear and protect the MVP.

The plan now has a coherent product claim:

> Cardre is not trying to beat Python libraries at WOE/logistic regression. It is trying to make the scorecard development journey reproducible, visible, editable, and auditable.

That is a real wedge.

---

## Corrections I would make before freezing it

### 1. Remove stored_status from plan steps

This bit is still slightly wrong:

```text
stored_status: not_run, queued, running, succeeded, failed, cancelled
```

A plan step should not really store execution status. Execution status belongs to run_steps.

Better model:

```text
plan_steps:
  step_id
  node_type
  params
  params_hash
  parent_step_ids

run_steps:
  run_step_id
  run_id
  step_id
  plan_version_id
  status
  started_at
  finished_at
  input_artifact_ids
  output_artifact_ids
  warnings
  errors
```

Then the API computes the display state:

```text
display_status = latest relevant run_step status
is_stale = latest successful run_step does not match current plan/upstream/code/artifacts
```

Otherwise you risk mixing “current design” with “historical execution evidence”.

### 2. Staleness needs more than upstream hash comparison

You currently say:

> staleness computation (`is_stale` from upstream hash comparison)

That is too narrow. A step should become stale if any of these change:

- step params_hash
- parent step output logical_hash
- node_type version
- relevant dependency/runtime version, at least for governance runs
- input artifact logical_hash
- plan version lineage

So I’d change that phrase to:

> staleness computation from the execution fingerprint: step params, parent output logical hashes, node implementation version, and relevant runtime/dependency metadata.

That concept — execution fingerprint — is worth adding explicitly.

### 3. The WOE pathway needs a final post-manual WOE/IV calculation

Current flow:

```text
Automatic Fine Classing
-> Calculate WOE/IV
-> Variable Selection
-> Manual Bin Editing
-> WOE Transform
```

That is nearly right, but you probably need to distinguish:

- Initial WOE/IV diagnostics using automatic bins
- Manual coarse classing for candidate variables
- Final WOE/IV calculation using refined bins
- WOE transform using final refined mapping

Otherwise the IV/ranking evidence in the audit report may refer to pre-manual bins, while the model uses post-manual bins.

I’d revise the build stream to:

```text
Automatic Fine Classing
-> Initial WOE/IV Diagnostics
-> Candidate Variable Selection
-> Manual Bin Editing / Coarse Classing
-> Final WOE/IV Calculation
-> WOE Transform Train
-> Logistic Regression
-> Score Scaling
```

### 4. The validate stream should include scored train as well

The plan says validation metrics are reported separately for train, test, and OOT, but the validate stream only mentions test/OOT.

You need train metrics too, not because train is validation, but because governance reviewers expect to compare:

- train performance
- test performance
- OOT performance

So the final structure should be:

```text
BUILD STREAM:
  fit bins/model/scorecard on train

SCORING/EVALUATION STREAM:
  score train using fitted artifacts
  score test using fitted artifacts
  score OOT using fitted artifacts
  calculate metrics by role
```

This makes it clear that train is scored for comparison, while fitting still only happens on train.

### 5. Be careful with “sort columns by name” in logical hashing

For canonical tabular hashes, this line is slightly risky:

> sort columns by name

That is okay for datasets where column order is not semantically meaningful. But for modelling matrices, exported coefficient vectors, and scorecard point arrays, column order can matter.

Safer wording:

> Canonical hashes should use deterministic column ordering. For unordered tabular datasets this may be sorted by name; for model matrices and artifacts where order is semantically meaningful, the artifact schema must declare the canonical order.

That avoids accidentally treating two different design matrices as equivalent.

### 6. Add explicit unknown/out-of-range scoring behaviour

This is the biggest missing modelling detail.

You need a section saying every binning artifact must define behaviour for:

- unseen categorical levels
- numeric values outside training ranges
- missing values where no missing bin existed in train
- undeclared special codes
- malformed values at scoring time

This matters hugely for SQL export, Python scoring export, and implementation parity.

Suggested addition:

> Every bin map must include explicit fallback rules for unknown categories, out-of-range numeric values, missing values, and undeclared special codes. Fallback use must be counted and reported during validation/scoring.

### 7. Add WOE zero-cell policy as a decision, not just a warning

You mention zero-cell warnings, but v0 needs an actual behaviour.

For example:

Default governance behaviour:

- zero-good or zero-bad bins block final WOE mapping unless the user merges bins or explicitly enables smoothing.
- smoothing method and parameter are recorded in the audit trail.
- affected bins are listed in the model development report.

Warnings alone are not enough; otherwise users can produce unstable WOE mappings and still export a “governance” pack.

### 8. Add a sensitive audit export rule

Security section is good, but add this:

> Audit exports should not include raw row-level customer data by default.

Audit packs can accidentally become data exfiltration bundles. The default pack should include metadata, summaries, metrics, definitions, model artifacts, and reports — not the full raw/transformed portfolio unless explicitly selected.

### 9. Fix the mojibake characters

There are several encoding artefacts:

```text
â€”
â”€â”€
â†’
```

These are just broken em dashes / arrows / line characters. Fix before publishing the plan, because they make the document look less polished.

---

## My suggested final wording changes

I’d add these short sections.

### Execution fingerprint

```md
### Execution Fingerprint
Each successful step execution records an execution fingerprint containing:
- plan version ID
- step ID
- node type and implementation version
- step params hash
- parent run step IDs
- input artifact logical hashes
- relevant runtime/dependency metadata
- output artifact logical hashes
A step is current only if its latest successful execution fingerprint matches the current plan, current parent outputs, and current implementation version. Otherwise it is stale.
```

### Scoring fallback rules

```md
### Scoring Fallback Rules
Every binning artifact must define explicit handling for:
- unseen categorical levels
- numeric values outside training ranges
- missing values
- undeclared special codes
- malformed scoring-time values
Fallback usage must be counted during validation and included in the audit report. Governance exports should flag high fallback usage as a model implementation risk.
```

### Zero-cell WOE policy

```md
### Zero-Cell WOE Policy
Bins with zero goods or zero bads must not silently produce infinite WOE values. The default behaviour is to block final WOE mapping until the bins are merged or a smoothing policy is explicitly enabled. If smoothing is enabled, the smoothing method, parameter, affected bins, and user rationale are recorded in the audit trail.
```

### Audit data minimisation

```md
### Audit Export Data Minimisation
Audit packs should not include raw row-level customer data by default. The default export should contain manifests, summaries, metrics, bin definitions, model parameters, scorecard specifications, validation evidence, and reports. Row-level datasets may be exported only by explicit user action.
```

---

## One strategic point

The plan says:

> Cardre is a desktop app from day one.

That is fine as a product promise, but your phase plan correctly starts with engine/storage proof. I’d phrase it as:

> Cardre’s product form is a desktop app from day one, but implementation begins with the local engine, storage model, and reproducibility contract before the GUI is built.

That avoids contradiction.

---

## Final verdict

This is now a credible implementation plan.

I would not keep expanding it. The only changes I’d make are the corrections above, then move immediately to one of these next artefacts:

1. SQLite schema + artifact model
2. Node type / step / run_step interface spec
3. Execution fingerprint and staleness algorithm
4. Manual binning v0 UX spec
5. Scorecard correctness test suite

The next best document is definitely:

**Cardre v0 Engine Specification:**

- SQLite schema
- artifact layout
- node contract
- execution fingerprint
- staleness rules
- dummy DAG example

Once that exists, you can start building without the architecture drifting.
