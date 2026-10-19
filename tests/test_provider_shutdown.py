import pytest
from anyio import Event, create_task_group, fail_after, sleep_forever
from pycrdt import Channel, Doc, Provider, Text, YSyncMessageType, handle_sync_message

pytestmark = pytest.mark.anyio


class SlowChannel(Channel):
    def __init__(self, fail=False, block_initial=False):
        self.send_started = Event()
        self.allow_send = Event()
        self.messages = []
        self.fail = fail
        self.block_initial = block_initial

    @property
    def path(self):
        return "test"

    async def send(self, message):
        if self.block_initial or message[1] == YSyncMessageType.SYNC_UPDATE:
            self.send_started.set()
            await self.allow_send.wait()
            if self.fail:
                raise OSError("send failed")
        self.messages.append(message)

    async def recv(self):
        await sleep_forever()


async def test_exit_drains_queued_and_inflight_updates():
    doc = Doc({"text": Text()})
    channel = SlowChannel()
    exited = Event()

    async def edit():
        async with Provider(doc, channel):
            for value in ("A", "B", "C"):
                doc["text"] += value
        exited.set()

    with fail_after(3):
        async with create_task_group() as tasks:
            tasks.start_soon(edit)
            await channel.send_started.wait()
            assert not exited.is_set()
            channel.allow_send.set()
            await exited.wait()
    replica = Doc({"text": Text()})
    updates = [m for m in channel.messages if m[1] == YSyncMessageType.SYNC_UPDATE]
    assert len(updates) == 3
    for message in updates:
        handle_sync_message(message[1:], replica)
    assert str(replica["text"]) == "ABC"


async def test_exit_without_updates():
    channel = SlowChannel()
    with fail_after(3):
        async with Provider(Doc(), channel):
            pass
    assert len(channel.messages) == 1


async def test_exception_exit_does_not_drain():
    doc = Doc({"text": Text()})
    channel = SlowChannel()
    with pytest.raises(ExceptionGroup) as error:
        with fail_after(3):
            async with Provider(doc, channel):
                doc["text"] += "A"
                raise ValueError("body failed")
    assert error.value.subgroup(ValueError) is not None
    assert not channel.allow_send.is_set()


async def test_cancellation_during_drain():
    doc = Doc({"text": Text()})
    channel = SlowChannel()
    stopped = Event()

    async def edit():
        try:
            async with Provider(doc, channel):
                doc["text"] += "A"
        finally:
            stopped.set()

    with fail_after(3):
        async with create_task_group() as tasks:
            tasks.start_soon(edit)
            await channel.send_started.wait()
            tasks.cancel_scope.cancel()
    assert stopped.is_set()
    assert not channel.allow_send.is_set()


@pytest.mark.parametrize("block_initial", [False, True])
async def test_send_failure_propagates(block_initial):
    doc = Doc({"text": Text()})
    channel = SlowChannel(fail=True, block_initial=block_initial)
    channel.allow_send.set()
    with pytest.raises(ExceptionGroup) as error:
        with fail_after(3):
            async with Provider(doc, channel):
                doc["text"] += "A"
    assert error.value.subgroup(OSError) is not None


async def test_exit_waits_for_initial_send():
    channel = SlowChannel(block_initial=True)
    exited = Event()

    async def run():
        async with Provider(Doc(), channel):
            pass
        exited.set()

    with fail_after(3):
        async with create_task_group() as tasks:
            tasks.start_soon(run)
            await channel.send_started.wait()
            assert not exited.is_set()
            channel.allow_send.set()
            await exited.wait()
    assert len(channel.messages) == 1
