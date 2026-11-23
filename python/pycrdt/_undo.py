from __future__ import annotations

from operator import index
from time import time_ns
from typing import Any, Callable

from ._base import BaseType
from ._pycrdt import (
    StackItem,
)
from ._pycrdt import (
    UndoManager as _UndoManager,
)
from ._transaction import _callback_exceptions, hash_origin


def timestamp() -> int:
    return time_ns() // 1_000_000


class UndoManager:
    """
    The undo manager allows to perform undo/redo operations on shared types.
    Scopes are a list of shared types integrated in a document.
    Changes can be undone/redone by batches using time intervals.
    It is possible to include/exclude changes by transaction origin in undo/redo operations.
    """

    def __init__(
        self,
        *,
        scopes: list[BaseType] | None = None,
        capture_timeout_millis: int = 500,
        timestamp: Callable[[], int] = timestamp,
        undo_stack: list[StackItem] | None = None,
        redo_stack: list[StackItem] | None = None,
    ) -> None:
        """
        Args:
            scopes: A list of shared types the undo manager will work with.
            capture_timeout_millis: A time interval for grouping changes that will be undone/redone.
            timestamp: A function that returns a timestamp in milliseconds as an unsigned
                64-bit integer. Callback errors are collected and raised after the transaction.
                On failure, the last successful timestamp (initially zero) is used.
            undo_stack: Pre-filled undo stack items.
            redo_stack: Pre-filled redo stack items.

        Raises:
            RuntimeError: A transaction is in progress on the document of a scope.
        """
        self._exceptions: list[BaseException] = []
        exceptions = self._exceptions
        last_timestamp = 0

        def timestamp_callback() -> int:
            nonlocal last_timestamp
            try:
                value = index(timestamp())
                if not 0 <= value < 2**64:
                    raise OverflowError("Timestamp must fit in an unsigned 64-bit integer")
            except BaseException as exc:
                _callback_exceptions.get(exceptions).append(exc)
            else:
                last_timestamp = value
            return last_timestamp

        self._undo_manager = _UndoManager(
            capture_timeout_millis,
            timestamp_callback,
            undo_stack or [],
            redo_stack or [],
        )
        if scopes:
            for scope in scopes:
                self.expand_scope(scope)

    @property
    def origin(self) -> int:
        """The transaction origin used by this manager for undo and redo operations.

        Compare with a transaction's origin to identify changes made by this manager.
        """
        return self._undo_manager.origin()

    def expand_scope(self, scope: BaseType) -> None:
        """
        Expands the scope of shared types for this undo manager.

        Args:
            scope: The shared type to include.

        Raises:
            RuntimeError: A transaction is in progress on the document of the shared type,
                which is not tracked yet by this undo manager.
        """
        method = getattr(self._undo_manager, f"expand_scope_{scope.type_name}")
        method(scope.doc._doc, scope._integrated)

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

        Raises:
            RuntimeError: A transaction is in progress on a tracked document.
            BaseExceptionGroup: Timestamp callback errors, raised as an ExceptionGroup
                when all errors are Exceptions.

        Returns:
            True if some changes were undone.
        """
        token = _callback_exceptions.set(self._exceptions)
        try:
            result = self._undo_manager.undo()
        finally:
            _callback_exceptions.reset(token)
        self._raise_exceptions()
        return result

    def can_redo(self) -> bool:
        """
        Returns:
            True if there are changes to redo.
        """
        return self._undo_manager.can_redo()

    def redo(self) -> bool:
        """
        Perform a redo operation.

        Raises:
            RuntimeError: A transaction is in progress on a tracked document.
            BaseExceptionGroup: Timestamp callback errors, raised as an ExceptionGroup
                when all errors are Exceptions.

        Returns:
            True if some changes were redone.
        """
        token = _callback_exceptions.set(self._exceptions)
        try:
            result = self._undo_manager.redo()
        finally:
            _callback_exceptions.reset(token)
        self._raise_exceptions()
        return result

    def _raise_exceptions(self) -> None:
        if self._exceptions:
            exceptions = tuple(self._exceptions)
            self._exceptions.clear()
            raise BaseExceptionGroup("Timestamp callback error", exceptions)

    def clear(self) -> None:
        """
        Clears all [StackItem][pycrdt.StackItem]s stored in this undo manager,
        effectively resetting its state.

        Raises:
            RuntimeError: A transaction is in progress on a tracked document.
        """
        self._undo_manager.clear_all()

    def reset(self) -> None:
        """
        Makes the next change a new undo step, instead of merging it with the last one
        when it happens within `capture_timeout_millis`.
        """
        self._undo_manager.reset()

    @property
    def undo_stack(self) -> list[StackItem]:
        """The list of undoable actions."""
        return self._undo_manager.undo_stack()

    @property
    def redo_stack(self) -> list[StackItem]:
        """The list of redoable actions."""
        return self._undo_manager.redo_stack()
