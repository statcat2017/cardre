"""Single source of truth for the Cardre project version (#219).

Every exposed version string — package metadata, API app, health
response, manifest writer, project metadata — must read from here.
"""

__version__ = "0.2.0"

__all__ = ["__version__"]
