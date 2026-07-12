from __future__ import annotations

from hashlib import sha256

import polars as pl
import pytest

from cardre.domain.artifacts import (
    TABLE_LOGICAL_HASH_VERSION,
    ArtifactRef,
    json_logical_hash,
    params_hash,
    physical_hash,
    relative_path,
    table_logical_hash,
)


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


# ---------------------------------------------------------------------------
# table_logical_hash regression fixtures
# ---------------------------------------------------------------------------

_TABLE_LOGICAL_HASH_FIXTURES: dict[str, pl.DataFrame] = {
    "basic_ints_strings": pl.DataFrame({
        "age": [25, 40, 65],
        "name": ["alice", "bob", "carol"],
    }),
    "with_nulls": pl.DataFrame({
        "a": [1, None, 3],
        "b": [None, "y", None],
    }),
    "with_booleans": pl.DataFrame({
        "flag": [True, False, True],
        "val": [10, 20, 30],
    }),
    "float_columns": pl.DataFrame({
        "x": [1.5, 2.5, None],
        "y": [3.14, None, 2.71],
    }),
    "categoricals": pl.DataFrame({
        "cat": pl.Series(["low", "medium", "high"]).cast(pl.Categorical),
        "score": [1, 2, 3],
    }),
    "datetime_columns": pl.DataFrame({
        "ts": [
            "2024-01-01T00:00:00",
            "2024-06-15T12:30:00",
            "2024-12-31T23:59:59",
        ],
        "id": [1, 2, 3],
    }).with_columns(pl.col("ts").str.to_datetime()),
}


@pytest.mark.parametrize(
    "fixture_name",
    list(_TABLE_LOGICAL_HASH_FIXTURES.keys()),
    ids=list(_TABLE_LOGICAL_HASH_FIXTURES.keys()),
)
def test_table_logical_hash_deterministic(fixture_name: str) -> None:
    """Hash of the same data is identical across repeated calls."""
    df = _TABLE_LOGICAL_HASH_FIXTURES[fixture_name]
    h1 = table_logical_hash(df)
    h2 = table_logical_hash(df)
    assert h1 == h2


@pytest.mark.parametrize(
    "fixture_name",
    list(_TABLE_LOGICAL_HASH_FIXTURES.keys()),
    ids=list(_TABLE_LOGICAL_HASH_FIXTURES.keys()),
)
def test_table_logical_hash_column_order_independent(fixture_name: str) -> None:
    """Sorting columns internally produces the same hash regardless of input order."""
    df = _TABLE_LOGICAL_HASH_FIXTURES[fixture_name]
    cols = df.columns
    h_original = table_logical_hash(df)
    h_reversed = table_logical_hash(df.select(reversed(cols)))
    assert h_original == h_reversed


def test_table_logical_hash_version_prefix() -> None:
    """Hashes carry the TABLE_LOGICAL_HASH_VERSION prefix."""
    df = pl.DataFrame({"x": [1, 2]})
    h = table_logical_hash(df)
    assert h.startswith(f"{TABLE_LOGICAL_HASH_VERSION}:")


def test_table_logical_hash_different_data_different_hash() -> None:
    """Different data produces a different hash."""
    df_a = pl.DataFrame({"x": [1, 2]})
    df_b = pl.DataFrame({"x": [1, 3]})
    assert table_logical_hash(df_a) != table_logical_hash(df_b)
