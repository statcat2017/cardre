"""Engine capability detection for optbinning availability."""
from typing import Any


def get_binning_capabilities() -> dict[str, Any]:
    try:
        import optbinning

        return {
            "optimal_binning": {
                "available": True,
                "engine": "optbinning",
                "version": optbinning.__version__,
                "target_types": ["binary"],
                "variable_types": ["numerical", "categorical"],
            }
        }
    except ImportError:
        return {
            "optimal_binning": {
                "available": False,
                "reason": "optbinning package not installed. Install with: pip install cardre[optimal-binning]",
            }
        }
    except Exception as exc:
        return {
            "optimal_binning": {
                "available": False,
                "reason": str(exc),
            }
        }
