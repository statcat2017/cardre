# Plan Review 004: Execution, Market Fit, And Technical Risk Review

I’ve read the plan in full. It’s unusually well-structured for an early-stage product outline: the vision is clear, the domain is well-understood, and the proposed architecture avoids a lot of classic monolith mistakes. That said, there are some real challenges around execution, market fit, and technical complexity that need more thought. Below is a detailed critique.

---

## 1. Overall strengths (what the plan gets right)

- **Audit-first thinking**
  Immutable snapshots, content-addressed artifacts, deterministic replay, and never mutating history are exactly what model-risk and governance teams need. The plan correctly separates plan from run and stores parameter hashes, input/output hashes, and code versions.
- **Clean separation of concerns**
  The scorecard domain is pure (`scorecard/`), nodes bridge GUI properties to domain functions (`nodes/`), and the GUI only edits plans and triggers execution. This makes the core testable and keeps scoring logic out of Streamlit/React.
- **Node model and branching**
  The DAG/tree with branching, sibling comparison, and champion/challenger labels is a strong differentiator. The idea of comparing two binning strategies side by side and exporting both audit packs is something proprietary tools rarely do well.
- **Plugin architecture**
  Entry-point discovery and custom node support from the start is ambitious but wise; it avoids a closed ecosystem and lets large lenders add proprietary transformations (e.g., custom affordability, reject inference) without forking.
- **Explicit phased roadmap**
  Phases 1–6 are concrete, with Foundation -> First Pathway -> GUI MVP -> Governance/Export -> Extensibility. This shows realistic scoping.

---

## 2. Clarity and completeness

### Well covered

- End-to-end workflow from project creation to export.
- Node inputs/outputs as tabular examples.
- Storage layout (`.cardre/`) and JSON manifests.
- Audit record schema.
- List of planned node types (data, binning, WOE/IV, modelling, scoring, validation, export).

### Areas where the plan is vague or underspecified

- **Target definition and profiling early steps** — “validate target” is mentioned but never detailed. What checks are performed? Binary vs continuous target? Event rate minimums? What happens when the target is missing or all-0? This matters for MVP reliability.
- **Coarse classing and manual bin editing UX** — The plan mentions “manual bin editing” and “bin override/import” but no concrete interaction model. Manual bin editing is famously fiddly and stateful; how will the GUI represent editable bin boundaries, and how will they be versioned?
- **Replay and state management** — The replay algorithm is described at a high level. It’s unclear how Cardre handles:
  - Nodes that have non-deterministic elements (e.g., random seed for train/test split). The plan says “deterministic” later, but early phases might need explicit seed handling.
  - Cancellation and partial runs. If a downstream node fails, do we mark the whole branch as failed and preserve partial outputs?
  - How plans are versioned. “Plan version” is referenced but the versioning scheme (sequential? timestamped?) is not defined.
- **Comparison views** — Listed (“Variable IV comparison”, “Model metric comparison”) but no mockup or concrete description. Will this be side-by-side tables, difference charts, or a third view? Without a clear UX design, this might be implemented inconsistently.
- **Export audit pack content** — Described as “full pathway graph, all node parameters, all node audit records…” but the format details (what exactly goes in HTML vs JSON) are left open. Governance teams will demand specific report sections (e.g., model development document in SR 11-7 style). The plan should specify that the export can generate a human-readable model development report — not just a machine-readable manifest.

---

## 3. Feasibility concerns

### Technical feasibility

- **Determinism across environments** — The plan mentions “Python version, dependency lockfile hash” for reproducibility. In practice, floating-point differences across OS/architecture or library versions (even minor) can change WOE calculations or logistic regression coefficients. Cardre will need a strict pinning strategy and possibly container-based execution to guarantee reproducibility. This is a massive operational challenge for an open-source tool without a hosted service.
- **Content-addressed artifact hashing** — Great idea, but the plan doesn’t specify how hashes are computed for tabular data. If Parquet files can have different internal compression metadata but identical logical content, hash mismatches will break reuse. Need canonical serialisation rules.
- **DuckDB/SQLite migration later** — The storage is initially filesystem-based. When moving to DuckDB, the entire project structure, artifact paths, and run manifests will need to adapt. Migrating in-place projects with history is hard; the plan should consider building on a simple embedded database (SQLite) from the start to avoid a painful migration.
- **Streamlit as GUI** — Streamlit is fine for MVP but has serious limitations:
  - Global script re-runs on every interaction make complex stateful pathway editing challenging.
  - No native tree/flowchart widget; you’ll need custom Streamlit components or hacky workarounds.
  - Branch comparison side-by-side views will require custom layout work.
  - Performance with large datasets (e.g., interactive binning visualisations) may hit limits.
    Plan for a potential React+FastAPI migration earlier than “later” if the product gains traction.
- **Node execution engine** — The plan says “execution can be local and synchronous” for early versions. A synchronous engine works for small datasets, but a single WOE calculation on millions of rows can block the GUI. Even in MVP, some form of background execution (threads/subprocess) with status polling is needed, else the tool will feel broken.

### Operational feasibility

- Single-user local-first MVP is sensible, but the plan mentions “multi-user/server project storage” later. Multi-user collaborative editing of a pathway DAG (with branching, stale markers, etc.) introduces concurrency challenges that are non-trivial. This should be deferred explicitly, not assumed as a natural extension.
- Testing strategy is good, but the node contract testing (“every node type”) needs a clear specification of what constitutes a valid/invalid node run. Without a shared harness, testing will be ad-hoc.

---

## 4. Market fit and differentiation

### Who is the customer?

The target users are:

1. Credit-risk analysts (practitioners).
2. Data scientists building scorecards.
3. Model-risk/governance teams.
4. Learners.

The plan strongly caters to (2) and (3), but (1) — the traditional credit analyst — often has limited programming experience. A Streamlit GUI might still be too technical if they have to understand DAGs, WOE transformations, and branching. The plan could benefit from a “wizard” mode or opinionated defaults that hide the underlying pathway from non-technical users while still producing an audit trail.

### Competitive landscape

- Proprietary tools (SAS Credit Scoring, FICO Model Builder, Experian PowerCurve) are entrenched. Their advantage: integrated data handling, regulatory templates, and vendor support.
- Open-source alternatives (e.g., scorecardpy, OptBinning in Python) provide functional libraries but no GUI, no branching, and no audit pack.
- Cardre’s differentiation is the auditable pathway tree with branching — a “git for scorecard modelling”. This is a strong narrative, but it will only win if the tool is as easy to use as a Jupyter notebook for prototyping and as trustworthy as a regulator-accepted report. The plan doesn’t yet address regulatory acceptance: will regulators accept an audit pack generated by an open-source tool? Need documentation of the tool’s development and validation (like an independent model validation of the tool itself).

### Monetisation

The plan doesn’t mention a business model. If it stays purely open-source, sustainment is a risk. Many successful OSS tools offer a hosted service or enterprise support. Cardre could eventually provide a cloud version with team collaboration, managed storage, and compliance reports. The architecture (local-first) makes a hosted version straightforward to add, but that should be acknowledged as a future direction.

---

## 5. Risks

1. **Reproducibility and floating-point drift** — As noted, this can undermine the entire audit promise. Without container or lockfile enforcement, outputs may differ across user machines, breaking trust.
2. **Complexity of the pathway UX** — A DAG editor with branching, property editing, stale markers, and comparison is a complex application. Streamlit may not scale to the necessary interactivity, leading to user frustration and slow iteration.
3. **Manual binning and property editing** — Manual binning is a high-touch activity. Poor UX here will kill adoption. If the tool doesn’t allow analysts to drag bin boundaries and see immediate WOE/IV impact, they will revert to Excel.
4. **Data size assumptions** — “CSV/parquet file” import implies small-to-medium data. Credit portfolios can have millions of records and hundreds of variables. The plan mentions DuckDB later, but early profiling and cleaning steps may need to work on out-of-core data from the start. If the MVP chokes on a 5GB CSV, it will be dismissed.
5. **Security** — No mention of security. Even local-first tools handling sensitive credit data need to consider encryption at rest, PII masking, and audit log integrity. A governance tool that stores raw data in `.cardre/datasets/` without access control is a risk.
6. **Over-engineering too early** — The plugin architecture, entry points, and custom renderers are phase 6. That’s fine. But even the internal node registry and property schema system could become a maintenance burden before the first scorecard is built. There’s a risk of building a framework instead of a product.

---

## 6. Missing elements and open questions

### Missing from the plan

- Dependency management and packaging — How will Cardre be installed? `pip install cardre`? Will it bundle all dependencies (scikit-learn, statsmodels, etc.)? Version conflicts with user environments could break deterministic execution. Consider a lockfile or poetry/pipenv integration from the start.
- Error handling and user feedback — When a node fails, what does the user see? A stack trace? A structured error with suggestions? The plan needs a section on error propagation and user-friendly messages.
- Performance benchmarks — No estimates for execution time or memory usage on representative datasets. For the MVP, the team should define a target dataset size (e.g., “100k rows, 50 variables”) and ensure the tool performs within acceptable limits.
- Model documentation template — The audit export is a manifest, but governance teams expect a model development document with business justification, variable selection rationale, and interpretation. The plan could include a template that auto-populates from node metadata.
- Testing with real regulatory scenarios — Consider adding a phase for “Regulatory pilot” where the tool is used to build a scorecard that is submitted to a friendly regulator or internal model-risk team for feedback.
- Community and governance — As an open-source project, who will maintain it? Need a CLA, contribution guidelines, and a code of conduct. The plan doesn’t mention community building.
- Accessibility — No mention of accessibility standards (WCAG) for the GUI. If banks adopt this, accessibility will be required.

### Open design questions from the plan, answered

- **Strict trees vs general DAGs?** Start with strict trees; DAG support can come later if needed. A tree is easier to visualise and reason about. Most scorecard workflows are linear with branches; shared downstream nodes (e.g., a single validation node used by multiple branches) are an edge case that can be worked around by duplicating.
- **Artifacts: CSV or parquet first?** Parquet first. It’s typed, compressed, and has better hash stability. CSV is a lossy import format; convert to Parquet on import.
- **Large datasets: store in project or reference externally?** For MVP, copy into project storage and hash. For larger data, allow external referencing with a hash stored, but warn that reproducibility depends on the external file not changing. This can be a flag.
- **Manual bin editing in MVP?** Yes, but only basic: edit bin boundaries for numeric variables and merge categories for categorical. Advanced drag-and-drop can wait.
- **Mandatory metrics for governance release?** KS, Gini/ROC AUC, PSI, and a calibration plot. Also include variable-level IV and coefficient stability across branches.

---

## 7. Recommendations for the next iteration of the plan

1. **Add a “Minimum Viable Scorecard” definition** — The absolute simplest end-to-end flow that a user will accept. E.g.: import CSV, auto-fine-class, WOE, logistic regression, scale, and export a points table. That’s the target for Phase 2; anything beyond that is nice-to-have.
2. **Design the manual binning UX early** — Even a paper sketch will expose state management challenges.
3. **Decide on a concrete storage/execution isolation strategy** — I suggest using SQLite from day one for metadata and run records, and keeping files for artifacts. This avoids migration pain and allows transactional plan updates.
4. **Specify the reproducibility contract** — “Two executions with the same inputs, params, and code version must produce bitwise-identical output artifacts.” This needs to be tested in CI with different Python versions and OSes to see what breaks.
5. **Integrate a model-development report template** — Partner with a credit-risk model governance expert to design an SR 11-7 style template, then make Cardre’s export fill it automatically. This is a killer feature.
6. **Plan for performance from Phase 1** — At minimum, ensure the profiling node can handle a million-row dataset in under a minute using streaming or chunked processing. DuckDB or Polars can be early dependencies.
7. **Define a simple security model** — Local-first, but recommend that projects can be stored on encrypted volumes and that no plaintext sensitive data is logged. Add a warning on project creation.
8. **Clarify the open-source license and community structure** — Apache 2.0 or MIT? Who decides on contributions? This matters for potential enterprise users.

---

## Bottom line

The plan is a compelling vision for a tool that could genuinely improve credit model governance. Its technical foundation is sound, but the risks around reproducibility, UX complexity, and data scale need early attention. Focusing ruthlessly on the simplest end-to-end audit pack — and testing it with real practitioners — will prove whether the concept holds before building the full extensibility framework.
