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
    "TAURI_ENV_TARGET_TRIPLE" in main and "env!" in main,
    "must read TAURI_ENV_TARGET_TRIPLE via env!",
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
