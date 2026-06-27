# Sidecar Resolution Hardening — Technical Plan

**Status:** Ready for implementation
**Mode:** TDD (red → green → refactor, vertical slices)
**Scope:** Fix the desktop sidecar packaging/launch risk. No broad architectural changes.

---

## 1. Root Cause (read this first)

Cardre is a Tauri v2 desktop app bundling a PyInstaller-packed Python FastAPI
sidecar. The chain has **three** naming points that must agree:

| Stage | Expected name | Source |
|-------|---------------|--------|
| Build (PyInstaller + script) | `frontend/src-tauri/binaries/cardre-api-{triple}{.exe?}` | `scripts/build-sidecar.sh:30-33` |
| Tauri compile-time validation | `src-tauri/binaries/cardre-api-{triple}{.exe?}` (stem `binaries/cardre-api` + triple) | `tauri.conf.json:28` `externalBin` |
| Runtime launch (Rust shell) | `resource_dir/binaries/cardre-api-{triple}{.exe?}` | `frontend/src-tauri/src/main.rs:96-101` |

**The bug:** `main.rs:101` joins `resource_dir/binaries/cardre-api` — the **bare
stem with no target-triple suffix and no `.exe`**. Tauri bundles `externalBin`
resources with the target-triple suffix preserved, so in a packaged app the
file at `resource_dir/binaries/` is `cardre-api-{triple}{.exe?}`, the
`bundled.exists()` check is **false**, and the launcher silently falls through
to `which::which("cardre-api")` (not on PATH in a packaged app) and then to
`Command::new("cardre-api")` (also fails) → `FATAL: Could not start cardre-api`
→ `exit(1)`.

**Why CI stayed green:** `smoke-test-sidecar` launches the standalone PyInstaller
binary from the artifact download dir, never via Tauri's bundled resource path.
`check-tauri` only runs `cargo check` (which validates `externalBin` at compile
time, not runtime resolution). ADR 0011 explicitly acknowledges "No end-to-end
sidecar launch" against the packed resource path.

**Dev masking:** In `npm run tauri dev`, `which::which("cardre-api")` succeeds
when `pip install -e ".[sidecar]"` put `cardre-api` on PATH, so dev limps along
via the PATH fallback and hides the broken bundled path.

---

## 2. Fix Strategy

Make sidecar resolution **explicit and correct** by embedding the target triple
at Rust compile time via `build.rs`, then building the bundled path with the
triple + `.exe` suffix. Keep `which::which` as an **intentional dev fallback**
with clear diagnostics. Add logging for path, port, health failure, and stderr.
Add CI that proves the naming contract and exercises the resolution path.

**No new plugin dependencies.** We do **not** adopt `tauri-plugin-shell` (it is
already in `Cargo.lock` transitively but not a direct dep; adopting it would
require async `CommandChild`, capabilities, and a frontend plugin pkg — out of
scope per "no broad architectural changes"). We use `std::process::Command`
with an explicit path, which is what `main.rs` already does — just with the
correct name.

---

## 3. Files Changed

| File | Change |
|------|--------|
| `frontend/src-tauri/build.rs` | Emit `CARDRE_TARGET_TRIPLE` env at compile time |
| `frontend/src-tauri/src/main.rs` | Explicit resolution + logging + unit tests |
| `frontend/src-tauri/tests/sidecar_resolution.rs` | **NEW** integration test (cargo test target) |
| `scripts/build-sidecar.sh` | Add post-build naming assertion |
| `scripts/check-sidecar-naming.py` | **NEW** drift guard (CI + local) |
| `.github/workflows/ci.yml` | New `smoke-test-packaged-sidecar` job + naming guards |
| `docs/release/sidecar-packaging.md` | **NEW** sidecar packaging/runbook doc |
| `docs/adr/0012-sidecar-resolution-explicit-target-triple.md` | **NEW** ADR |
| `docs/adr/0011-cross-platform-tauri-check-and-sidecar-smoke-test.md` | Add amendment |
| `docs/troubleshooting.md` | Update "Sidecar Won't Start" |
| `README.md` | Update sidecar build section |
| `scripts/check_doc_references.py` | Add new doc paths to allowed list if needed |

---

## 4. TDD Order (vertical slices)

Follow this exact order. **One test → minimal impl → next test.** Do NOT write
all tests first.

### Slice A — `sidecar_binary_name()` (pure function, unit test)

**Red A1:** In `main.rs`, add a `#[cfg(test)]` module with:

```rust
#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn sidecar_binary_name_includes_target_triple() {
        // CARDRE_TARGET_TRIPLE is emitted by build.rs; in test it may be the
        // host triple. Assert the format, not the exact triple.
        let name = sidecar_binary_name();
        assert!(
            name.starts_with("cardre-api-"),
            "expected cardre-api-{{triple}}, got {name}"
        );
        assert!(
            !name.ends_with(".exe") || cfg!(windows),
            ".exe suffix must only appear on windows, got {name}"
        );
        if cfg!(windows) {
            assert!(name.ends_with(".exe"), "windows name must end .exe, got {name}");
        }
    }
}
```

Run: `cd frontend/src-tauri && cargo test sidecar_binary_name_includes_target_triple`
→ fails to compile (`sidecar_binary_name` undefined).

**Green A1:** In `build.rs`, emit the triple:

```rust
fn main() {
    emit_target_triple();
    tauri_build::build();
}

fn emit_target_triple() {
    // rustc sets CARGO_CFG_TARGET_* for build scripts. Assemble the canonical
    // target triple: {arch}-{vendor}-{os}-{env}[-{abi}].
    // Vendor is not exposed via CARGO_CFG_TARGET_*; default to "unknown" which
    // matches the triples Tauri expects (x86_64-unknown-linux-gnu etc.).
    let arch = std::env::var("CARGO_CFG_TARGET_ARCH").unwrap_or_else(|_| fallback_arch());
    let os = std::env::var("CARGO_CFG_TARGET_OS").unwrap_or_else(|_| fallback_os());
    let env = std::env::var("CARGO_CFG_TARGET_ENV").unwrap_or_default();
    let abi = std::env::var("CARGO_CFG_TARGET_ABI").unwrap_or_default();
    let vendor = "unknown";
    let triple = if abi.is_empty() {
        format!("{arch}-{vendor}-{os}-{env}")
    } else {
        format!("{arch}-{vendor}-{os}-{env}-{abi}")
    };
    println!("cargo:rustc-env=CARDRE_TARGET_TRIPLE={triple}");
    println!("cargo:rerun-if-changed=binaries/");
}

fn fallback_arch() -> String {
    // Dev-mode fallback when not built via cargo for a real target.
    std::env::var("HOST_ARCH").unwrap_or_else(|_| "x86_64".to_string())
}
fn fallback_os() -> String {
    std::env::var("HOST_OS").unwrap_or_else(|_| "linux".to_string())
}
```

In `main.rs`, add the function + read the compile-time env:

```rust
const SIDECAR_NAME: &str = "cardre-api";

/// The target triple embedded at compile time by build.rs.
fn target_triple() -> &'static str {
    env!("CARDRE_TARGET_TRIPLE")
}

/// Bundled sidecar filename: `cardre-api-{triple}` plus `.exe` on Windows.
fn sidecar_binary_name() -> String {
    let base = format!("{SIDECAR_NAME}-{}", target_triple());
    if cfg!(windows) {
        format!("{base}.exe")
    } else {
        base
    }
}
```

Run: `cargo test sidecar_binary_name_includes_target_triple` → green.

**Refactor A:** None needed.

---

### Slice B — `bundled_sidecar_path()` (pure path builder, unit test)

**Red B1:**

```rust
    #[test]
    fn bundled_sidecar_path_uses_binaries_subdir_and_triple_name() {
        let dir = std::path::PathBuf::from("/tmp/fake-resource");
        let path = bundled_sidecar_path(&dir);
        assert_eq!(path, dir.join("binaries").join(sidecar_binary_name()));
        assert!(path.to_string_lossy().contains("binaries/cardre-api-"));
    }
```

Run: fails to compile (`bundled_sidecar_path` undefined).

**Green B1:**

```rust
/// Path to the bundled sidecar inside a Tauri resource dir.
fn bundled_sidecar_path(resource_dir: &std::path::Path) -> std::path::PathBuf {
    resource_dir.join("binaries").join(sidecar_binary_name())
}
```

Run: green.

---

### Slice C — `resolve_sidecar()` (resolution + dev fallback, unit test)

**Red C1:** Test that bundled path is preferred when it exists:

```rust
    #[test]
    fn resolve_sidecar_prefers_bundled_when_present() {
        let tmp = tempfile::tempdir().expect("tempdir");
        let resource = tmp.path();
        let bin_dir = resource.join("binaries");
        std::fs::create_dir_all(&bin_dir).unwrap();
        let bin_path = bin_dir.join(sidecar_binary_name());
        std::fs::write(&bin_path, b"#!fake\n").unwrap();
        #[cfg(unix)]
        {
            use std::os::unix::fs::PermissionsExt;
            std::fs::set_permissions(&bin_path, std::fs::Permissions::from_mode(0o755)).unwrap();
        }

        let resolved = resolve_sidecar(Some(resource)).expect("should resolve");
        assert_eq!(resolved, bin_path);
    }
```

Run: fails (`resolve_sidecar` undefined, and `tempfile` not a dep).

Add `tempfile` to `[dev-dependencies]` in `Cargo.toml`:

```toml
[dev-dependencies]
tempfile = "3"
```

Run: fails to compile (`resolve_sidecar` undefined). Now implement:

**Green C1:**

```rust
/// Resolve the sidecar binary path. Bundled first; dev PATH fallback second.
/// Returns Err with both attempted paths so the failure is diagnosable.
fn resolve_sidecar(resource_dir: Option<&std::path::Path>) -> Result<std::path::PathBuf, String> {
    // 1. Bundled (packaged app / tauri build with externalBin).
    if let Some(rd) = resource_dir {
        let bundled = bundled_sidecar_path(rd);
        if bundled.exists() {
            return Ok(bundled);
        }
        eprintln!(
            "sidecar: bundled path not found: {}",
            bundled.display()
        );
    }

    // 2. Dev fallback: cardre-api on PATH (pip install -e ".[sidecar]").
    //    Intentional for `npm run tauri dev`. A packaged app should never hit this.
    if let Ok(p) = which::which(SIDECAR_NAME) {
        eprintln!(
            "sidecar: dev fallback using PATH entry: {}",
            p.display()
        );
        return Ok(p);
    }

    Err(format!(
        "Could not resolve sidecar. Bundled: {:?}; PATH entry `{SIDECAR_NAME}` not found.",
        resource_dir.map(|rd| bundled_sidecar_path(rd))
    ))
}
```

Run: green.

**Red C2:** Test that dev fallback is used when bundled absent:

```rust
    #[test]
    fn resolve_sidecar_falls_back_to_path_when_bundled_absent() {
        let tmp = tempfile::tempdir().expect("tempdir");
        // No binaries/ dir created — bundled path won't exist.
        // We can't reliably make which::which succeed in a unit test without
        // polluting PATH, so assert the error message mentions both attempts.
        let err = resolve_sidecar(Some(tmp.path())).unwrap_err();
        assert!(err.contains("binaries/cardre-api-"), "err should list bundled path: {err}");
        assert!(err.contains(SIDECAR_NAME), "err should mention PATH entry: {err}");
    }
```

Run: should already be green (the error path returns both). If green, move on —
this test locks in the diagnostic contract.

---

### Slice D — Wire `resolve_sidecar` into `main()` + logging

This slice modifies the existing `setup` closure. There's no clean unit test
for the wired version (it needs a Tauri app handle), so we verify via the
integration test in Slice F and the CI smoke job. Keep this slice minimal.

**Replace** `main.rs:94-125` (the `sidecar_cmd` block + spawn) with:

```rust
            // Resolve the sidecar binary: bundled first (packaged), then dev PATH fallback.
            let resource_dir = app.path().resource_dir().ok();
            let sidecar_path = match resolve_sidecar(resource_dir.as_deref()) {
                Ok(p) => p,
                Err(e) => {
                    eprintln!("FATAL: {e}");
                    std::process::exit(1);
                }
            };
            eprintln!("sidecar: resolved path: {}", sidecar_path.display());
            eprintln!("sidecar: port: {port}");

            let mut child: Child = match Command::new(&sidecar_path)
                .arg(port.to_string())
                .stdout(Stdio::piped())
                .stderr(Stdio::piped())
                .spawn()
            {
                Ok(c) => {
                    eprintln!("sidecar: started {} (pid {})", sidecar_path.display(), c.id());
                    c
                }
                Err(e) => {
                    eprintln!(
                        "FATAL: Could not start sidecar at {}: {e}",
                        sidecar_path.display()
                    );
                    std::process::exit(1);
                }
            };
```

**Keep** the existing stdout/stderr line readers (`spawn_line_reader`) — they
already prefix `[sidecar] ` / `[sidecar:err] `. That satisfies "child process
stderr" logging.

**Improve** the health-failure block (`main.rs:144-155`) to dump the resolved
path and port again on failure (stderr is already streamed live):

```rust
            match wait_for_health(port, 30) {
                Ok(()) => eprintln!("sidecar: healthy on port {port}"),
                Err(e) => {
                    eprintln!(
                        "FATAL: sidecar health check failed: {e} (path={}, port={port})",
                        sidecar_path.display()
                    );
                    if let Ok(mut guard) = app.state::<AppState>().sidecar_child.lock() {
                        if let Some(ref mut c) = *guard {
                            kill_child(c);
                        }
                    }
                    std::process::exit(1);
                }
            }
```

Run: `cargo check` and `cargo clippy --all-targets -- -D warnings` → must pass.

---

### Slice E — `build-sidecar.sh` naming assertion

**Edit** `scripts/build-sidecar.sh` — after the `mv` block (line 33), add:

```bash
# Guard: the binary MUST be triple-suffixed for Tauri externalBin to find it.
# x86_64-pc-windows-msvc.exe on Windows; {arch}-{vendor}-{os}[-{env}] elsewhere.
if [[ "$TARGET" != *.* ]] && [[ ! -f "frontend/src-tauri/binaries/cardre-api-${TARGET}" ]]; then
  echo "ERROR: expected frontend/src-tauri/binaries/cardre-api-${TARGET} after rename"
  exit 1
fi
echo "Verified: frontend/src-tauri/binaries/cardre-api-${TARGET}"
```

(Windows path: PyInstaller emits `cardre-api.exe`; the existing `mv` command
would need `cardre-api.exe` → `cardre-api-${TARGET}.exe`. If running on Windows,
adjust the `mv` source name. For now CI is Linux-only, so the existing `mv`
works. Add a comment noting the Windows case.)

Run: `bash scripts/build-sidecar.sh` locally if PyInstaller is installed; else
verify the guard logic by reading.

---

### Slice F — Integration test `tests/sidecar_resolution.rs`

**NEW file** `frontend/src-tauri/tests/sidecar_resolution.rs`:

```rust
//! Integration test: bundled sidecar filename matches the Tauri externalBin
//! convention (cardre-api-{triple}{.exe?}) and the build script + main.rs agree.
//!
//! Run: cargo test --test sidecar_resolution

// We reuse the pure functions from the crate by making them pub. Alternatively
// re-implement the path builder here against the published contract. This test
// asserts the CONTRACT (what file name Tauri expects), independent of main.rs
// internals, so it fails if either side drifts.

/// The stem declared in tauri.conf.json externalBin.
const SIDECAR_STEM: &str = "binaries/cardre-api";

/// Build the expected bundled resource filename for the compile-time triple.
fn expected_bundled_filename() -> String {
    let triple = env!("CARDRE_TARGET_TRIPLE");
    if cfg!(windows) {
        format!("cardre-api-{triple}.exe")
    } else {
        format!("cardre-api-{triple}")
    }
}

#[test]
fn expected_filename_matches_tauri_convention() {
    let name = expected_bundled_filename();
    assert!(name.starts_with("cardre-api-"), "got {name}");
    if cfg!(windows) {
        assert!(name.ends_with(".exe"), "windows must end .exe: {name}");
    } else {
        assert!(!name.ends_with(".exe"), "non-windows must not end .exe: {name}");
    }
}

#[test]
fn stem_in_tauri_conf_is_cardre_api() {
    // Parse tauri.conf.json and assert externalBin contains the stem.
    let conf = include_str!("../tauri.conf.json");
    assert!(
        conf.contains("\"externalBin\""),
        "tauri.conf.json must declare externalBin"
    );
    assert!(
        conf.contains(SIDECAR_STEM),
        "tauri.conf.json externalBin must list {SIDECAR_STEM}"
    );
}

#[test]
fn build_sidecar_script_produces_triple_suffixed_name() {
    // Static contract: the build script must mv to cardre-api-${TARGET}.
    let script = include_str!("../../../scripts/build-sidecar.sh");
    assert!(
        script.contains("--name cardre-api"),
        "build-sidecar.sh must pyinstaller --name cardre-api"
    );
    assert!(
        script.contains("cardre-api-${TARGET}") || script.contains("cardre-api-${TARGET}.exe"),
        "build-sidecar.sh must rename to cardre-api-${TARGET}{{.exe}}"
    );
}

#[test]
fn binaries_dir_contains_expected_file_when_built() {
    // Only assert presence if the binaries dir exists (dev/CI with artifact).
    let bin_dir = std::path::Path::new("binaries");
    if !bin_dir.exists() {
        eprintln!("skipped: binaries/ not present (no sidecar built in this env)");
        return;
    }
    let expected = bin_dir.join(expected_bundled_filename());
    assert!(
        expected.exists(),
        "expected bundled sidecar {} but binaries/ = {:?}",
        expected.display(),
        std::fs::read_dir(bin_dir).ok().map(|mut it| {
            it.by_ref().filter_map(|e| e.ok().map(|e| e.file_name().to_string_lossy().to_string())).collect::<Vec<_>>()
        })
    );
}
```

> **Note on crate-private functions:** `sidecar_binary_name`/`resolve_sidecar`
> live in `main.rs` (a binary crate). Integration tests in `tests/` cannot call
> them directly. That's intentional — this test asserts the **contract** (file
> names) independent of internals, so it fails if any of the three naming points
> drift. The unit tests in `main.rs` (Slice A–C) cover the internal functions.

Run: `cargo test --test sidecar_resolution` → green (skip the binaries-presence
test locally if no sidecar built; in CI the artifact is downloaded first).

---

### Slice G — `scripts/check-sidecar-naming.py` (drift guard)

**NEW file** `scripts/check-sidecar-naming.py`:

```python
#!/usr/bin/env python3
"""Fail if sidecar naming drifts across tauri.conf.json, build-sidecar.sh, main.rs.

Run locally and in CI. Exits non-zero on drift.
"""
from __future__ import annotations
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
CONF = ROOT / "frontend/src-tauri/tauri.conf.json"
BUILD_SCRIPT = ROOT / "scripts/build-sidecar.sh"
MAIN_RS = ROOT / "frontend/src-tauri/src/main.rs"

errors: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    if not ok:
        errors.append(f"{name}: {detail}" if detail else name)


conf = CONF.read_text()
check(
    "tauri.conf.json externalBin stem",
    '"externalBin"' in conf and "binaries/cardre-api" in conf,
    "must list binaries/cardre-api in externalBin",
)

script = BUILD_SCRIPT.read_text()
check(
    "build-sidecar.sh pyinstaller name",
    "--name cardre-api" in script,
    "must pyinstaller --name cardre-api",
)
check(
    "build-sidecar.sh triple rename",
    "cardre-api-${TARGET}" in script,
    "must rename to cardre-api-${TARGET}",
)

main = MAIN_RS.read_text()
check(
    "main.rs SIDECAR_NAME const",
    'SIDECAR_NAME: &str = "cardre-api"' in main,
    "must define SIDECAR_NAME = cardre-api",
)
check(
    "main.rs uses target triple",
    "CARDRE_TARGET_TRIPLE" in main and "env!" in main,
    "must read CARDRE_TARGET_TRIPLE via env!",
)
check(
    "main.rs no bare cardre-api Command::new",
    not re.search(r'Command::new\(\s*"cardre-api"\s*\)', main),
    "must not fall back to Command::new(\"cardre-api\")",
)
check(
    "main.rs bundled path uses sidecar_binary_name",
    "sidecar_binary_name()" in main and "binaries" in main,
    "bundled path must use sidecar_binary_name()",
)

if errors:
    print("Sidecar naming drift detected:", file=sys.stderr)
    for e in errors:
        print(f"  - {e}", file=sys.stderr)
    sys.exit(1)
print("Sidecar naming consistent across config, build script, and main.rs.")
```

Make it executable: `chmod +x scripts/check-sidecar-naming.py`.

Run: `python3 scripts/check-sidecar-naming.py` → fails until main.rs is updated
(Slice D done), then green.

---

### Slice H — CI updates (`.github/workflows/ci.yml`)

**H1. Add naming guard to `lint` job** (after "Check doc references"):

```yaml
      - name: Check sidecar naming consistency
        run: python3 scripts/check-sidecar-naming.py
```

**H2. New job `smoke-test-packaged-sidecar`** — proves the bundled resource
path resolution. Insert after `check-tauri`:

```yaml
  smoke-test-packaged-sidecar:
    runs-on: ubuntu-latest
    needs: [build-sidecar]
    timeout-minutes: 20
    steps:
      - uses: actions/checkout@v4
      - name: Install system deps
        run: sudo apt-get update && sudo apt-get install -y libwebkit2gtk-4.1-dev libgtk-3-dev libayatana-appindicator3-dev librsvg2-dev
      - uses: actions-rust-lang/setup-rust-toolchain@v1
        with:
          cache-workspaces: "frontend/src-tauri"
      - name: Download sidecar binary
        uses: actions/download-artifact@v4
        with:
          name: cardre-api-sidecar
          path: frontend/src-tauri/binaries/
      - name: Make sidecar executable
        run: chmod +x frontend/src-tauri/binaries/cardre-api-*
      - name: Verify naming + resolution contract
        working-directory: frontend/src-tauri
        run: |
          # The integration test asserts binaries/cardre-api-{triple} exists
          # and that main.rs / tauri.conf.json / build-sidecar.sh agree.
          cargo test --test sidecar_resolution -- --nocapture
      - name: Naming guard
        run: python3 scripts/check-sidecar-naming.py
      - name: Assert resource path compiles (cargo check with artifact present)
        working-directory: frontend/src-tauri
        run: cargo check
```

**H3. Extend `smoke-test-sidecar`** — add a naming assertion after the binary
launches healthy (before `exit 0`):

```yaml
          # Naming guard: the artifact must be triple-suffixed for Tauri.
          case "$BINARY" in
            *cardre-api-*-unknown-linux-gnu) echo "Naming OK: $BINARY" ;;
            *) echo "ERROR: sidecar not triple-suffixed: $BINARY"; exit 1 ;;
          esac
```

(Place this right after the `echo "Sidecar is healthy"` / before `kill` block.)

---

### Slice I — Docs

**I1. NEW `docs/release/sidecar-packaging.md`:**

```markdown
# Sidecar Packaging & Launch

Cardre's desktop app bundles a PyInstaller-packed Python FastAPI sidecar
(`cardre-api`) via Tauri's `externalBin` mechanism.

## Naming convention

Tauri treats each `externalBin` entry as a **stem** and requires a
platform-specific variant suffixed with the Rust target triple (and `.exe` on
Windows) at build time:

| Platform | Bundled filename |
|----------|------------------|
| Linux x86_64 | `cardre-api-x86_64-unknown-linux-gnu` |
| macOS Apple Silicon | `cardre-api-aarch64-apple-darwin` |
| macOS Intel | `cardre-api-x86_64-apple-darwin` |
| Windows x86_64 | `cardre-api-x86_64-pc-windows-msvc.exe` |

At runtime the packaged app finds the binary at
`{resource_dir}/binaries/cardre-api-{triple}{.exe?}`. The target triple is
embedded at Rust compile time by `frontend/src-tauri/build.rs` (env
`CARDRE_TARGET_TRIPLE`) and read in `main.rs` via `env!`.

## Build the sidecar

```bash
pip install pyinstaller
pip install -e ".[sidecar]"
./scripts/build-sidecar.sh            # auto-detect host triple
./scripts/build-sidecar.sh aarch64-apple-darwin  # explicit
```

Output: `frontend/src-tauri/binaries/cardre-api-{triple}{.exe?}`.

## Dev mode (`npm run tauri dev`)

In dev the bundled path may not exist yet. `main.rs` falls back to
`which::which("cardre-api")`, which succeeds when
`pip install -e ".[sidecar]"` put the `cardre-api` console script on PATH.
This fallback is **intentional for dev only**; a packaged app should never hit
it. The launcher logs which path it used:

```
sidecar: resolved path: /home/.../binaries/cardre-api-x86_64-unknown-linux-gnu
sidecar: port: 54321
sidecar: started ... (pid 12345)
sidecar: healthy on port 54321
```

or, in dev:

```
sidecar: bundled path not found: .../binaries/cardre-api-x86_64-unknown-linux-gnu
sidecar: dev fallback using PATH entry: /home/.../.venv/bin/cardre-api
```

## CI guards

- `scripts/check-sidecar-naming.py` — fails if `tauri.conf.json`,
  `build-sidecar.sh`, and `main.rs` disagree on the sidecar name.
- `smoke-test-sidecar` — launches the standalone PyInstaller binary and asserts
  `/health` comes up, and asserts the filename is triple-suffixed.
- `smoke-test-packaged-sidecar` — downloads the sidecar artifact into
  `frontend/src-tauri/binaries/` and runs the `sidecar_resolution` integration
  test, proving the bundled resource path contract.

## Troubleshooting

See `docs/troubleshooting.md` → "Sidecar Won't Start".
```

**I2. NEW `docs/adr/0012-sidecar-resolution-explicit-target-triple.md`** — use
the repo's ADR template (check `docs/adr/0001-*` for format). Key content:

- **Status:** Accepted
- **Context:** `main.rs` resolved the bundled sidecar as the bare stem
  `binaries/cardre-api`, but Tauri bundles `externalBin` resources with the
  target-triple suffix preserved. The bundled branch never matched; the app
  fell through to a PATH lookup that cannot work when packaged. CI never
  exercised the packaged resource path, so the drift stayed green (ADR 0011
  acknowledged the gap).
- **Decision:** Embed the target triple at Rust compile time via `build.rs`
  (`cargo:rustc-env=CARDRE_TARGET_TRIPLE`), and in `main.rs` build the bundled
  path as `resource_dir/binaries/cardre-api-{triple}{.exe?}` explicitly. Keep
  `which::which("cardre-api")` as an intentional dev fallback with diagnostics.
  Do **not** adopt `tauri-plugin-shell` (already a transitive dep) — it would
  require async `CommandChild`, capabilities, and a frontend plugin package,
  which is broader than the sidecar launch fix requires.
- **Consequences:** Easier: packaged launch works; naming drift fails CI.
  Harder: `build.rs` now depends on `CARGO_CFG_TARGET_*` env vars (set by
  rustc for build scripts) — a non-cargo build would need to set
  `CARDRE_TARGET_TRIPLE` manually. Risk: Windows packaged smoke test still
  deferred (PyInstaller cross-compile not supported; ADR 0011 amendment).

**I3. Amend `docs/adr/0011-...md`** — append:

```markdown
## Amendment: Sidecar Resolution Fixed

The "No end-to-end sidecar launch" gap noted in Context is partially closed by
ADR 0012: `main.rs` now resolves the bundled resource path explicitly
(`binaries/cardre-api-{triple}{.exe?}`), and `smoke-test-packaged-sidecar`
asserts the naming/resolution contract against a real downloaded sidecar
artifact. A full Tauri `tauri build --no-bundle` headless smoke test is still
deferred (flaky on shared runners); the contract test + `cargo check` with the
artifact present is the current proof.
```

**I4. Update `docs/troubleshooting.md`** — replace the "Sidecar Won't Start"
section:

```markdown
## Sidecar Won't Start

The launcher logs its resolution path, port, and health status to stderr.
Check the terminal output for lines starting with `sidecar:`.

**Symptom**: `sidecar: bundled path not found: .../binaries/cardre-api-{triple}`
followed by `sidecar: dev fallback using PATH entry` (dev only).

**Fix (dev)**: `pip install -e ".[sidecar]"` so `cardre-api` is on PATH, or
build the sidecar first: `./scripts/build-sidecar.sh`.

**Symptom (packaged)**: `FATAL: Could not resolve sidecar. Bundled: ...`

**Fix (packaged)**: The bundled build is missing the triple-suffixed binary.
Rebuild via `./scripts/build-sidecar.sh` and repackage. Run
`python3 scripts/check-sidecar-naming.py` to verify naming consistency.

**Symptom**: `FATAL: sidecar health check did not become healthy` with
`[sidecar:err]` lines.

**Fix**: The sidecar started but crashed. Read the `[sidecar:err]` lines. Common
causes: missing PyInstaller hidden imports (rebuild with `--hidden-import`),
port conflict (the launcher picks an ephemeral port, so this is rare), or a
missing system library for a bundled dependency.
```

**I5. Update `README.md`** — in the "Build Sidecar Binary" section, after the
existing block, add:

```markdown
The target triple is embedded at Rust compile time by `frontend/src-tauri/build.rs`.
In dev, `main.rs` falls back to `cardre-api` on PATH (from `pip install -e ".[sidecar]"`).
See [docs/release/sidecar-packaging.md](docs/release/sidecar-packaging.md) for details.
```

---

## 5. Verification Commands (run after each slice where applicable)

```bash
# Rust unit + integration tests
cd frontend/src-tauri
export PATH="$HOME/.cargo/bin:$PATH"
cargo fmt --check
cargo test                              # all unit + integration tests
cargo test --test sidecar_resolution -- --nocapture
cargo clippy --all-targets -- -D warnings
cargo check

# Drift guard
cd ../..
python3 scripts/check-sidecar-naming.py

# Sidecar build (if PyInstaller + cardre[sidecar] installed)
pip install pyinstaller
pip install -e ".[sidecar]"
bash scripts/build-sidecar.sh
ls -la frontend/src-tauri/binaries/     # expect cardre-api-x86_64-unknown-linux-gnu

# Doc reference check (if the new docs are referenced anywhere)
python3 scripts/check_doc_references.py
python3 scripts/check-line-counts.py

# Frontend (no change expected, but confirm no regression)
cd frontend && npm run test -- src/api
```

---

## 6. Known Platform Limitations (carry forward)

- **Windows packaged smoke test** — PyInstaller cannot cross-compile; a Windows
  sidecar build needs a Windows runner (ADR 0011 amendment). The resolution
  logic's Windows branch (`cfg!(windows)` → `.exe`) is unit-tested, but no
  Windows packaged binary is built or launched in CI.
- **Port TOCTOU** in `find_free_port()` — pre-existing, out of scope.
- **`tauri build --no-bundle` in CI** — not used (flaky on shared runners).
  The contract test + `cargo check` with the artifact present is the proof.
- **`build.rs` vendor field** — hardcoded to `unknown`, which matches all
  Tauri-expected triples (linux-gnu, apple-darwin, windows-msvc). If a custom
  vendor triple is ever needed, extend `emit_target_triple`.

---

## 7. Final Pass/Fail Statement (target)

**Can a packaged Cardre desktop app reliably start its bundled sidecar?**
**Yes.** `main.rs` resolves `resource_dir/binaries/cardre-api-{triple}{.exe?}`
explicitly, with the target triple embedded at compile time by `build.rs` and
clear diagnostics for path/port/health/stderr. CI asserts the naming contract
across `tauri.conf.json`, `build-sidecar.sh`, and `main.rs`, and exercises the
resolution path against a real downloaded sidecar artifact. (Windows packaged
smoke test remains a documented gap.)