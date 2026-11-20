from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from functools import partial
from typing import TypeVar, TypeVarTuple, Unpack

from anyio import (
    BrokenResourceError,
    CancelScope,
    CapacityLimiter,
    ClosedResourceError,
    create_memory_object_stream,
    from_thread,
    to_thread,
)
from anyio.streams.memory import MemoryObjectReceiveStream

from ._base import BaseType
from ._doc import Doc
from ._pycrdt import TransactionEvent

R = TypeVar("R")
Args = TypeVarTuple("Args")


class AsyncDoc:
    """A document accessed asynchronously through serialized worker calls.

    Create instances with :meth:`create`. Operations may run on different worker
    threads, but only one operation per instance runs at a time. Use the instance
    within one event loop. Shared types and the underlying document must only be
    accessed inside synchronous callbacks passed to :meth:`run_sync`.
    """

    def __init__(self, doc: Doc) -> None:
        """Take exclusive ownership of an existing synchronous document.

        The document and its shared types must no longer be used directly.
        Prefer :meth:`create` to initialize a new document in a worker.
        """
        self._limiter = CapacityLimiter(1)
        self._doc = doc

    @classmethod
    async def create(
        cls,
        init: dict[str, BaseType] | None = None,
        *,
        client_id: int | None = None,
        skip_gc: bool | None = None,
        guid: str | None = None,
    ) -> AsyncDoc:
        """Create a document and initialize its root types in a worker thread.

        Arguments have the same meaning as for :class:`Doc`. Initial shared types
        become owned by this instance and must subsequently be accessed through
        :meth:`run_sync`.
        """
        doc = await to_thread.run_sync(
            partial(Doc, init or {}, client_id=client_id, skip_gc=skip_gc, guid=guid),
        )
        return cls(doc)

    async def run_sync(self, callback: Callable[[Doc, Unpack[Args]], R], *args: Unpack[Args]) -> R:
        """Call ``callback(doc, *args)`` in a worker and return its result.

        The callback must be synchronous. Return plain data rather than documents,
        shared types, transactions, or borrowed events. Group edits in a regular
        ``with doc.transaction():`` block inside the callback. A callback exception
        propagates to the caller; as with synchronous transactions, edits are not
        rolled back. Once started, a callback finishes before cancellation takes
        effect, keeping subsequent operations serialized.
        """
        return await to_thread.run_sync(callback, self._doc, *args, limiter=self._limiter)

    async def get_state(self) -> bytes:
        """Return the document's state vector."""
        return await self.run_sync(Doc.get_state)

    async def get_update(self, state: bytes | None = None) -> bytes:
        """Return the update since ``state``, or the complete document update."""
        return await self.run_sync(Doc.get_update, state)

    async def apply_update(self, update: bytes) -> None:
        """Apply a binary update in a worker thread."""
        await self.run_sync(Doc.apply_update, update)

    @asynccontextmanager
    async def updates(self) -> AsyncIterator[MemoryObjectReceiveStream[bytes]]:
        """Subscribe to binary updates using an async context manager.

        Updates are copied during the observer callback and delivered on the event
        loop, so no borrowed events cross threads. The buffer is unbounded: slow
        consumers accumulate updates without blocking document operations. Context
        exit unsubscribes and closes the stream, including under cancellation.
        """
        send, receive = create_memory_object_stream[bytes](float("inf"))

        def deliver(update: bytes) -> None:
            try:
                send.send_nowait(update)
            except (BrokenResourceError, ClosedResourceError):
                pass

        def observe(event: TransactionEvent) -> None:
            from_thread.run_sync(deliver, event.update)

        subscription = None
        try:
            # Shield subscription creation so cancellation cannot lose its handle.
            with CancelScope(shield=True):
                subscription = await self.run_sync(Doc.observe, observe)
            yield receive
        finally:
            with CancelScope(shield=True):
                try:
                    if subscription is not None:
                        await self.run_sync(Doc.unobserve, subscription)
                finally:
                    send.close()
                    receive.close()
