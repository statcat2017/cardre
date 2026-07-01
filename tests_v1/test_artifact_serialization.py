from __future__ import annotations

import json

from tests.helpers import _make_json_artifact, make_store


def test_json_artifact_serialization_is_predictable():
    store, _ = make_store()
    artifact = _make_json_artifact(store, {"schema_version": "cardre.example.v1", "value": 1}, stem="artifact-serialization")
    payload = json.loads(store.artifact_path(artifact).read_text())  # cardre-allow-artifact-read: serialization-compatibility-test
    assert payload == {"schema_version": "cardre.example.v1", "value": 1}
