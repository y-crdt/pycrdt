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
from ._pycrdt import decode_sticky_index, get_sticky_index_from_json_string

if TYPE_CHECKING:
    from pycrdt import Transaction

    from ._base import Sequence


class Assoc(IntEnum):
    """
    Whether to associate a sticky index with the item on its left (`BEFORE`)
    or on its right (`AFTER`).
    """

    AFTER = 0
    BEFORE = -1


@dataclass
class StickyIndex:
    """
    A permanent position that sticks to the same place even when concurrent updates are made.
    """

    _sticky_index: _StickyIndex
    _sequence: Sequence | None = None

    def get_index(self, transaction: Transaction | None = None) -> int:
        """
        Get the current value of the index.

        Args:
            transaction: A transaction that must be provided when the sticky index
                was deserialized and not associated with a shared type.

        Returns:
            The current index.

        Raises:
            RuntimeError: No transaction was provided and no shared type was associated
                with the deserialized sticky index.
        """
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
        """
        The [Assoc][pycrdt.Assoc] of the sticky index (before or after).
        """
        return Assoc(self._sticky_index.get_assoc())

    def encode(self) -> bytes:
        """
        Encode the sticky index to binary.

        Returns:
            The binary representation of the sticky index.
        """
        return self._sticky_index.encode()

    def to_json(self) -> dict:
        """
        Serialize the sticky index to JSON.

        Returns:
            The JSON representation of the sticky index.
        """
        return json.loads(self._sticky_index.to_json_string())

    @classmethod
    def new(cls, sequence: Sequence, index: int, assoc: Assoc) -> Self:
        """
        Create a sticky index before or after the specified index.

        Args:
            sequence: The [Array][pycrdt.Array] or [Text][pycrdt.Text] to get the sticky index from.
            index: The index at which the sticky index should remain.
            assoc: The [Assoc][pycrdt.Assoc] the sticky index should be associated
                with (before or after).

        Returns:
            The sticky index.
        """
        with sequence.doc.transaction() as txn:
            self = cls(sequence.integrated.sticky_index(txn._txn, index, assoc), sequence)
            return self

    @classmethod
    def decode(cls, data: bytes, sequence: Sequence | None = None) -> Self:
        """
        Create the sticky index from its binary representation.

        Args:
            data: The binary data to get the sticky index from.
            sequence: The [Array][pycrdt.Array] or [Text][pycrdt.Text] the sticky index belongs to.
                If not provided, a [Transaction][pycrdt.Transaction] will be needed when getting
                the index.

        Returns:
            The decoded sticky index.
        """
        self = cls(decode_sticky_index(data), sequence)
        return self

    @classmethod
    def from_json(cls, data: dict, sequence: Sequence | None = None) -> Self:
        """
        Create a sticky index from its JSON representation.

        Args:
            data: The JSON dictionary to get the sticky index from.
            sequence: The [Array][pycrdt.Array] or [Text][pycrdt.Text] the sticky index belongs to.
                If not provided, a [Transaction][pycrdt.Transaction] will be needed when getting
                the index.

        Returns:
            The deserialized sticky index.
        """
        self = cls(get_sticky_index_from_json_string(json.dumps(data)), sequence)
        return self
