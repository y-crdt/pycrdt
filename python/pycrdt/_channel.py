from typing import Protocol


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
