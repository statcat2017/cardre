#!/usr/bin/env python3
"""Generate TypeScript types from the FastAPI OpenAPI schema.

Usage:
    python3 scripts/generate-openapi-types.py
"""

import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


def main() -> None:
    import os
    os.environ["CARDRE_GOVERNANCE"] = "1"

    sys.path.insert(0, str(REPO_ROOT))

    try:
        from cardre.api.app import app
    except ImportError as exc:
        print(f"Cannot import cardre.api.app: {exc}")
        print("Install sidecar deps: pip install -e '.[sidecar]'")
        sys.exit(1)

    openapi_spec = app.openapi()

    api_dir = REPO_ROOT / "frontend" / "src" / "api"
    api_dir.mkdir(parents=True, exist_ok=True)

    openapi_path = api_dir / "openapi.json"
    openapi_path.write_text(json.dumps(openapi_spec, indent=2))
    print(f"Wrote OpenAPI spec to {openapi_path}")

    schema_path = api_dir / "schema.d.ts"
    cmd = [
        "npx",
        "openapi-typescript",
        str(openapi_path),
        "-o",
        str(schema_path),
    ]
    result = subprocess.run(
        cmd,
        cwd=str(REPO_ROOT / "frontend"),
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        print(f"Error generating TypeScript types:\n{result.stderr}")
        sys.exit(1)

    print(f"Generated types at {schema_path}")
    if result.stdout:
        print(result.stdout)


if __name__ == "__main__":
    main()
