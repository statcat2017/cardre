"""Binning engine endpoints — availability, version, and capability detection."""

from __future__ import annotations

from fastapi import APIRouter

from cardre.engine.binning.capabilities import get_binning_capabilities
from sidecar.models import BinningEngineInfo, BinningEnginesResponse

router = APIRouter(prefix="/binning", tags=["binning"])


@router.get("/engines", response_model=BinningEnginesResponse)
def list_binning_engines() -> BinningEnginesResponse:
    """List available binning engines and their capabilities."""
    caps = get_binning_capabilities()
    engines: list[BinningEngineInfo] = []

    if "optimal_binning" in caps:
        ob = caps["optimal_binning"]
        engines.append(BinningEngineInfo(
            id="optbinning",
            label="Optimal binning",
            available=ob.get("available", False),
            version=ob.get("version"),
            target_types=ob.get("target_types", []),
        ))

    # Quantile / fine classing is always available (Polars built-in)
    engines.append(BinningEngineInfo(
        id="quantile",
        label="Quantile binning (fine classing)",
        available=True,
        target_types=["binary"],
    ))

    return BinningEnginesResponse(engines=engines)
