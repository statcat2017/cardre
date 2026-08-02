"""UUID-based ID generator — concrete IdGeneratorPort."""

from __future__ import annotations

import uuid


class UuidGenerator:
    """Concrete IdGeneratorPort that delegates to ``uuid.uuid4``."""

    def new_id(self) -> str:
        return str(uuid.uuid4())
