# Cardre

Cardre is an open-source, auditable credit scorecard builder. A scorecard is not just a final model — it is an input dataset plus a traceable build pathway: profiling, binning, WOE/IV, model fitting, score scaling, validation, and export. Every step is reproducible and explainable.

## Quick Start

```bash
pip install -e ".[sidecar]"
cardre-api &
cd frontend && npm install && npm run dev
```

## Architecture

- **`cardre/`** — pure-Python scorecard engine (no GUI dependency)
- **`sidecar/`** — FastAPI local API server (bundled as sidecar binary)
- **`frontend/`** — React + TypeScript UI (Vite)
- **`frontend/src-tauri/`** — Tauri v2 Rust desktop shell

### Node Tiers

Cardre uses two environment variables to control feature availability:

| Variable | Default | Effect |
|----------|---------|--------|
| `CARDRE_LAUNCH_MODE` | `1` | When enabled, deferred nodes (boosting, ensembles, fairness, etc.) are visible as schemas but not executable. Set to `0` to enable all nodes. |
| `CARDRE_GOVERNANCE` | `0` | When enabled, branch/comparison/champion workflows are available. Set to `1` for enterprise governance features. |

See `docs/launch-mode.md` for details.

### Current State

The engine supports the full scorecard build pathway: import, profiling, binning, WOE/IV, variable selection, logistic regression, score scaling, validation, cutoff analysis, and reporting. ML challenger nodes (decision tree — launch tier; random forest, gradient boosting, XGBoost, LightGBM, CatBoost — deferred tier) are available. Governance features (branching, champion/challenger comparison) are gated behind `CARDRE_GOVERNANCE=1`.

## Documentation

See `docs/README.md` for the full documentation index.

## Development

### Prerequisites

**Python** (3.11+):
```bash
pip install -e .
pip install -e ".[sidecar]"   # for the FastAPI sidecar
```

**Frontend** (Node 20+):
```bash
cd frontend && npm install
```

**Tauri Desktop** (for `npm run tauri dev`):
- Linux: `sudo apt install libwebkit2gtk-4.1-dev libgtk-3-dev libayatana-appindicator3-dev librsvg2-dev`
- macOS: Xcode CLI tools
- Windows: WebView2 (included in Windows 10+)

### Build Sidecar Binary

```bash
pip install pyinstaller
./scripts/build-sidecar.sh
```

Produces `frontend/src-tauri/binaries/cardre-api-{target-triple}` for Tauri bundling.

### Run Tests

```bash
python3 -m pytest tests/ -q
cd frontend && npm test
```

### CI

See `.github/workflows/ci.yml` — runs Python tests, frontend typecheck, and sidecar build on push/PR to `main`.
