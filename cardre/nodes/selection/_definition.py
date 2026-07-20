from __future__ import annotations

from dataclasses import asdict
from typing import Any, Literal

from cardre._evidence.kinds import EvidenceKind
from cardre._evidence.reader import ArtifactEvidenceReader


def typed_definition_payload(value: Any | None) -> dict[str, Any]:
    if value is None:
        return {}
    if hasattr(value, "to_dict"):
        payload = value.to_dict()
        if isinstance(payload, dict):
            return dict(payload)
    if hasattr(value, "__dataclass_fields__"):
        return asdict(value)
    return {}


def merge_selection_definition(
    reader: ArtifactEvidenceReader,
    definition_artifact_id: str | None,
    *,
    key: Literal["selection_filter", "selection_embedded"],
    selection: dict[str, Any],
) -> dict[str, Any]:
    if definition_artifact_id is None:
        return selection

    existing_typed = (
        reader.read_optional(definition_artifact_id, EvidenceKind.FEATURE_SELECTION_EVIDENCE)
        or reader.read_optional(definition_artifact_id, EvidenceKind.MODELLING_METADATA)
        or reader.read_optional(definition_artifact_id, EvidenceKind.SELECTION_DEFINITION)
    )
    existing = typed_definition_payload(existing_typed)
    existing["selected"] = [entry["variable"] for entry in selection["selected"]]
    existing[key] = selection
    existing["selected_count"] = selection["selected_count"]
    existing["rejected_count"] = selection["rejected_count"]
    return existing
