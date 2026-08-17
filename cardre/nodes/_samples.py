"""Sample-role helpers — collecting the train/test/oot bundle.

The scorecard build/validate stream distinguishes three sample roles: the
``train`` split (fit), and the ``test`` / ``oot`` holdout splits (apply).
Several validate nodes iterate "all sample roles" and previously re-assembled
the same ``by_role("train") + by_role("test") + by_role("oot")`` concatenation
inline. ``sample_bundle`` is that collection's single home.
"""

from __future__ import annotations

from typing import Any

from cardre.nodes.contracts import InputCollection

SAMPLE_ROLES: tuple[str, ...] = ("train", "test", "oot")


def sample_bundle(inputs: InputCollection) -> list[Any]:
    """Return all sample-role artifacts (``train``, ``test``, ``oot``), in order.

    The sample-role set and ordering are a domain fact about the two-stream
    model (see CONTEXT.md): nodes that process every sample role cross the
    ``InputCollection`` seam through this helper so the set is defined once.
    """
    artifacts: list[Any] = []
    for role in SAMPLE_ROLES:
        artifacts.extend(inputs.by_role(role))
    return artifacts


__all__ = ["SAMPLE_ROLES", "sample_bundle"]
