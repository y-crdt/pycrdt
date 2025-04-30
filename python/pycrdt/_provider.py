from __future__ import annotations

from contextlib import AsyncExitStack, asynccontextmanager
from logging import Logger, getLogger
from typing import AsyncIterator, Protocol

from anyio import (
    TASK_STATUS_IGNORED,
    Event,
    Lock,
    create_task_group,
)
from anyio.abc import TaskGroup, TaskStatus

from ._doc import Doc
from ._sync import (
    YMessageType,
    YSyncMessageType,
    create_sync_message,
    create_update_message,
    handle_sync_message,
)


class Channel(Protocol):
    """A transport-agnostic stream used to synchronize a document through a provider.
    An example of a channel is a WebSocket.

    Messages can be received through the channel using an async iterator,
    until the connection is closed:
    ```py
    async for message in channel:
        ...
    ```
    Or directly by calling `recv()`:
    ```py
    message = await channel.recv()
    ```
    Sending messages is done with `send()`:
    ```py
    await channel.send(message)
    ```
    """

    @property
    def path(self) -> str:
        """The channel path."""
        ...  # pragma: nocover

    def __aiter__(self) -> "Channel":
        return self

    async def __anext__(self) -> bytes:
        return await self.recv()

    async def send(self, message: bytes) -> None:
        """Send a message.

        Args:
            message: The message to send.
        """
        ...  # pragma: nocover

    async def recv(self) -> bytes:
        """Receive a message.

        Returns:
            The received message.
        """
        ...  # pragma: nocover


class Provider:
    def __init__(self, doc: Doc, channel: Channel, log: Logger | None = None) -> None:
        """A provider synchronizes a document through a channel.

        The provider should preferably be used with an async context manager:
        ```py
        async with provider:
            ...
        ```
        However, a lower-level API can also be used:
        ```py
        task = asyncio.create_task(provider.start())
        await provider.started.wait()
        ...
        await provider.stop()
        ```

        Arguments:
            doc: The `Doc` to connect through the `Channel`.
            channel: The `Channel` through which to connect the `Doc`.
            log: An optional logger.
        """
        self._doc = doc
        self._channel = channel
        self.log = log or getLogger(__name__)
        self.started = Event()
        self._start_lock = Lock()
        self._task_group: TaskGroup | None = None

    async def _run(self):
        sync_message = create_sync_message(self._doc)
        self.log.debug(
            "Sending %s message to endpoint: %s",
            YSyncMessageType.SYNC_STEP1.name,
            self._channel.path,
        )
        await self._channel.send(sync_message)
        assert self._task_group is not None
        self._task_group.start_soon(self._send_updates)
        async for message in self._channel:
            if message[0] == YMessageType.SYNC:
                self.log.debug(
                    "Received %s message from endpoint: %s",
                    YSyncMessageType(message[1]).name,
                    self._channel.path,
                )
                reply = handle_sync_message(message[1:], self._doc)
                if reply is not None:
                    self.log.debug(
                        "Sending %s message to endpoint: %s",
                        YSyncMessageType.SYNC_STEP2.name,
                        self._channel.path,
                    )
                    await self._channel.send(reply)

    async def _send_updates(self):
        async with self._doc.events() as events:
            async for event in events:
                message = create_update_message(event.update)
                await self._channel.send(message)

    async def __aenter__(self) -> Provider:
        async with AsyncExitStack() as exit_stack:
            self._task_group = await exit_stack.enter_async_context(
                self._get_or_create_task_group()
            )
            await self._task_group.start(self.start)
            self._exit_stack = exit_stack.pop_all()
        return self

    async def __aexit__(self, exc_type, exc_value, exc_tb):
        try:
            await self.stop()
        finally:
            return await self._exit_stack.__aexit__(exc_type, exc_value, exc_tb)

    @asynccontextmanager
    async def _get_or_create_task_group(self) -> AsyncIterator[TaskGroup]:
        if self._task_group is not None:
            yield self._task_group
            return

        async with create_task_group() as tg:
            yield tg

    async def start(
        self,
        *,
        task_status: TaskStatus[None] = TASK_STATUS_IGNORED,
    ) -> None:
        """Start the provider.

        Args:
            task_status: The status to set when the task has started.
        """
        async with self._start_lock:
            async with self._get_or_create_task_group() as self._task_group:
                task_status.started()
                self.started.set()
                self._task_group.start_soon(self._run)

    async def stop(self) -> None:
        """Stop the provider."""
        assert self._task_group is not None
        self._task_group.cancel_scope.cancel()
        self._task_group = None
