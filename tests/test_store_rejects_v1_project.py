from __future__ import annotations

import pytest

from cardre.domain.errors import SchemaVersionError
from cardre.store.db import ProjectStore


def test_open_rejects_v1_schema_family(store) -> None:
    store.execute(
        "UPDATE store_meta SET value = ? WHERE key = 'schema_family'",
        ("cardre-v1",),
    )
    store.close()

    reopened = ProjectStore(store.root)

    with pytest.raises(SchemaVersionError) as excinfo:
        reopened.open()

    assert excinfo.value.code == "STORE_VERSION_INCOMPATIBLE"
    assert "does not match app family" in str(excinfo.value)
