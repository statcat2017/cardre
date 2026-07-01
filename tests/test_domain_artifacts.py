"""Phase 1 — domain artifacts: hash determinism, canonical form."""

import hashlib
from pathlib import Path

from cardre.domain.artifacts import (
    ArtifactRef,
    json_logical_hash,
    params_hash,
    physical_hash,
)


def test_json_logical_hash_determinism():
    """Same data always produces the same hash."""
    data = {"a": 1, "b": [1, 2, 3], "c": {"nested": "value"}}
    h1 = json_logical_hash(data)
    h2 = json_logical_hash(data)
    assert h1 == h2


def test_json_logical_hash_key_order_independent():
    """Hashes are independent of Python dict key order."""
    data1 = {"a": 1, "b": 2}
    data2 = {"b": 2, "a": 1}
    assert json_logical_hash(data1) == json_logical_hash(data2)


def test_params_hash_is_json_logical_hash():
    """params_hash is a shortcut for json_logical_hash."""
    params = {"learning_rate": 0.1, "max_depth": 5}
    assert params_hash(params) == json_logical_hash(params)


def test_physical_hash(tmp_path: Path):
    """physical_hash produces a consistent SHA-256 for file content."""
    content = b"hello world"
    f = tmp_path / "test.bin"
    f.write_bytes(content)
    expected = hashlib.sha256(content).hexdigest()
    assert physical_hash(f) == expected


def test_physical_hash_large_file(tmp_path: Path):
    """physical_hash works for files larger than the chunk size."""
    content = b"x" * (1024 * 1024 + 1)  # 1 MiB + 1 byte
    f = tmp_path / "large.bin"
    f.write_bytes(content)
    expected = hashlib.sha256(content).hexdigest()
    assert physical_hash(f) == expected


def test_artifact_ref_to_dict_roundtrip():
    """ArtifactRef.to_dict() -> from_dict() preserves all fields."""
    ref = ArtifactRef(
        artifact_id="a1",
        artifact_type="dataset",
        role="train",
        path="datasets/data.parquet",
        physical_hash="abc123",
        logical_hash="def456",
        media_type="application/octet-stream",
        created_at="2025-01-01T00:00:00",
        metadata={"source": "test"},
    )
    d = ref.to_dict()
    restored = ArtifactRef.from_dict(d)
    assert restored == ref


def test_artifact_ref_from_dict_defaults():
    """from_dict handles missing optional fields gracefully."""
    data = {
        "artifact_id": "a1",
        "artifact_type": "dataset",
        "role": "train",
        "path": "datasets/data.parquet",
        "physical_hash": "abc",
        "logical_hash": "def",
    }
    ref = ArtifactRef.from_dict(data)
    assert ref.media_type == "application/octet-stream"
    assert ref.created_at == ""
    assert ref.metadata == {}
