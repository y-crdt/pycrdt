import pytest
from anyio import EndOfStream, Event, create_task_group, fail_after, wait_all_tasks_blocked
from anyio.streams.memory import MemoryObjectReceiveStream
from pycrdt import Doc, Text

pytestmark = pytest.mark.anyio


@pytest.mark.parametrize("async_transactions", [False, True])
async def test_unsubscribe_drains_buffer(async_transactions):
    doc = Doc({"text": Text()})
    text = doc["text"]
    async with doc.events(async_transactions=async_transactions) as events:
        for value in ("A", "B"):
            if async_transactions:
                async with doc.transaction():
                    text += value
            else:
                text += value
        events.unsubscribe()
        events.unsubscribe()
        text += "C"
        updates = [event.update async for event in events]
    replica = Doc({"text": Text()})
    for update in updates:
        replica.apply_update(update)
    assert str(replica["text"]) == "AB"
    async with doc.events() as events:
        text += "D"
        events.unsubscribe()
        assert len([event async for event in events]) == 1


async def test_unsubscribe_keeps_other_subscribers():
    doc = Doc({"text": Text()})
    async with doc.events() as first, doc.events() as second:
        doc["text"] += "A"
        first.unsubscribe()
        doc["text"] += "B"
        second.unsubscribe()
        assert len([event async for event in first]) == 1
        assert len([event async for event in second]) == 2


async def test_unsubscribe_with_clones():
    doc = Doc({"text": Text()})
    with doc.events() as events, events.clone() as clone:
        assert type(events) is MemoryObjectReceiveStream
        assert type(clone) is MemoryObjectReceiveStream
        assert events.unsubscribe is clone.unsubscribe
        assert events.statistics().open_receive_streams == 2
        doc["text"] += "A"
        clone.receive_nowait()
        clone.unsubscribe()
        with pytest.raises(EndOfStream):
            await events.receive()
        with pytest.raises(EndOfStream):
            await clone.receive()


async def test_unsubscribe_drains_waiting_async_producer():
    doc = Doc({"text": Text()})
    done = Event()
    async with doc.events(max_buffer_size=0, async_transactions=True) as events:

        async def edit():
            async with doc.transaction():
                doc["text"] += "A"
            done.set()

        with fail_after(3):
            async with create_task_group() as tasks:
                tasks.start_soon(edit)
                await wait_all_tasks_blocked()
                assert events.statistics().tasks_waiting_send == 1
                events.unsubscribe()
                assert len([event async for event in events]) == 1
                await done.wait()
        with pytest.raises(EndOfStream):
            await events.receive()
