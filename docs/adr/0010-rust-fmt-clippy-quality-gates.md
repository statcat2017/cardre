# Rust Quality Gates: cargo fmt And cargo clippy In CI

## Status

Accepted

## Context

The Rust surface in this repository is small — `frontend/src-tauri/src/main.rs`
(~160 lines) plus `build.rs` — but it is the desktop launcher that spawns the
Python sidecar, handles Ctrl-C, manages the child process lifecycle, and
injects the API URL into the webview. It is the only code path that runs
outside the Python test suite and outside the frontend Vitest suite.

The current `check-tauri` job in `.github/workflows/ci.yml` runs `cargo check`
only. `cargo check` verifies that the code compiles but does not enforce
formatting or catch common Rust pitfalls (unnecessary clones, `unwrap` in
places where `?` would work, needless `Box`ing, `mut` bindings that are never
mutated, `Mutex` held across await points, etc.). There is no `clippy.toml`
or `rustfmt.toml` in `frontend/src-tauri/`, and no `[tool.ruff]`/mypy
equivalent on the Rust side.

Because the Rust surface is small and stable, the cost of adding `cargo fmt
--check` and `cargo clippy -- -D warnings` to CI is low, and the payoff is
proportional: a single `unwrap()` panic in `main.rs` would crash the desktop
app with no Python-stack trace to debug from.

## Decision

1. **Add `cargo fmt --check` and `cargo clippy --all-targets -- -D warnings`
   to the `check-tauri` job**, after `cargo check`. Both run in the
   `frontend/src-tauri` working directory.

2. **Baseline formatting before enabling the gate.** A one-off commit runs
   `cargo fmt` once to normalise `main.rs` and `build.rs`. Without this, the
   new `--check` step fails immediately on the first PR that enables it.

3. **Baseline clippy before enabling `-D warnings`.** A one-off commit runs
   `cargo clippy --fix` (where safe) and manually addresses remaining lints,
   so the gate starts from a clean baseline. Lints that require a deliberate
   choice (e.g. suppressing a lint with `#[allow(...)]` at a specific call
   site) are annotated with a comment explaining why.

4. **No `clippy.toml` or `rustfmt.toml` initially.** The defaults are
   sufficient for a 160-line crate. Add config files only if a specific lint
   or style rule needs project-wide tuning later.

5. **Order within the job:** `cargo fmt --check` → `cargo check` →
   `cargo clippy`. Formatting is cheapest to fail fast; clippy is most
   expensive and runs last.

## Consequences

- **Easier:** formatting drift is caught automatically; clippy surfaces
  `unwrap`/`expect` sites that could panic the desktop launcher at runtime
  (where they are hardest to debug).
- **Easier:** future contributors get immediate feedback on idiomatic Rust
  rather than a review-round-trip.
- **Harder:** the first PR enabling the gate must include a baselining
  commit. Any existing code that trips clippy must be fixed or explicitly
  `#[allow]`-ed with a justification.
- **Risk:** `-D warnings` on a Tauri crate can be noisy because Tauri's own
  macros occasionally trigger lints. Mitigated by running `cargo clippy
  --all-targets` locally first and reviewing the full output before enabling
  the gate; pin specific `#[allow]`s at the call site rather than downgrading
  the whole crate.
- **Risk:** `cargo fmt --check` will fail any PR that touched `main.rs`
  without running `cargo fmt`. Acceptable — this is the intended behaviour.