# Plan Review 007: Second Round Desktop Data Engine Review

The shift to a **local-first Tauri desktop architecture** perfectly honors the reality of credit risk data: it is heavily regulated, highly sensitive, and suffers from intense "data gravity." Keeping the execution engine in Python via a local FastAPI sidecar while driving it with a React frontend gives you the best of both worlds—native data-science performance and a modern UI.

The JSON-serializable manual bin override layout is also exactly what was needed. Representing human interventions as structured code configuration rather than black-box binaries makes your reproducibility claim ironclad.

Let’s tackle your remaining open questions and call out a few unique desktop-delivery edge cases you'll face.

## Resolving the Open Questions

### 1. DuckDB, Polars, or Pandas?

> **Recommendation:** Use **Polars** for node transformations, **DuckDB** for profiling and aggregations. Skip Pandas entirely.

Pandas carries too much legacy overhead, struggles with memory efficiency on laptops, and treats missing values (NaN vs. None) inconsistently.

- **Polars** gives you blazing-fast, multi-threaded execution, native Parquet integration, and strict typing. It will easily handle your 1M+ row performance target on standard laptop hardware.
- **DuckDB** can be used alongside Polars if you need an out-of-core SQL engine to run rapid profiling queries or cross-tabulations directly against Parquet files without fully loading them into memory.

### 2. PyInstaller vs. Nuitka for Python Bundling?

> **Recommendation:** Start with **PyInstaller** for the MVP; benchmark Nuitka later.

- **PyInstaller** is the path of least resistance. It is well-documented, widely supported, and easily wraps a FastAPI application into a single executable sidecar that Tauri can launch.
- **Nuitka** compiles Python code down to C, offering better optimization and code obfuscation. However, debugging compilation failures with large data science libraries (like Scikit-Learn or Polars) can become a massive time-sink during early development.

### 3. Canonical Hashing Rules for Tabular Equality

To guarantee logical reproducibility without relying on volatile file-level binary hashes, your canonical hash should be computed from a deterministic metadata string.

| Layer | Component | Rules for the Hash Input |
|---|---|---|
| **Schema** | Types & Names | Order columns alphabetically, append their data types (e.g., age:Int32, balance:Float64). |
| **Data Matrix** | Row Content | Sort the DataFrame by a unique row ID (or a deterministic compound key) before serializing values to a string buffer. |
| **Metadata** | Role Mapping | Append the designated Target and ID column names to the string buffer. |

Run SHA-256 against this combined text structure. If the data types, column roles, and sorted row values are identical, the logical hash matches perfectly—even if the underlying Parquet files have different compression block sizes.

### 4. Minimum Acceptable Manual Binning UX for v0

Risk analysts live in charts. The bare minimum interface requires:

1. A **bar chart** showing the population distribution across fine bins, paired with a line plot of the event rate (bad rate).
2. A **tabular grid** where users can multi-select rows (fine bins) and click a "Merge" button.
3. A mandatory text input modal that pops up on merge, forcing the analyst to type their governance reason before the application saves the step configuration.

## Crucial Desktop Architecture Blindspots

Because Cardre is operating as a local desktop suite inside strict enterprise corporate environments (banks and lenders), you will run into infrastructure challenges that web apps never face:

### The "Local Firewall" Enterprise Trap

Corporate security tools (like Zscaler, Crowdstrive, or local Windows Defender policies) frequently block or flag applications attempting to open arbitrary localhost ports. If your Tauri shell tries to communicate with the FastAPI sidecar over `http://127.0.0.1:8000`, the bank's security software may silently drop the traffic.

- **The Fix:** Ensure your sidecar lifecycle manager dynamically discovers an open port and supports IPC (Inter-Process Communication) pipes or domain sockets as a fallback alternative to standard HTTP network ports if corporate policies block local TCP/IP traffic.

### Database Strategy (SQLite vs. Tabular Reports)

> *Should SQLite store small tabular reports?*

- **Keep SQLite strictly for metadata, schemas, and run status logs.**
- Save your validation metrics, WOE tables, and profiling summaries as small, lightweight JSON or Parquet files inside the `artifacts/` folder, and store *only the file path and its canonical hash* in SQLite. This keeps your database highly performant, easy to backup, and prevents database fragmentation when a user runs hundreds of challenger branches.

## Refined Core Metrics & Licensing

- **Mandatory Governance Metrics:** Do not compromise on your Phase 2 validation suite. You must include **Gini/AUC**, **KS Statistic**, and **Population Stability Index (PSI)**. Without PSI to track data drift between Train, Test, and OOT datasets, risk management teams will reject the output.
- **Open Source License:** Go with the **Apache 2.0 License**. While MIT is simple, Apache 2.0 provides an explicit grant of patent rights from contributors to users. In the banking and corporate lending space, legal departments are far more comfortable approving Apache 2.0 software because it protects them from patent trolling.

With the desktop shell architecture solidified, the engineering boundaries of this project are incredibly crisp.

Given that data leakage is the most common way scorecards fail in production, how do you plan to structurally enforce the "Train/Test/OOT split discipline" within the FastAPI sidecar so a node cannot accidentally compute WOE or Logistic parameters using data from the validation split?
