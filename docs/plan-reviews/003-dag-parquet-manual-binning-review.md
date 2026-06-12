# Plan Review 003: DAG, Parquet, Manual Binning, And Governance Review

This is an exceptionally well-thought-out product plan. You have mapped out a clear understanding of both software engineering best practices (immutability, content-addressed storage, separation of concerns) and the specific pain points of credit risk modeling (traceability, reproducibility, and rigorous model governance).

The approach of treating the scorecard build as a deterministic, versioned graph is exactly what the credit risk industry needs to move away from legacy, black-box proprietary software.

Here is a targeted review of your plan, addressing your core architecture, your open design questions, and a few critical gotchas to watch out for.

## Key Strengths of the Plan

- **Purity of the Domain Layer (`scorecard/`):** Separating the pure mathematical and statistical domain logic from the pipeline orchestration (`nodes/`) and the UI (`gui/`) is an excellent design choice. It ensures that the underlying modeling engine can eventually be run headlessly in a CI/CD deployment pipeline or an automated batch scoring environment.
- **The Audit-First Mentality:** In credit risk, model governance (e.g., SR 11-7 compliance) often takes longer than actual model building. Making the execution deterministic and capturing parameters, hashes, and code versions directly into a JSON manifest solves a massive compliance headache out of the box.
- **Pragmatic MVP Choice:** Starting with local-first storage and a Streamlit GUI is highly efficient. It lets you validate the node engine logic and UX with real users before over-engineering a distributed backend or complex React frontend.

## Addressing Your Open Design Questions

### 1. Pathway Plans: Strict Tree vs. General DAG?

> **Recommendation:** Backend as a DAG; UI presented as a Tree (initially).

From a data-science perspective, true DAGs are useful (e.g., joining an external bureau dataset halfway through a pipeline). However, for a credit scorecard MVP, **95% of user actions are tree-based branching** (e.g., "Let's branch here to try a manual binning approach vs. an automatic one").

- Keep your backend implementation schema as a DAG (where nodes define an array of parent_step_ids).
- Restrict the MVP GUI to a strict tree structure where a node only has one parent. This prevents you from having to handle complex schema-merging or node-joining logic in the UI for Phase 1.

### 2. Artifact Storage: CSV vs. Parquet?

> **Recommendation:** Parquet internally; CSV for exports.

**Do not use CSV for internal artifact snapshots.** CSV lacks strict schema preservation, meaning data types (like integer vs. float, or string vs. categorical) can silently mutate when reading/writing between steps.

- Use **Parquet** for all internal step data snapshots. It preserves data types perfectly, handles null values natively, and is highly compressed.
- Keep **CSV** strictly as an output format for the final scorecard tables or audit packs that analysts want to open in Excel.

### 3. Manual Bin Editing: How much is needed for the MVP?

> **Recommendation:** Move this from an "open question" to a **Core Phase 2 Requirement**.

In professional credit risk scoring, automated binning algorithms (like decision-tree-based fine classing) get you only 70% of the way there. Risk analysts *always* manually adjust bins to:

- Enforce operational monotonicity.
- Isolate special values (e.g., "No hit", "999-Error codes").
- Combine small bins to ensure a minimum population size (e.g., at least 5% of records per bin).

If Cardre does not allow an analyst to manually override and merge bins through the GUI, it will be viewed as a toy rather than a professional tool. A simple interactive table or slider interface to group fine bins into coarse bins is essential for your first useful release.

## Architectural Blindspots & Nuances to Watch

### Streamlit State Management

Streamlit is fantastic for rapid prototyping, but its architecture is inherently linear—the entire script reruns from top to bottom on user interaction.

- Because your product relies on a visual graph and selective node execution, you will need to be incredibly disciplined with Streamlit's `st.session_state`.
- Ensure that the `PipelineExecutor` acts as the single source of truth, and Streamlit merely reads from it, rather than letting the UI drive execution states.

### Data Scale & Massive Snapshots

If a user imports a 5GB dataset, copying it into `.cardre/datasets/` and then caching full data snapshots at every downstream node (`clean_data`, `woe_transform`, etc.) will rapidly deplete local disk space.

- **The Fix:** For early versions, only snapshot data frames at steps where rows change or new columns are created.
- Alternatively, store data transformations as *views* or metadata recipes rather than physical data files, applying them on-the-fly from the source snapshot during a run, though physical parquet caching is safer for strict reproducibility if disk space allows.

### Mandatory Metrics for Governance

To make your Phase 5 "governance-ready," ensure your validation node prioritizes:

- **Gini / AUC** (Discrimination power).
- **Kolmogorov-Smirnov (KS) statistic** (Separation capacity).
- **Population Stability Index (PSI)** (Essential for monitoring data drift over time).
- **System Stability Index (SSI)** (To check if the characteristics themselves are shifting).

## Suggested Tweaks to the Implementation Phases

Your phased plan is solid, but given the critical nature of manual binning, consider shifting your milestones slightly:

```text
Phase 2: Foundation & Automated Binning (Profile -> Auto Fine Class -> WOE/IV)
Phase 3: GUI MVP (Streamlit interface for the Phase 2 pipeline)
Phase 4: The Human Element (Add Manual Bin Editing UI - highly critical for adoption)
Phase 5: Modelling, Scaling, & Validation (Logistic regression -> Points -> Metrics)
Phase 6: Governance & Export (Audit packs)
```

By bringing the GUI and manual binning forward, you can test the *interaction model* of your node pathways much sooner.

Considering that manual bin editing is a massive make-or-break feature for risk analysts, how do you envision representing those manual bin adjustments in your `plan_id` JSON specification so that they remain perfectly reproducible and auditable?
