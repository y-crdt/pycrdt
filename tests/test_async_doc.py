import threading

import pytest
from anyio import (
    CancelScope,
    Event,
    create_task_group,
    from_thread,
    to_thread,
    wait_all_tasks_blocked,
)
from pycrdt import AsyncDoc, Doc, Text

pytestmark = pytest.mark.anyio


async def test_create_and_synchronize():
    loop_thread = threading.get_ident()
    doc = await AsyncDoc.create({"text": Text("hello")}, client_id=123, guid="async-doc")
    assert await doc.run_sync(lambda doc: (doc.client_id, doc.guid)) == (123, "async-doc")
    assert await doc.run_sync(lambda doc: threading.get_ident()) != loop_thread
    other = await AsyncDoc.create()
    await other.apply_update(await doc.get_update())
    assert await other.get_state() == await doc.get_state()
    assert await other.run_sync(lambda doc: str(doc.get("text", type=Text))) == "hello"
    state = await other.get_state()

    def append(doc, text):
        doc["text"] += text

    await doc.run_sync(append, " world")
    await other.apply_update(await doc.get_update(state))
    assert await other.run_sync(lambda doc: str(doc.get("text", type=Text))) == "hello world"


async def test_wrap_existing_doc_and_errors():
    doc = AsyncDoc(Doc({"text": Text()}))

    def edit(doc):
        with doc.transaction(origin="edit"):
            doc["text"] += "saved"
            raise ValueError("callback failed")

    with pytest.raises(ValueError, match="callback failed"):
        await doc.run_sync(edit)
    assert await doc.run_sync(lambda doc: str(doc["text"])) == "saved"
    with pytest.raises(ValueError, match="Cannot decode update"):
        await doc.apply_update(b"invalid")
    assert await doc.get_state()


async def test_concurrent_calls_are_serialized():
    doc = await AsyncDoc.create({"text": Text()})
    started = Event()
    release = threading.Event()
    order = []

    def first(doc):
        with doc.transaction():
            doc["text"] += "a"
            order.append("first started")
            from_thread.run_sync(started.set)
            assert release.wait(5)
            doc["text"] += "b"
            order.append("first finished")

    def second(doc):
        order.append("second")
        doc["text"] += "c"

    async with create_task_group() as group:
        group.start_soon(doc.run_sync, first)
        await started.wait()
        group.start_soon(doc.run_sync, second)
        await wait_all_tasks_blocked()
        assert order == ["first started"]
        release.set()
    assert order == ["first started", "first finished", "second"]
    assert await doc.run_sync(lambda doc: str(doc["text"])) == "abc"


async def test_cancellation_does_not_abandon_worker():
    doc = await AsyncDoc.create({"text": Text()})
    started = Event()
    release = threading.Event()
    scope = CancelScope()
    finished = Event()

    def edit(doc):
        from_thread.run_sync(started.set)
        assert release.wait(5)
        doc["text"] += "done"

    async def run():
        with scope:
            await doc.run_sync(edit)
        finished.set()

    async with create_task_group() as group:
        group.start_soon(run)
        await started.wait()
        scope.cancel()
        await wait_all_tasks_blocked()
        assert not finished.is_set()
        release.set()
    assert finished.is_set()
    assert await doc.run_sync(lambda doc: str(doc["text"])) == "done"


async def test_cancel_waiting_operation():
    doc = await AsyncDoc.create()
    scope = CancelScope()
    finished = Event()

    async def run():
        with scope:
            await doc.run_sync(lambda doc: pytest.fail("Cancelled callback ran"))
        finished.set()

    await doc._limiter.acquire()
    try:
        async with create_task_group() as group:
            group.start_soon(run)
            await wait_all_tasks_blocked()
            scope.cancel()
            await finished.wait()
    finally:
        doc._limiter.release()
    assert await doc.get_state() == b"\x00"


async def test_updates_are_safe_to_consume_and_unsubscribe():
    doc = await AsyncDoc.create({"text": Text()})
    replica = await AsyncDoc.create()
    await replica.apply_update(await doc.get_update())

    def edit(doc):
        with doc.transaction():
            doc["text"] += "hello"
            doc["text"] += " world"

    async with doc.updates() as first, doc.updates() as second:
        await doc.run_sync(edit)
        update = await first.receive()
        assert isinstance(update, bytes)
        assert await second.receive() == update
        # Consume on another worker too: the result is owned bytes, not a borrowed event.
        assert await to_thread.run_sync(bytes, update) == update
        await replica.apply_update(update)
        assert await replica.run_sync(lambda doc: str(doc.get("text", type=Text))) == "hello world"
    assert await doc.run_sync(lambda doc: len(doc._subscriptions)) == 0


async def test_updates_cleanup_on_cancellation_and_closed_receiver():
    doc = await AsyncDoc.create({"text": Text()})
    with CancelScope() as scope:
        async with doc.updates() as updates:
            updates.close()
            await doc.run_sync(lambda doc: doc["text"].insert(0, "hello"))
            scope.cancel()
    assert await doc.run_sync(lambda doc: len(doc._subscriptions)) == 0
    assert await doc.run_sync(lambda doc: str(doc["text"])) == "hello"
