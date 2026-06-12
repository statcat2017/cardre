# Plan Review 008: Second Round Desktop Packaging And Reproducibility Review

The second version of the plan is a substantial improvement. It makes hard, specific technology choices, sharpens the product scope, and directly addresses many of the first version's weaknesses. The shift to a desktop-only, Tauri-based app with a bundled Python sidecar is a bold and sensible move for a governance tool handling sensitive credit data. The plan is now far more concrete and buildable.

Below is a detailed critique of version two, highlighting what’s stronger, what’s still risky, and what needs further thought before building.

---

## 1. What’s significantly better than v1

### Hard technology choices

Moving from an abstract “GUI + application service layer” to a concrete stack (Tauri, React, FastAPI sidecar, SQLite, Parquet) transforms the plan from a wish list into an engineering blueprint. These choices are appropriate for a local-first desktop product that must never send sensitive data to the cloud.

### Desktop-only, no-cloud stance

This directly answers the biggest unspoken fear of credit-risk teams: “Where is my data going?” The plan now explicitly rules out remote execution, multi-user servers, and hosted features for the MVP. This builds trust and avoids a whole category of security reviews.

### Fixed pathway first, not a freeform DAG canvas

Constraining the initial GUI to a fixed scorecard pathway dramatically reduces UI complexity and lets the team deliver a working product faster. The backend remains DAG-capable, so the architecture isn’t painted into a corner. This is realistic product scoping.

### Leakage prevention

The explicit rules around fitting on train only, applying to test/OOT, and recording split logic in the audit trail show strong domain understanding. This is a correctness requirement that many tools fudge; getting it right from day one is a differentiator.

### Manual binning as a first-class citizen

The detailed description of manual binning – merging bins, isolating special codes, capturing reasons as JSON overrides, and warning on non-monotonic WOE – is excellent. This is exactly how professional scorecard builders work, and the plan treats it as core, not an afterthought.

### Canonical hashing, not raw byte hashing

The plan recognises that Parquet metadata can produce different bytes for the same logical data, and commits to defining a logical artifact hash. This is a deep but crucial point for reproducibility across environments.

### Model development report, not just a JSON manifest

Targeting an SR 11-7 style human-readable report with variable rationale, override reasons, stability metrics, and limitations elevates the audit export from a technical log to a governance deliverable. This is a strong differentiator.

### Packaging and installer smoke test

The inclusion of a bundled Python sidecar via PyInstaller/Nuitka, installer testing, and a sidecar health check shows the team is thinking about the real user experience, not just the development environment.

### Explicit non-goals

Listing what won’t be built (multi-user, cloud, reject inference, PMML, etc.) prevents scope creep and sets realistic expectations.

---

## 2. Remaining feasibility concerns

### Desktop stack complexity

Tauri + React + FastAPI + bundled Python is a lot of moving parts for a small team:

- **Sidecar management:** The Tauri shell must start, monitor, and shut down a Python process reliably on Windows, macOS, and Linux. Sidecar crashes, port conflicts, and antivirus interference are real-world nightmares. The plan mentions “capture sidecar logs” and “actionable messages”, but the implementation effort is non-trivial.
- **Bundled Python size:** A full Python runtime plus dependencies (pandas, scikit-learn, etc.) bundled via PyInstaller can exceed 200–300 MB. This may be acceptable for a specialised tool, but it’s worth benchmarking early.
- **Cross-platform quirks:** Python packaging on Windows (especially with C extensions like Polars or DuckDB) can cause DLL hell. macOS notarisation and code signing add further friction. The plan should acknowledge this and budget time accordingly.
- **Developer experience:** The development loop (change backend, restart sidecar, reload frontend) can be slow if not designed carefully. A “dev mode” that runs the backend separately is mentioned; ensure this is a first-class workflow, not an afterthought.

### Reproducibility contract

The plan aims for logical reproducibility: “equivalent logical artifacts and identical audit records except for run IDs and timestamps”. Achieving this across OS/architecture requires:

- **Canonical Parquet serialisation rules** — still an open question. Without a spec, two runs might produce different float representations or column orders.
- **Floating-point determinism** — Logistic regression solvers (even with the same seed) can produce slightly different coefficients across BLAS implementations. Scikit-learn’s liblinear is deterministic, but the plan must lock down the exact solver and library versions.
- **Dependency lockfile** — The plan mentions a “dependency lockfile hash”. This is good, but the bundled sidecar must embed the exact lockfile and validate it at runtime to prevent drift between development and production builds.

The plan acknowledges the difficulty; I recommend adding a test suite that executes the same scorecard on Linux, macOS, and Windows and asserts logical artifact equality. This will flush out hidden non-determinism early.

### Performance targets

“1M rows, 50 variables, profiling under one minute” is a reasonable target. However:

- Automatic fine classing on 1M rows with many variables can be slow if done naively (e.g., ChiMerge or decision-tree binning). The plan should specify which binning algorithm will be used and whether it’s been benchmarked.
- WOE/IV calculation is straightforward but may be memory-heavy if many categorical variables have high cardinality. The plan should clarify if category grouping is performed before WOE.
- DuckDB or Polars are mentioned as candidates, but no decision is made. Leaving this open risks a pandas-only implementation that struggles with the volume target. I recommend choosing one (Polars is lighter to bundle, DuckDB has SQL for reporting) and committing to it for the MVP.

### Manual binning UX

The plan describes the what of manual binning well, but the how is still vague:

- “Dedicated table/chart view” — What does this look like? Will the user drag bin boundaries on a histogram, or edit numbers in a table? Both are needed.
- “Show before/after WOE and event-rate charts” — This implies interactive charting. React charting libraries (e.g., Recharts, Plotly.js) can handle this, but performance with many bins and variables must be tested.
- “Override reasons” — The plan mandates reasons for manual changes. The UI must make this easy (e.g., a dropdown of common reasons, or a free-text field that is validated as non-empty). This adds state management complexity.
- The manual binning node produces JSON overrides, which is good. However, editing those overrides later (e.g., reordering, undoing a merge) requires a versioned, undoable edit model. The plan doesn’t address this.

### SQLite for metadata and run records

SQLite is a great choice for local metadata. But the plan mentions “small tabular reports” as an open question. My advice: store only metadata, hashes, and paths in SQLite. Keep any tabular data (even small ones) as Parquet artifacts. This maintains a clean boundary and avoids blob handling in SQLite.

---

## 3. Market fit and positioning

The plan positions Cardre as “PowerBI-style transform flow for scorecard modelling, but local-first, reproducible, branchable, and governance-aware.” This is clear and compelling.

### Strengths

- Addresses a real pain point: proprietary tools are expensive and opaque; open-source libraries require scripting and lack audit trails.
- The desktop-only, no-cloud posture will appeal to banks and lenders with strict data policies.
- The audit pack and model development report are genuine differentiators that no current open-source tool provides.

### Risks

- **User sophistication:** The fixed pathway and node property editor still assume a user comfortable with concepts like WOE, IV, binning, and logistic regression. A traditional credit analyst may be intimidated. A future “wizard mode” is mentioned; this needs to remain on the roadmap, as it will significantly expand the addressable market.
- **Competition from hosted tools:** If a competitor offers a cloud-based auditable scorecard builder with enterprise support, Cardre’s local-only stance becomes a feature for some but a friction for others who want team collaboration. The plan correctly postpones multi-user features, but the product will eventually face pressure to add them.
- **Open-source sustainability:** No monetisation path is discussed. This is fine for an open-source tool, but long-term maintenance requires institutional backing or a services model. The plan should at least mention the possibility of future enterprise support, training, or certification to keep the project healthy.

---

## 4. Risks (new and lingering)

1. **Desktop packaging fragility** — This is the biggest new risk. The sidecar approach introduces a class of bugs (port allocation, process lifecycle, environment differences) that web-only apps don’t have. Mitigation: invest heavily in integration tests that run on clean VMs, and budget for early packaging iterations.
2. **Reproducibility across platforms** — As noted, a cross-platform reproducibility test suite is essential. Without it, the audit claim will be hard to defend.
3. **Manual binning UX complexity** — This could balloon into a major development effort. Consider whether a simpler table-based editor with before/after charts (no drag-and-drop) is acceptable for v0. Drag-and-drop can come later.
4. **Dependency on Python ecosystem stability** — Bundling Python with a frozen lockfile is good, but the tool will be sensitive to the underlying OS. A Windows update breaking a DLL could break the sidecar. Frequent CI testing on all supported OS versions is necessary.
5. **Scope creep at phase boundaries** — The phases are now well-defined, but “duplicate branch” and “champion/challenger” in Phase 4 could become a larger project than anticipated if the UI for side-by-side comparison becomes complex. Resist the urge to add freeform DAG editing too early.
6. **Security model gaps** — The plan says “no plaintext sensitive values in logs” and “users are responsible for encrypted drives”. This is acceptable for MVP, but as the tool matures, features like project-level encryption or PII masking will become expected. The plan should at least note that the audit trail may contain variable names and derived values, which could be sensitive, and that users should be warned.

---

## 5. Open questions that need answers before Phase 1

The plan lists several open questions. I’ll offer concrete recommendations:

- **PyInstaller vs Nuitka:** Start with PyInstaller; it’s simpler and more battle-tested for scientific Python. Nuitka can be explored later if performance or size becomes an issue.
- **DuckDB, Polars, or pandas:** Use Polars for core tabular operations. It’s fast, memory-efficient, and bundles well. DuckDB can be added later for SQL-based reporting if needed. Avoid pandas as the primary engine for large data.
- **Canonical hash rules:** Define a spec: Parquet file, but logical hash computed over a sorted, canonical representation of the data (e.g., Arrow table with fixed schema, null representation, and column ordering). This can be implemented using PyArrow’s Table to bytes canonicalisation. Test early.
- **Minimum acceptable manual binning UX:** A table with editable bin boundaries, a histogram/event-rate chart per variable, and a structured reason field. No drag-and-drop for v0. This is achievable with a good React table library and Plotly.js.
- **SQLite for reports:** No. Store only metadata. Small reports can be stored as JSON or Parquet artifacts. This keeps SQLite schemas simple and avoids binary blobs.
- **Mandatory metrics in governance report:** KS, Gini/ROC AUC, PSI per segment, calibration plot, and variable IV. Add a characteristic stability index (CSI) and a coefficient business-sense sign check. Keep it focused.
- **License:** Apache 2.0 is generally preferred for enterprise adoption because of its patent grant. MIT is simpler but lacks explicit patent protection. Apache 2.0 is a safer choice for a tool aimed at regulated industries.

---

## 6. Recommendations for the next iteration (before coding starts)

1. **Build a thin vertical slice first** — Implement the full loop: Tauri shell starts sidecar, sidecar returns `/health`, React displays “Hello Cardre”. Then add a dummy node execution end-to-end. This de-risks the entire desktop architecture before any scorecard logic is written.
2. **Design the manual binning data model and UI mockups now** — Even paper sketches of the table/chart view will reveal state management challenges. Validate with a credit-risk practitioner.
3. **Lock down the canonical artifact hash spec** — Write a short technical document and a test that verifies logical equality across different Parquet files with known metadata differences. This will be foundational for audit trust.
4. **Define the node compatibility contract** — The plan mentions “node compatibility contracts” for Phase 6. Move a minimal version of this to Phase 1: every built-in node must declare its input/output artifact roles and property schema in a machine-readable way. This makes the internal registry testable from the start.
5. **Write a reproducibility test harness** — Even before the full engine, create a test that runs a simple pipeline with fixed seed and asserts deterministic outputs. Run it in CI on all three platforms.
6. **Clarify the “failure semantics” for manual binning** — If a user edits bins manually, then changes an upstream node (e.g., adds a new variable), what happens to the manual edits? They should become stale and require review, but not be silently discarded. This needs a clear rule.
7. **Budget for sidecar lifecycle robustness** — Allocate significant testing time for process crashes, port conflicts, and graceful shutdown. This will make or break the user’s first impression.
8. **Add a governance review pilot to Phase 5** — Partner with an internal model-risk team (or a friendly one) to review the generated model development report. Their feedback will be invaluable before claiming governance-readiness.

---

## Bottom line

The second version of the plan is focused, technically grounded, and product-savvy. It makes the right big bets: desktop-only, fixed pathway first, manual binning as core, and a human-readable governance report as differentiator. The remaining risks are execution-level: desktop packaging, cross-platform reproducibility, and manual binning UX. If the team invests early in de-risking these three areas with concrete prototypes and tests, Cardre has the potential to become the standard open-source tool for auditable credit scorecard development.
