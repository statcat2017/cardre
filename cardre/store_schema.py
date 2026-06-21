"""Backward-compatibility shim for the renamed store schema module.

Previously lived at ``cardre/store_schema.py``; now at
``cardre/store/schema.py``.
"""

from cardre.store.schema import BRANCH_TABLES_SQL, SCHEMA_SQL

__all__ = ["SCHEMA_SQL", "BRANCH_TABLES_SQL"]
