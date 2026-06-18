"""Binning engine adapters.

Cardre's binning pipeline uses SCHEMA_BIN_DEFINITION as the universal
interface. Engines produce bin definitions conforming to this schema.
"""
from cardre.engine.binning.capabilities import get_binning_capabilities

__all__ = ["get_binning_capabilities"]
