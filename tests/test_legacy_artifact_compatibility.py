from __future__ import annotations

import json

from tests.helpers import _make_json_artifact, make_store


def test_legacy_json_artifact_shape_is_stable():
    store, _ = make_store()
    artifact = _make_json_artifact(store, {"schema_version": "legacy.v1", "foo": "bar"}, stem="legacy-shape")
    payload = json.loads(store.artifact_path(artifact).read_text())  # cardre-allow-artifact-read: serialization-compatibility-test
    assert payload["schema_version"] == "legacy.v1"
    assert payload["foo"] == "bar"
