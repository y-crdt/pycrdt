from __future__ import annotations

from enum import IntEnum

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ._base import Sequence


class Assoc(IntEnum):
    AFTER = 0
    BEFORE = -1


class StickyIndex:
    def __init__(self, sequence: Sequence, index: int, assoc: Assoc) -> None:
        self._sequence = sequence
        self._assoc = assoc
        with sequence.doc.transaction() as txn:
            self._sticky_index = sequence.integrated.sticky_index(txn._txn, index, assoc)

    @property
    def index(self) -> int:
        with self._sequence.doc.transaction() as txn:
            return self._sticky_index.get_index(txn._txn)

    @property
    def assoc(self) -> Assoc:
        return self._assoc
