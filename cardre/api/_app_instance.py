"""Module-level FastAPI app singleton for backward compatibility.

Imported by tests and the OpenAPI generator that reference
``cardre.api.app.app``. Built via ``bootstrap.build_app.build_app()``.
"""

from cardre.bootstrap.build_app import build_app

app, _shutdown = build_app()
