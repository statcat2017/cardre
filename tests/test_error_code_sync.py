"""Test that errorCodes.ts mirrors cardre/api/errors.py.

The TypeScript file is a hand-written second source. This test asserts
that every server-side error code in errorCodes.ts exists in the Python
canonical set, so drift is caught in CI.
"""

from __future__ import annotations

import re
from pathlib import Path

from cardre.api.errors import ErrorCode


def _parse_ts_server_codes() -> set[str]:
    """Extract server-side error code strings from errorCodes.ts.

    Transport-only codes (SIDECAR_UNREACHABLE, REQUEST_TIMEOUT, etc.)
    are excluded — they are client-side only and have no Python counterpart.
    """
    ts_path = Path(__file__).parents[1] / "frontend" / "src" / "api" / "errorCodes.ts"
    text = ts_path.read_text()
    transport_codes = {
        "SIDECAR_UNREACHABLE",
        "REQUEST_TIMEOUT",
        "REQUEST_ABORTED",
        "EMPTY_OK_BODY",
        "EMPTY_ERROR_RESPONSE",
        "MALFORMED_JSON_RESPONSE",
        "HTML_ERROR_RESPONSE",
        "NON_JSON_ERROR_RESPONSE",
    }
    codes: set[str] = set()
    for m in re.finditer(r'(\w+):\s*"(\w+)"', text):
        name, value = m.group(1), m.group(2)
        if name not in transport_codes and name != "ErrorCodes":
            codes.add(value)
    return codes


class TestErrorCodeSync:
    def test_ts_server_codes_are_subset_of_python(self):
        ts_codes = _parse_ts_server_codes()
        py_codes = {e.value for e in ErrorCode}
        extra = ts_codes - py_codes
        assert not extra, (
            f"errorCodes.ts has server codes not in cardre/api/errors.py: "
            f"{sorted(extra)}. Add them to ErrorCode in errors.py or remove "
            f"them from errorCodes.ts."
        )

    def test_python_codes_have_ts_counterpart(self):
        ts_codes = _parse_ts_server_codes()
        py_codes = {e.value for e in ErrorCode}
        missing = py_codes - ts_codes
        assert not missing, (
            f"cardre/api/errors.py has codes not in errorCodes.ts: "
            f"{sorted(missing)}. Add them to errorCodes.ts."
        )
