from __future__ import annotations

from typing import TYPE_CHECKING, Callable, TypeVar, cast

from anyio.streams.memory import MemoryObjectReceiveStream

E = TypeVar("E")


class UnsubscribableStream(MemoryObjectReceiveStream[E]):
    """A receive stream with an unsubscribe method.

    Unsubscribing stops collecting items while leaving buffered items available
    to receive. Iteration ends once the buffer is drained.
    """

    unsubscribe: Callable[[], None]
    """Stop collecting items. Repeated calls have no effect."""

    if TYPE_CHECKING:

        def clone(self) -> UnsubscribableStream[E]: ...


def _with_unsubscribe(
    stream: MemoryObjectReceiveStream[E], unsubscribe: Callable[[], None]
) -> UnsubscribableStream[E]:
    stream = cast(UnsubscribableStream[E], stream)
    stream.unsubscribe = unsubscribe
    original_clone = stream.clone
    stream.clone = lambda: _with_unsubscribe(original_clone(), unsubscribe)  # type: ignore[method-assign]
    return stream
