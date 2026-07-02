from __future__ import annotations

from hashlib import sha256

from cardre.domain.artifacts import ArtifactRef
from cardre.domain.artifacts import json_logical_hash
from cardre.domain.artifacts import params_hash
from cardre.domain.artifacts import physical_hash
from cardre.domain.artifacts import relative_path


def test_json_logical_hash_is_canonical() -> None:
    left = {"b": 2, "a": 1}
    right = {"a": 1, "b": 2}

    assert json_logical_hash(left) == json_logical_hash(right)
    assert params_hash(left) == json_logical_hash(left)


def test_physical_hash_reads_file_bytes(tmp_path) -> None:
    path = tmp_path / "artifact.bin"
    path.write_bytes(b"abc")

    assert physical_hash(path) == sha256(b"abc").hexdigest()


def test_relative_path_and_artifact_ref_round_trip(tmp_path) -> None:
    root = tmp_path / "root"
    nested = root / "nested"
    nested.mkdir(parents=True)
    path = nested / "file.txt"
    path.write_text("hello")

    ref = ArtifactRef(
        artifact_id="art-1",
        artifact_type="json",
        role="output",
        path=relative_path(path, root),
        physical_hash="phys",
        logical_hash="logic",
        media_type="application/json",
        created_at="2026-01-01T00:00:00+00:00",
        metadata={"x": 1},
    )

    assert ref.path == "nested/file.txt"
    assert ArtifactRef.from_dict(ref.to_dict()) == ref
