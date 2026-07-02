#!/usr/bin/env bash
set -euo pipefail

# Build the Cardre API sidecar binary for Tauri desktop bundling.
# Output: frontend/src-tauri/binaries/cardre-api-{target-triple}
#
# Usage:
#   ./scripts/build-sidecar.sh          # auto-detect target triple
#   ./scripts/build-sidecar.sh x86_64-unknown-linux-gnu   # explicit target
#
# Prerequisites:
#   pip install pyinstaller
#   pip install cardre[sidecar]

TARGET="${1:-$(rustc -vV | grep host | awk '{print $2}')}"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

echo "Building cardre-api sidecar for target: $TARGET"

cd "$REPO_DIR"

pyinstaller --onefile \
  --name cardre-api \
  --paths "$REPO_DIR" \
  --distpath frontend/src-tauri/binaries \
  --hidden-import cardre.api.app \
  sidecar/__main__.py

# PyInstaller outputs to distpath as cardre-api; Tauri expects
# cardre-api-{target-triple}
if [ -f "frontend/src-tauri/binaries/cardre-api" ]; then
  mv "frontend/src-tauri/binaries/cardre-api" \
     "frontend/src-tauri/binaries/cardre-api-${TARGET}"
  echo "Sidecar binary: frontend/src-tauri/binaries/cardre-api-${TARGET}"
else
  echo "ERROR: PyInstaller did not produce a cardre-api binary"
  exit 1
fi

# Guard: the binary MUST be triple-suffixed for Tauri externalBin to find it.
# On Windows the suffix is .exe; on Linux/macOS there is no extension.
if [ -f "frontend/src-tauri/binaries/cardre-api-${TARGET}" ]; then
  echo "Verified: frontend/src-tauri/binaries/cardre-api-${TARGET}"
elif [ -f "frontend/src-tauri/binaries/cardre-api-${TARGET}.exe" ]; then
  echo "Verified: frontend/src-tauri/binaries/cardre-api-${TARGET}.exe"
else
  echo "ERROR: expected frontend/src-tauri/binaries/cardre-api-${TARGET} after rename"
  ls -la frontend/src-tauri/binaries/
  exit 1
fi
