"""Shared evidence-reading helpers for nodes.

The IV-table → dict loop was copy-pasted across selection, clustering and
features.  ``load_iv_map`` is the single implementation.
"""

from __future__ import annotations

from cardre.domain.evidence.kinds import EvidenceKind
from cardre.nodes.contracts import InputCollection


def load_iv_map(inputs: InputCollection, *, required: bool = True) -> dict[str, float]:
    """Load the IV table as ``{variable: iv}``.

    With ``required=True`` a missing IV table raises; with ``required=False``
    a missing or unreadable table yields ``{}`` (clustering previews).
    """
    iv_map: dict[str, float] = {}
    try:
        iv_list = inputs.by_kind(EvidenceKind.IV_TABLE)
        iv_table = iv_list[0] if iv_list else None
    except (KeyError, TypeError):
        iv_table = None
    if iv_table is None:
        if required:
            raise ValueError("No IV table found")
        return {}
    try:
        iv_df = iv_table.dataframe.collect()
        for row in iv_df.iter_rows():
            iv_map[str(row[0])] = float(row[1])
    except (KeyError, TypeError):
        if required:
            raise
        iv_map = {}
    return iv_map
