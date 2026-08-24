#!/usr/bin/env python3
"""Generate the TypeScript error-code union from the Python ``ErrorCode`` enum.

Usage:
    python3 scripts/generate-error-codes.py

Emits ``frontend/src/api/errorCodes.ts``. The 8 transport codes
(SIDECAR_UNREACHABLE, REQUEST_TIMEOUT, ...) are client-only and hand-maintained;
every server code is emitted from ``cardre/domain/errors.py`` in declaration
order. Idempotent: running on an already-generated file produces a
byte-identical file.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
TS_PATH = REPO_ROOT / "frontend" / "src" / "api" / "errorCodes.ts"

# Client-only transport codes (hand-maintained, no Python counterpart).
TRANSPORT_CODES = [
    "SIDECAR_UNREACHABLE",
    "REQUEST_TIMEOUT",
    "REQUEST_ABORTED",
    "EMPTY_OK_BODY",
    "EMPTY_ERROR_RESPONSE",
    "MALFORMED_JSON_RESPONSE",
    "HTML_ERROR_RESPONSE",
    "NON_JSON_ERROR_RESPONSE",
]

HEADER = """/**
 * Auto-generated from cardre/domain/errors.py by
 * scripts/generate-error-codes.py — do not edit server codes by hand;
 * transport codes below are client-only.
 */

export const ErrorCodes = {"""

TAIL = """} as const;

export type ErrorCode = (typeof ErrorCodes)[keyof typeof ErrorCodes];

const VALID_CODES: ReadonlySet<string> = new Set(Object.values(ErrorCodes));

export function isErrorCode(value: unknown): value is ErrorCode {
  return typeof value === "string" && VALID_CODES.has(value);
}
"""


def main() -> None:
    sys.path.insert(0, str(REPO_ROOT))

    from cardre.domain.errors import INTERNAL_ERROR_CODES, ErrorCode

    internal_names = {m.name for m in INTERNAL_ERROR_CODES}
    lines = [HEADER]
    for name in TRANSPORT_CODES:
        lines.append(f"  {name}: \"{name}\",")
    for member in ErrorCode:
        if member.name in internal_names:
            continue
        lines.append(f"  {member.name}: \"{member.value}\",")
    lines.append(TAIL.rstrip("\n"))

    TS_PATH.write_text("\n".join(lines) + "\n")
    print(f"Wrote {TS_PATH}")


if __name__ == "__main__":
    main()
