from contextlib import AsyncExitStack

import pytest
from anyio import create_memory_object_stream, create_task_group, sleep
from anyio.streams.stapled import StapledObjectStream
from pycrdt import (
    Channel,
    Doc,
    Provider,
    Text,
    YMessageType,
    create_sync_message,
    create_update_message,
    handle_sync_message,
)
from utils import StartStopContextManager

pytestmark = pytest.mark.anyio


class MyChannel(Channel):
    def __init__(self):
        self.doc = Doc()
        self.doc.observe(self._on_doc_change)
        self._stream_to_remote = StapledObjectStream(
            *create_memory_object_stream[bytes](float("inf"))
        )
        self._stream_from_remote = StapledObjectStream(
            *create_memory_object_stream[bytes](float("inf"))
        )

    def _on_doc_change(self, event):
        message = create_update_message(event.update)
        self._task_group.start_soon(self._stream_from_remote.send, message)

    async def __aenter__(self) -> "MyChannel":
        async with AsyncExitStack() as exit_stack:
            self._task_group = await exit_stack.enter_async_context(create_task_group())
            self._task_group.start_soon(self._run)
            self._exit_stack = exit_stack.pop_all()
        return self

    async def __aexit__(self, exc_type, exc_value, exc_tb):
        await self._stream_from_remote.aclose()
        await self._stream_to_remote.aclose()
        return await self._exit_stack.__aexit__(exc_type, exc_value, exc_tb)

    async def _run(self):
        message = create_sync_message(self.doc)
        await self._stream_from_remote.send(message)
        async for message in self._stream_to_remote:
            message_type = message[0]
            if message_type == YMessageType.SYNC:
                reply = handle_sync_message(message[1:], self.doc)
                if reply is not None:
                    await self._stream_from_remote.send(reply)

    @property
    def path(self) -> str:
        return ""

    async def send(self, message: bytes) -> None:
        await self._stream_to_remote.send(message)

    async def recv(self) -> bytes:
        return await self._stream_from_remote.receive()


async def test_provider(service_api):
    local_doc = Doc()
    channel = MyChannel()
    provider = Provider(local_doc, channel)
    if service_api == "start_stop":
        provider = StartStopContextManager(provider)

    async with channel, provider:
        local_text = local_doc.get("text", type=Text)
        local_text += "Hello"
        await sleep(0.1)
        remote_doc = channel.doc
        remote_text = remote_doc.get("text", type=Text)
        assert str(remote_text) == "Hello"
        remote_text += ", World!"
        await sleep(0.1)
        assert str(local_text) == "Hello, World!"
