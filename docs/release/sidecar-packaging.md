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
embedded at Rust compile time by `tauri-build` (env `TAURI_ENV_TARGET_TRIPLE`)
and read in `main.rs` via `env!`.

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
