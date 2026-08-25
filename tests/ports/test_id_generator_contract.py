"""IdGenerator port contract tests (Batch 2A).

Covers the real ``UuidGenerator`` and a deterministic fake
(``DeterministicIdGenerator`` in ``tests/ports/_fakes``). ``new_id`` must
return nonempty, unique identifiers.
"""

from __future__ import annotations

from cardre.adapters.system.id_generator import UuidGenerator
from tests.ports._fakes import DeterministicIdGenerator


class TestUuidGeneratorContract:
    def test_new_id_is_nonempty(self):
        value = UuidGenerator().new_id()
        assert isinstance(value, str)
        assert len(value) > 0

    def test_new_ids_are_unique(self):
        generator = UuidGenerator()
        ids = {generator.new_id() for _ in range(1000)}
        assert len(ids) == 1000


class TestDeterministicIdGeneratorContract:
    def test_new_id_is_nonempty(self):
        value = DeterministicIdGenerator().new_id()
        assert isinstance(value, str)
        assert len(value) > 0

    def test_new_ids_are_unique(self):
        generator = DeterministicIdGenerator()
        ids = {generator.new_id() for _ in range(100)}
        assert len(ids) == 100

    def test_new_ids_are_deterministic(self):
        a = DeterministicIdGenerator()
        b = DeterministicIdGenerator()
        assert [a.new_id() for _ in range(5)] == [b.new_id() for _ in range(5)]
