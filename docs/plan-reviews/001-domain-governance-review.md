# Plan Review 001: Domain And Governance Review

Right, this is a meaty spec — and a genuinely interesting idea from a credit risk angle. Here’s a structured critique.

## What’s Strong

The core concept is well-suited to the domain. The node-based DAG model, immutable input snapshots, and branching comparison are exactly what’s needed for model risk governance. The audit-first design would survive most MRM scrutiny.

The phased plan is realistic. Phases 1–3 are entirely backend and testable without a GUI, which is the right call. Phase 4 deferring Streamlit is sensible.

The node contract is solid. Typed inputs/outputs, versioned implementations, JSON-serialisable properties, and deterministic execution are the right primitives for reproducibility.

## Gaps and Weaknesses

### 1. No Train/Test Discipline in the Core Pathway

The workflow shows a linear clean_data -> fine_classing -> WOE -> model pathway, but there’s no early emphasis on preventing data leakage. WOE is calculated on the full dataset in several described flows, when it should be fit on train only and applied to test. This is a correctness issue, not just a UX one — the node model needs to enforce or at minimum flag this, since it’s the most common scorecard validity error.

### 2. Reject Inference is Buried

It’s mentioned once as “later” in the modelling nodes. For a tool aimed at credit-risk modellers, reject inference is a first-class concern — arguably more important than regularised logistic regression. It affects every scored population. It should be a named phase or at minimum a named open question.

### 3. No Multi-User or Approval Workflow Design

The governance section mentions “approvals” and “approval checklist” but there’s no design for it. In practice, model risk governance requires a 4-eyes sign-off pattern: modeller builds, validator reviews, approver signs. Without at least a skeleton of how this works (even if deferred), governance teams won’t see this as a serious tool. This is a significant gap for the stated target user.

### 4. Data Volume / Performance Not Addressed

The spec mentions “large datasets” as a later concern, but credit scorecards routinely use millions of rows. WOE transforms, profile statistics, and IV calculations are expensive. The plan has no mention of chunked processing, sampling strategies, or lazy evaluation. If this hits a wall at 5M rows in Streamlit, the MVP will be dismissed by practitioners.

### 5. Variable Selection is Underspecified

Stepwise variable selection is listed as a node, but this is a notoriously tricky area — forward/backward/both, entry/exit p-value thresholds, interaction with regularisation, collinearity handling. For governance purposes, the reason variables are selected or excluded needs to be auditable. The current design treats it like a single node without addressing its inherent complexity.

### 6. The GUI Plan Doesn’t Address the Hard UX Problem

The pathway builder UX section is mostly a feature list. The genuinely hard UX problem is: how does a user see at a glance which nodes are stale, which have run, which have failed, and what the current champion branch is? Streamlit’s stateless model is poorly suited to this. The plan should acknowledge this tension explicitly rather than leaving it as an implementation detail.

### 7. Open Question on DAGs vs Trees is Unresolved but Load-Bearing

If a downstream node consumes outputs from two different branches (e.g., a combined validation node), the strict tree model breaks. The plan notes this but doesn’t decide. This needs a decision before Phase 2, not after — it affects the artifact reference model and replay algorithm.

## Minor Points

- CSV vs Parquet is left open, but it matters for determinism. Parquet preserves column types; CSVs don’t. This should be decided early.
- Random seeds are mentioned under reproducibility but not in the node property schema. They should be a first-class node property for any stochastic step.
- PMML/ONNX export is listed as “later if useful” — PMML is the dominant format for scoring in banking systems (including SAS). Worth elevating.
- The definition of success is good and concrete — that’s one of the better parts of the spec.

## Summary Verdict

This is a well-thought-out spec for the engineering problem. The architecture is clean and the phasing is sensible. The gaps are mostly on the domain side — reject inference, train/test discipline, multi-user governance, and performance at realistic data volumes. A credit risk practitioner reviewing this would approve the design philosophy but push back hard on the domain completeness before signing off on it as governance-ready.
