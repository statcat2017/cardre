"""Deprecation shim — re-exports from cardre.readiness.limitation_codes.

This file exists for backwards compatibility during the cardre/reporting/
→ cardre/readiness/ migration. New code should import from cardre.readiness
directly. This shim will be removed after all import sites are migrated.
"""

from cardre.readiness.limitation_codes import LimitationCode  # noqa: F401
