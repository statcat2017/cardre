"""ArtifactStore port contract tests (Batch 2A).

Runs the same staging -> publish/finalize -> read/resolve + stable-hash
contract against the real ``FsArtifactStore`` and a minimal in-memory fake
(``MemoryArtifactStore`` in ``tests/ports/_fakes``). The fake mirrors the real
adapter's content-addressed observable behaviour without filesystem I/O.
"""

from __future__ import annotations

import hashlib
import json

import polars as pl
import pytest

from cardre.adapters.filesystem.artifact_store import FsArtifactStore
from cardre.domain.artifacts import json_logical_hash, table_logical_hash
from tests.ports._fakes import MemoryArtifactStore


def _payload() -> dict[str, object]:
    return {"nested": [1, 2, 3], "name": 1}


def _frames() -> list[pl.DataFrame]:
    return [
        pl.DataFrame({"a": [1, 2], "b": ["x", "y"]}),
        pl.DataFrame({"b": ["x", "y"], "a": [1, 2]}),  # same logical content, reordered columns
    ]


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


@pytest.fixture(params=["fs", "memory"])
def store(request, tmp_path):
    """Parametrized fixture returning either the real or fake artifact store."""
    if request.param == "fs":
        return FsArtifactStore(tmp_path / "artifacts")
    return MemoryArtifactStore()


class TestArtifactStoreContract:
    def test_stage_json_publish_roundtrip(self, store):
        staged = store.stage_json("report", "profile", _payload())
        assert staged.staging_path is not None
        assert staged.media_type == "application/json"
        dest = store.publish(staged)
        assert dest == store.resolve_path(staged)
        stored = json.loads(store.read_bytes(staged).decode("utf-8"))
        assert stored == _payload()

    def test_stage_table_publish_roundtrip_preserves_content(self, store):
        for frame in _frames():
            staged = store.stage_table("report", "table_summary", frame)
            assert staged.media_type == "application/vnd.apache.parquet"
            store.publish(staged)
            back = pl.read_parquet(store.read_bytes(staged))
            # Logical hash is content-addressed and stable across column order.
            assert table_logical_hash(back) == staged.logical_hash
            assert back.select(sorted(frame.columns)).equals(frame.select(sorted(frame.columns)))

    def test_stage_bytes_publish_roundtrip(self, store):
        data = b"raw-bytes"
        logical = _sha256(data)
        staged = store.stage_bytes("report", "artifact_kind", data,
                                   media_type="application/octet-stream", logical_hash=logical)
        dest = store.publish(staged)
        assert store.read_bytes(staged) == data
        assert store.resolve_path(staged) == dest

    def test_identical_json_stages_dedup_to_same_identity(self, store):
        a = store.stage_json("report", "profile", _payload())
        b = store.stage_json("report", "profile", _payload())
        assert a.physical_hash == b.physical_hash
        assert a.provisional_artifact_id == b.provisional_artifact_id
        assert a.logical_hash == b.logical_hash == json_logical_hash(_payload())

    def test_finalize_is_idempotent(self, store):
        payload = _payload()
        staged = store.stage_json("report", "profile", payload)
        first = store.finalize(staged)
        second = store.finalize(staged)
        assert first == second
        stored = json.loads(store.read_bytes(staged).decode("utf-8"))
        assert stored == payload

    def test_identical_bytes_share_object_path(self, store):
        a = store.stage_json("report", "profile", _payload())
        b = store.stage_json("report", "profile", _payload())
        store.publish(a)
        store.publish(b)
        assert store.resolve_path(a) == store.resolve_path(b)

    def test_stage_table_logical_hash_stable_across_column_order(self, store):
        a = store.stage_table("report", "t", _frames()[0])
        b = store.stage_table("report", "t", _frames()[1])
        assert a.logical_hash == b.logical_hash

    @pytest.mark.parametrize("method", ["read_bytes"])
    def test_missing_object_raises_file_not_found(self, store, method):
        # A freshly staged artifact is never published, so its object namespace
        # entry is absent. ``read_bytes`` must fail loudly like the real
        # filesystem adapter (FileNotFoundError) rather than degrading silently.
        staged = store.stage_json("report", "profile", _payload())
        with pytest.raises(FileNotFoundError):
            getattr(store, method)(staged)


class TestArtifactStoreMissingStaging:
    def test_publish_without_staging_raises_file_not_found(self, store):
        payload = _payload()
        staged = store.stage_json("report", "profile", payload)
        store.publish(staged)
        with pytest.raises(FileNotFoundError):
            store.publish(staged)

    def test_finalize_is_idempotent_after_object_exists(self, store):
        staged = store.stage_json("report", "profile", _payload())
        store.finalize(staged)
        store.finalize(staged)
