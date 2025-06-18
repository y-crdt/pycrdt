from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from enum import IntEnum
from typing import TYPE_CHECKING

if sys.version_info >= (3, 11):
    from typing import Self
else:  # pragma: no cover
    from typing_extensions import Self

from ._pycrdt import StickyIndex as _StickyIndex
from ._pycrdt import decode_sticky_index, get_sticky_index_from_string

if TYPE_CHECKING:
    from pycrdt import Transaction

    from ._base import Sequence


class Assoc(IntEnum):
    AFTER = 0
    BEFORE = -1


@dataclass
class StickyIndex:
    _sticky_index: _StickyIndex
    _sequence: Sequence | None = None

    def get_offset(self, transaction: Transaction | None = None) -> int:
        if transaction is not None:
            _txn = transaction._txn
            assert _txn is not None
            return self._sticky_index.get_offset(_txn)

        if self._sequence is not None:
            with self._sequence.doc.transaction() as txn:
                _txn = txn._txn
                assert _txn is not None
                return self._sticky_index.get_offset(_txn)

        raise RuntimeError("No transaction available")

    @property
    def assoc(self) -> Assoc:
        return Assoc(self._sticky_index.get_assoc())

    def encode(self) -> bytes:
        return self._sticky_index.encode()

    def to_json(self) -> dict:
        return json.loads(self._sticky_index.to_string())

    @classmethod
    def new(cls, sequence: Sequence, index: int, assoc: Assoc) -> Self:
        with sequence.doc.transaction() as txn:
            self = cls(sequence.integrated.sticky_index(txn._txn, index, assoc), sequence)
            return self

    @classmethod
    def decode(cls, data: bytes, sequence: Sequence | None = None) -> Self:
        self = cls(decode_sticky_index(data), sequence)
        return self

    @classmethod
    def from_json(cls, data: dict, sequence: Sequence | None = None) -> Self:
        self = cls(get_sticky_index_from_string(json.dumps(data)), sequence)
        return self
