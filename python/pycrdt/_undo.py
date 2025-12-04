from __future__ import annotations

from time import time_ns
from typing import TYPE_CHECKING, Any, Callable

from ._base import BaseType
from ._pycrdt import (
    StackItem,
)
from ._pycrdt import (
    UndoManager as _UndoManager,
)
from ._transaction import hash_origin

if TYPE_CHECKING:
    from ._doc import Doc


def timestamp() -> int:
    return time_ns() // 1_000_000


class UndoManager:
    """
    The undo manager allows to perform undo/redo operations on shared types.
    It can be initialized either with a [Doc][pycrdt.Doc] or with scopes.
    Scopes are a list of shared types integrated in a document.
    If initialized with a `Doc`, scopes can later be expanded.
    Changes can be undone/redone by batches using time intervals.
    It is possible to include/exclude changes by transaction origin in undo/redo operations.
    """

    def __init__(
        self,
        *,
        doc: Doc | None = None,
        scopes: list[BaseType] = [],
        capture_timeout_millis: int = 500,
        timestamp: Callable[[], int] = timestamp,
        undo_stack: list[StackItem] | None = None,
        redo_stack: list[StackItem] | None = None,
    ) -> None:
        """
        Args:
            doc: The document the undo manager will work with.
            scopes: A list of shared types the undo manager will work with.
            capture_timeout_millis: A time interval for grouping changes that will be undone/redone.
            timestamp: A function that returns a timestamp as an integer number of milli-seconds.
            undo_stack: Pre-filled undo stack items.
            redo_stack: Pre-filled redo stack items.

        Raises:
            RuntimeError: UndoManager must be created with doc or scopes.
        """
        if doc is None:
            if not scopes:
                raise RuntimeError("UndoManager must be created with doc or scopes")
            doc = scopes[0].doc
        elif scopes:
            raise RuntimeError("UndoManager must be created with doc or scopes")
        self._undo_manager = _UndoManager(
            doc._doc,
            capture_timeout_millis,
            timestamp,
            undo_stack or [],
            redo_stack or [],
        )
        for scope in scopes:
            self.expand_scope(scope)

    def expand_scope(self, scope: BaseType) -> None:
        """
        Expands the scope of shared types for this undo manager.

        Args:
            scope: The shared type to include.
        """
        method = getattr(self._undo_manager, f"expand_scope_{scope.type_name}")
        method(scope._integrated)

    def include_origin(self, origin: Any) -> None:
        """
        Extends the list of transactions origin tracked by this undo manager.

        Args:
            origin: The origin to include.
        """
        self._undo_manager.include_origin(hash_origin(origin))

    def exclude_origin(self, origin: Any) -> None:
        """
        Removes a transaction origin from the list of origins tracked by this undo manager.

        Args:
            origin: The origin to exclude.
        """
        self._undo_manager.exclude_origin(hash_origin(origin))

    def can_undo(self) -> bool:
        """
        Returns:
            True if there are changes to undo.
        """
        return self._undo_manager.can_undo()

    def undo(self) -> bool:
        """
        Perform an undo operation.

        Returns:
            True if some changes were undone.
        """
        return self._undo_manager.undo()

    def can_redo(self) -> bool:
        """
        Returns:
            True if there are changes to redo.
        """
        return self._undo_manager.can_redo()

    def redo(self) -> bool:
        """
        Perform a redo operation.

        Returns:
            True if some changes were redone.
        """
        return self._undo_manager.redo()

    def clear(self) -> None:
        """
        Clears all [StackItem][pycrdt.StackItem]s stored in this undo manager,
        effectively resetting its state.
        """
        self._undo_manager.clear()

    @property
    def undo_stack(self) -> list[StackItem]:
        """The list of undoable actions."""
        return self._undo_manager.undo_stack()

    @property
    def redo_stack(self) -> list[StackItem]:
        """The list of redoable actions."""
        return self._undo_manager.redo_stack()
