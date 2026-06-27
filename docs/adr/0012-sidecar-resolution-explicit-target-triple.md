# Sidecar Resolution: Explicit Target-Triple Path

## Status

Accepted

## Context

Cardre ships as a Tauri v2 desktop application. The Rust shell
(`frontend/src-tauri/src/main.rs`) launches a PyInstaller-packed Python
sidecar (`cardre-api`) as a child process, polls
`http://127.0.0.1:{port}/health` until it reports `status == "ok"`, and
injects the API URL into the webview.

The sidecar binary name is platform-specific. Tauri's `externalBin` mechanism
treats the configured path as a **stem** and requires a file suffixed with the
Rust target triple (and `.exe` on Windows) at build time. The build script
(`scripts/build-sidecar.sh`) correctly produces
`frontend/src-tauri/binaries/cardre-api-{target-triple}`.

However, `main.rs` resolved the bundled sidecar as the **bare stem**:

```rust
let bundled = app.path().resource_dir().unwrap_or_default()
    .join("binaries")
    .join("cardre-api");  // NO target-triple suffix
```

Tauri bundles `externalBin` resources with the target-triple suffix preserved,
so in a packaged app the file at `resource_dir/binaries/` is
`cardre-api-{triple}{.exe?}`, not `cardre-api`. The `bundled.exists()` check
was always **false** in a packaged app, causing the launcher to silently fall
through to `which::which("cardre-api")` (not on PATH in a packaged app) and
then to `Command::new("cardre-api")` (also fails) → `FATAL: Could not start
cardre-api` → `exit(1)`.

**Why CI stayed green:** `smoke-test-sidecar` launched the standalone
PyInstaller binary from the artifact download dir, never via Tauri's bundled
resource path. `check-tauri` only ran `cargo check` (which validates
`externalBin` at compile time, not runtime resolution). ADR 0011 explicitly
acknowledged "No end-to-end sidecar launch" against the packed resource path.

**Dev masking:** In `npm run tauri dev`, `which::which("cardre-api")` succeeded
when `pip install -e ".[sidecar]"` put `cardre-api` on PATH, so dev limped
along via the PATH fallback and hid the broken bundled path.

## Decision

1. **Embed the target triple at Rust compile time.** `tauri-build` already
   emits `TAURI_ENV_TARGET_TRIPLE` via `cargo:rustc-env`. `main.rs` reads it
   with `env!("TAURI_ENV_TARGET_TRIPLE")` and builds the bundled path as
   `resource_dir/binaries/cardre-api-{triple}{.exe?}`.

2. **Keep `which::which("cardre-api")` as an intentional dev fallback** with
   clear diagnostic logging. A packaged app should never hit this path.

3. **Do NOT adopt `tauri-plugin-shell`.** The shell plugin is already a
   transitive dependency but is not a direct dep. Adopting it would require
   async `CommandChild`, capabilities, and a frontend plugin package — a
   broader change than the sidecar launch fix requires. The existing
   `std::process::Command` + explicit path approach is correct once the
   filename includes the target triple.

4. **Add CI that proves the naming contract.** A new `smoke-test-packaged-sidecar`
   job downloads the sidecar artifact into `frontend/src-tauri/binaries/` and
   runs the `sidecar_resolution` integration test, which asserts the naming
   contract across `tauri.conf.json`, `build-sidecar.sh`, and `main.rs`.

5. **Add a drift guard** (`scripts/check-sidecar-naming.py`) that fails if any
   of the three naming points (config, build script, Rust source) drifts.

## Consequences

- **Easier:** Packaged desktop app can now start its bundled sidecar. The
  resolution is explicit, logged, and tested.
- **Easier:** Naming drift across config/build-script/Rust-source is caught in
  CI before merge.
- **Harder:** `main.rs` now depends on `TAURI_ENV_TARGET_TRIPLE` being set at
  compile time. This is guaranteed by `tauri-build` (a build dependency), so
  it is always available in a normal `cargo build`/`cargo test` pipeline.
- **Risk:** The `sidecar_resolution` integration test uses `include_str!` to
  read `tauri.conf.json` and `build-sidecar.sh` at compile time. If those
  files are moved, the test breaks. This is desirable — it makes the contract
  load-bearing.

## Amendment: Windows Packaged Smoke Test Deferred

The new `smoke-test-packaged-sidecar` job runs on `ubuntu-latest` only.
PyInstaller cannot cross-compile; a Windows sidecar build requires a Windows
runner. The resolution logic's Windows branch (`cfg!(windows)` → `.exe`) is
unit-tested, but no Windows packaged binary is built or launched in CI. This
matches the pre-existing limitation documented in ADR 0011.
