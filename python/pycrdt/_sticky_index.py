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
            ValueError: The sticky index cannot be resolved, or its resolved owner is not
                the associated shared type.
        """
        if transaction is not None:
            _txn = transaction._txn
            assert _txn is not None
            if self._sequence is None:
                index = self._sticky_index.get_offset(_txn)
            elif self._sequence.is_integrated:
                index = self._sticky_index.resolve(_txn, self._sequence.integrated)
            else:
                index = None
        elif self._sequence is not None:
            index = self.resolve(self._sequence)
        else:
            raise RuntimeError("No transaction available")

        if index is None:
            raise ValueError("Sticky index cannot be resolved")
        return index

    def resolve(self, sequence: Sequence) -> int | None:
        """
        Resolve the current index only if it belongs to an exact shared type.

        Resolution does not mutate the document. A position owned by a sibling shared type,
        a deleted shared type, or data that is not yet available in the document is not resolved.

        Args:
            sequence: The [Array][pycrdt.Array] or [Text][pycrdt.Text] against which to validate
                the resolved owner.

        Returns:
            The current index, or `None` if the position cannot be resolved against `sequence`.
        """
        if not sequence.is_integrated:
            return None

        with sequence.doc.transaction() as txn:
            _txn = txn._txn
            assert _txn is not None
            return self._sticky_index.resolve(_txn, sequence.integrated)

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

        Raises:
            ValueError: The index is outside the sequence.
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
            sequence: The [Array][pycrdt.Array] or [Text][pycrdt.Text] against which the resolved
                owner will be validated. If not provided, a [Transaction][pycrdt.Transaction]
                will be needed when getting the index.

        Returns:
            The decoded sticky index.

        Raises:
            ValueError: The binary data is malformed.
        """
        self = cls(decode_sticky_index(data), sequence)
        return self

    @classmethod
    def from_json(cls, data: dict, sequence: Sequence | None = None) -> Self:
        """
        Create a sticky index from its JSON representation.

        Args:
            data: The JSON dictionary to get the sticky index from.
            sequence: The [Array][pycrdt.Array] or [Text][pycrdt.Text] against which the resolved
                owner will be validated. If not provided, a [Transaction][pycrdt.Transaction]
                will be needed when getting the index.

        Returns:
            The deserialized sticky index.

        Raises:
            ValueError: The JSON data is malformed.
        """
        self = cls(get_sticky_index_from_json_string(json.dumps(data)), sequence)
        return self
