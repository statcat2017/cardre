# Plan Review 006: Second Round Domain Foundations Review

This is substantially better than v1. The major gaps I flagged are mostly addressed — here’s an honest accounting of what improved and what remains.

## What’s Fixed

Train/test leakage prevention is now a first-class principle, with explicit rules per node type and a dedicated section. That’s the most important correction.

Desktop-first architecture resolves the data governance concern entirely. The Tauri + FastAPI sidecar model is the right call for sensitive credit data.

Manual binning is now properly specified — the JSON override structure with explicit reasons is exactly what’s needed for audit, and the list of supported operations (merge, isolate special codes, etc.) covers real practitioner needs.

Performance now has explicit targets (1M rows, 50 variables) and named tools (DuckDB, Polars). That’s actionable.

PMML is now on the export roadmap, appropriately deferred but acknowledged.

Non-Goals section is excellent — being explicit about what v0 won’t do is underrated and this list is well-judged.

## Remaining Gaps

### Reject inference is still not taken seriously

It’s mentioned once as “a later optional module.” For a tool targeting retail credit scorecards, reject inference affects the validity of every model built on approved-only data. It doesn’t need to be in v0, but the why of deferring it should be acknowledged — not just listed alongside PMML.

### Variable selection auditability is still thin

“Auditable inclusion/exclusion reasons” appears in the node roadmap but there’s no design for it. In practice this means: what goes into the audit record when a variable is dropped? A p-value threshold? A correlation threshold? A manual override with a reason field? The manual binning section has this level of detail — variable selection deserves the same treatment.

### The 4-eyes approval pattern is still absent

Multi-user collaboration is correctly out of scope, but single-user governance workflows still often require a state machine — draft → submitted → reviewed → approved. Even a lightweight version (champion branch + sign-off annotation) would make the tool more credible to model risk teams. The governance report section describes outputs but not the workflow that produces them.

### Packaging is the highest execution risk and gets the least design

PyInstaller vs Nuitka is listed as an open question, but this decision has large downstream consequences — Nuitka produces a compiled binary (better performance, no Python dependency exposure), PyInstaller produces a bundle that can trip AV software in corporate environments. The smoke test checklist is good; the packaging decision itself needs a recommendation, not just a question mark.

### The canonical hash question is still open but shouldn’t be

It’s listed as an open question but it’s foundational to the reproducibility contract. The spec correctly identifies that raw bytes aren’t enough, but doesn’t commit to a method. A concrete proposal (e.g. hash over column names + dtypes + sorted row fingerprints) should be in the design, even if implementation details evolve.

## Minor Points

The API surface section is a good addition — clean and appropriately minimal. The sidecar lifecycle steps are clear and production-realistic.

The Definition of Success has three well-separated stages (v0, v1, governance-ready) which is a significant improvement over v1’s single definition.

SQLite vs filesystem split is now explicit and the rationale is sound.

## Summary

V2 reads like a spec a senior engineer could start building from. The domain gaps that remain (reject inference, variable selection auditability, approval workflow) are bounded and deferrable — they don’t block v0. The packaging question and canonical hash question should be resolved before Phase 1 begins, not left open, because both affect foundational design decisions in `ArtifactRef` and the installer pipeline.
