# Troubleshooting Guide

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

**Symptom**: Port 8752 already in use.

**Fix**: Kill the existing process or change the port:
```bash
kill $(lsof -t -i:8752)
```

## Frontend Won't Build

**Symptom**: `npm install` fails.

**Fix**: Ensure Node.js 20+ is installed:
```bash
node --version
```

**Symptom**: TypeScript compilation errors.

**Fix**: Regenerate OpenAPI types:
```bash
python3 scripts/generate-openapi-types.py
```

## Tauri Build Fails

**Symptom**: `npm run tauri dev` fails with WebKit errors (Linux).

**Fix**: Install required system libraries:
```bash
sudo apt install libwebkit2gtk-4.1-dev libgtk-3-dev libayatana-appindicator3-dev librsvg2-dev
```

## Tests Fail

**Symptom**: Python tests fail with import errors.

**Fix**: Ensure the package is installed in editable mode:
```bash
pip install -e ".[sidecar,dev,test]"
```

**Symptom**: Frontend tests fail.

**Fix**: Ensure dependencies are installed:
```bash
cd frontend && npm install
```

## Database Issues

**Symptom**: Schema migration errors.

**Fix**: Delete the project directory and recreate the project. The project directory contains the SQLite database and all artifacts.

## Node Not Available

**Symptom**: `NodeNotAvailableForLaunch` error.

**Fix**: Set `CARDRE_LAUNCH_MODE=0` to enable deferred nodes:
```bash
CARDRE_LAUNCH_MODE=0 cardre-api
```

## Governance Features Not Available

**Symptom**: Branch endpoints return 403.

**Fix**: Set `CARDRE_GOVERNANCE=1` to enable governance features:
```bash
CARDRE_GOVERNANCE=1 cardre-api
```
