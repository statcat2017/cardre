# Troubleshooting Guide

## Sidecar Won't Start

**Symptom**: `cardre-api` command not found.

**Fix**: Ensure the sidecar is installed:
```bash
pip install -e ".[sidecar]"
```

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
pip install -e ".[sidecar,test]"
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
