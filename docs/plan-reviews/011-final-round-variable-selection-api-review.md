# Plan Review 011: Final Round Variable Selection And API Review

V3 is in good shape. This reads like a document a team could build from. Here’s a final honest pass.

---

## What V3 Resolves Well

Canonical hashing is now designed, not deferred. Dual physical/logical hash with a specified canonical form is the right approach, and tying reproducibility verification explicitly to logical_hash comparison closes the open question cleanly.

The two-stream pathway is the right MVP structure. Making the build/validate split structural — enforced by the executor via role-tagged artifacts — is a significant improvement over “convention.” This is the correct way to prevent leakage architecturally.

Phase 1 is now split into 1A and 1B. Engine-first, then desktop shell, is the right sequencing. You can validate the core model before fighting Tauri.

Open engineering decisions are now resolved or appropriately bounded. PyInstaller to start, Polars + DuckDB split, table-based binning UX for v0 — these are sensible calls that unblock Phase 1.

Apache 2.0 decision is correct for regulated-industry adoption. MIT would have been fine but Apache’s patent grant matters for enterprise/bank context.

---

## Remaining Issues Worth Noting

### Variable selection auditability is still a list item, not a design.

“Auditable inclusion/exclusion reasons” appears in the node roadmap but the design never specifies what that means concretely. Manual binning gets a detailed JSON override schema — variable selection deserves the same treatment. At minimum: what fields go in the audit record when a variable is excluded? IV threshold used, correlation cluster assignment, manual override flag, reason text. This is important for governance-quality output.

### The API surface has a naming inconsistency.

The spec now correctly distinguishes node types from steps, but the API endpoints still use /nodes/{node_id} in two places. These should probably be /steps/{step_id} to match the data model.

### Reject inference is still underdeveloped as a deferred item.

Listing it as a non-goal is fine. But the current framing implies it’s a straightforward later add-on. In practice, adding reject inference after the pathway is fixed will require significant rework — the split step, WOE fitting, and model node all need to understand the accept/reject population distinction. A single sentence noting this architectural implication would prevent a nasty surprise in Phase 6+.

### The manual binning UX decision needs a minimum chart spec.

The manual binning UX decision (“table-based, no drag-and-drop”) is reasonable but the before/after chart requirement needs a minimum spec. “Before/after WOE and event-rate charts” is mentioned but for v0 this needs to be explicit: is this a static render after applying overrides, or live-updating as edits are made? Live update against 1M rows is a very different engineering problem than a recalculate button.

---

## Minor Points

The is_stale as computed-not-stored distinction is well-handled and the execution model section is now clean.

The open engineering decisions section is a good addition — it keeps those questions visible without blocking the spec.

The definition of success across three stages remains one of the strongest parts of the document.

---

## Summary

This is ready to build from. The two issues worth fixing before Phase 1 begins are the API naming inconsistency (trivial) and the variable selection audit record design (not trivial — do it before the modelling nodes section is implemented). Everything else is either correctly deferred or fine to resolve in-flight.
