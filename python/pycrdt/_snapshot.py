from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from ._pycrdt import Snapshot as _Snapshot

if TYPE_CHECKING:
    from ._doc import Doc


@dataclass
class Snapshot:
    """
    A snapshot of a document's state at a given point in time.
    Can be encoded to bytes for storage or transmission, and decoded back.
    """

    _snapshot: _Snapshot

    @classmethod
    def from_doc(cls, doc: "Doc") -> "Snapshot":
        """
        Create a snapshot from a document.

        Args:
            doc: The document to snapshot.
        Returns:
            The snapshot of the document's current state.
        """
        snap = _Snapshot.from_doc(doc._doc)
        return cls(snap)

    @classmethod
    def decode(cls, data: bytes) -> Snapshot:
        """
        Decode a snapshot from its binary representation.

        Args:
            data: The bytes to decode into a snapshot.
        Returns:
            The decoded snapshot.
        Raises:
            ValueError: If the bytes are not a valid snapshot.
        """
        snap = _Snapshot.decode(data)
        return cls(snap)

    def encode(self) -> bytes:
        """
        Encode the snapshot to its binary representation.

        Returns:
            The bytes representing the snapshot.
        """
        return self._snapshot.encode()
