# Cross-Platform Tauri Check And Sidecar Smoke Test In CI

## Status

Accepted (Windows matrix deferred — see amendment below)

## Context

CARDRE ships as a Tauri desktop application. The Rust shell
(`frontend/src-tauri/src/main.rs`) launches a PyInstaller-packed Python
sidecar (`cardre-api`) as a child process, polls `http://127.0.0.1:{port}/health`
until it reports `status == "ok"`, and injects the API URL into the webview.
The sidecar binary name is platform-specific
(`cardre-api-x86_64-pc-windows-msvc.exe` on Windows, `cardre-api-<arch>-<os>`
on Linux/macOS via Tauri's sidecar naming convention).

The current `check-tauri` job runs only on `ubuntu-latest` and only runs
`cargo check`. It downloads the sidecar artifact built by `build-sidecar`
(a Linux PyInstaller binary), runs `ls` and `file` on it, and never actually
launches it. This means:

1. **No Windows verification.** The sidecar binary naming, the `which::which`
   fallback path in `main.rs:71`, and the `Command::new` spawn behaviour on
   Windows are untested in CI. A regression that breaks Windows-only behaviour
   (path separators, `.exe` suffix, Windows Defender flagging PyInstaller
   binaries) lands green.

2. **No end-to-end sidecar launch.** The `/health` contract between the Rust
   shell and the Python sidecar (`sidecar/main.py`) is asserted only by
   Python unit tests that import the sidecar module directly — never by
   spawning the packed binary. PyInstaller packing can break imports
   (missing hidden imports, data files not bundled) in ways that pass the
   unit suite and fail at runtime. The `api` and `e2e` pytest markers exist
   in `pyproject.toml` but are not run against the packed binary in CI.

3. **`cargo check` on Linux does not catch platform-specific code paths.**
   `main.rs` uses `std::process::Command`, `which::which`, and
   `tauri::Manager::path` — all cross-platform, but the sidecar binary
   resolution at `main.rs:74-83` branches on `which::which` succeeding,
   which depends on PATH and platform.

## Decision

1. **Add a `smoke-test-sidecar` job** that actually launches the packed
   binary and asserts the health endpoint comes up. The job:
   - `needs: [build-sidecar]` (downloads the artifact).
   - Runs on `ubuntu-latest`.
   - Downloads the `cardre-api-sidecar` artifact into a known directory.
   - Spawns the binary in the background with a port argument.
   - Polls `http://127.0.0.1:18000/health` until it returns
     `{"status": "ok"}`, with a 30-second timeout.
   - Tears down the child process on success or failure.
   - Exits non-zero if health never comes up.
   - Selects the Linux binary explicitly via glob pattern to avoid
     accidentally executing a non-Linux artifact.

2. **Do not run the full `api`/`e2e` pytest markers against the packed
   binary in CI yet.** The smoke test covers the highest-risk gap (PyInstaller
   packing breaks imports). Running the full API suite against the packed
   binary is a larger lift (requires a conftest fixture that points httpx
   at the spawned process, port management, teardown on failure). Defer to a
   later iteration if the smoke test surfaces packing issues that warrant
   deeper coverage.

3. **`build-sidecar` stays Linux-only for now.** PyInstaller cross-compilation
   is not supported; a Windows sidecar build requires a Windows runner and a
   separate PyInstaller spec. A Windows sidecar build is a separate decision
   and is out of scope for this ADR.

4. **Windows `check-tauri` is deferred.** The initial plan was to add a
   `windows-latest` matrix leg, but `tauri-build` validates `externalBin`
   entries at compile time and no Windows-compatible sidecar binary exists
   in CI. See the amendment below for details.

## Consequences

- **Easier:** PyInstaller packing regressions (missing hidden imports, data
  files not bundled) are caught before merge by the smoke test, rather than
  after a release.
- **Harder:** the smoke test introduces a new flake vector — port conflicts
  on shared CI runners. Mitigated by using a fixed high port (18000)
  unlikely to collide.
- **Risk:** the smoke test couples CI to the sidecar's CLI contract (port
  argument, health endpoint shape). If `sidecar/main.py` changes its CLI,
  the smoke test breaks. This is desirable — it makes the contract
  load-bearing in CI rather than implicit.

## Amendment: Windows Matrix Deferred

The initial implementation included a `windows-latest` matrix leg for
`check-tauri`. This was removed because `tauri-build` validates `externalBin`
entries at compile time, and no Windows-compatible sidecar binary exists in
CI. A dummy text file did not resolve the issue — `cargo check` still failed
on Windows runners for reasons that could not be diagnosed without access
to the full compiler diagnostics.

The Windows matrix leg will be re-added in a follow-up PR that either:
1. Builds a Windows PyInstaller sidecar in a separate job and downloads it
   in the Windows `check-tauri` leg, or
2. Splits the Windows job into a pure Rust compile check that avoids
   `externalBin` validation (e.g. via a cargo feature flag that disables
   the `tauri::generate_context!()` macro's sidecar resolution).

Until then, `check-tauri` runs on `ubuntu-latest` only, and the required
status check list in ADR 0009 reflects this.

## Amendment: Sidecar Resolution Fixed

The "No end-to-end sidecar launch" gap noted in Context is partially closed by
ADR 0012: `main.rs` now resolves the bundled resource path explicitly
(`binaries/cardre-api-{triple}{.exe?}`), and `smoke-test-packaged-sidecar`
asserts the naming/resolution contract against a real downloaded sidecar
artifact. A full Tauri `tauri build --no-bundle` headless smoke test is still
deferred (flaky on shared runners); the contract test + `cargo check` with the
artifact present is the current proof.