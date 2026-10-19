from contextlib import AsyncExitStack

import pytest
from anyio import Event, create_memory_object_stream, create_task_group, fail_after, sleep
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
    def __init__(self, doc=None, pause_sync=False):
        self.doc = Doc() if doc is None else doc
        self.sync_requested = Event()
        self.allow_sync = Event()
        if not pause_sync:
            self.allow_sync.set()
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
        self._task_group.cancel_scope.cancel()
        try:
            return await self._exit_stack.__aexit__(exc_type, exc_value, exc_tb)
        finally:
            await self._stream_from_remote.aclose()
            await self._stream_to_remote.aclose()

    async def _run(self):
        message = create_sync_message(self.doc)
        await self._stream_from_remote.send(message)
        async for message in self._stream_to_remote:
            message_type = message[0]
            if message_type == YMessageType.SYNC:
                reply = handle_sync_message(message[1:], self.doc)
                if reply is not None:
                    self.sync_requested.set()
                    await self.allow_sync.wait()
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


@pytest.mark.parametrize("remote_text", ["", "Hello from the remote peer"])
async def test_provider_synced(service_api, remote_text):
    local_doc = Doc()
    remote_doc = Doc()
    remote_doc["text"] = Text(remote_text)
    channel = MyChannel(remote_doc, pause_sync=True)
    provider = Provider(local_doc, channel)
    service = StartStopContextManager(provider) if service_api == "start_stop" else provider
    sync_states_during_updates = []
    subscription = local_doc.observe(
        lambda event: sync_states_during_updates.append(provider.synced.is_set())
    )

    with fail_after(5):
        async with channel, service:
            await provider.started.wait()
            await channel.sync_requested.wait()
            assert not provider.synced.is_set()
            channel.allow_sync.set()
            await provider.synced.wait()
            assert str(local_doc.get("text", type=Text)) == remote_text
            if remote_text:
                assert sync_states_during_updates
            assert not any(sync_states_during_updates)
            local_doc.unobserve(subscription)


async def test_provider_synced_ignores_updates(service_api):
    local_doc = Doc()
    update_doc = Doc()
    update_doc["text"] = Text("An update before the sync response")
    channel = MyChannel(pause_sync=True)
    provider = Provider(local_doc, channel)
    service = StartStopContextManager(provider) if service_api == "start_stop" else provider
    updated = Event()
    subscription = local_doc.observe(lambda event: updated.set())

    with fail_after(5):
        async with channel, service:
            await channel.sync_requested.wait()
            await channel._stream_from_remote.send(create_update_message(update_doc.get_update()))
            await updated.wait()
            assert not provider.synced.is_set()
            channel.allow_sync.set()
            await provider.synced.wait()
            assert str(local_doc.get("text", type=Text)) == str(update_doc["text"])
            local_doc.unobserve(subscription)
