"""Cardre — auditable open-source credit scorecard builder.

Top-level package. Submodules are imported directly
(e.g. ``from cardre.api.app import app``); this module exposes only
the package version to avoid creating a re-export facade that would
risk circular imports across the layered architecture.
"""

from cardre._version import __version__

__all__ = ["__version__"]
