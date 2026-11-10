import gc
import time
from functools import partial

import pytest
from anyio import Event, create_task_group, fail_after, sleep, to_thread
from pycrdt import Array, Doc, Map, ReadTransaction, Text, XmlFragment

pytestmark = pytest.mark.anyio


def test_callback_transaction():
    text = Text()
    array = Array()
    map_ = Map()
    Doc(
        {
            "text": text,
            "array": array,
            "map": map_,
        }
    )
    events = []

    def callback(event):
        target = event.target
        doc = target.doc
        with doc.transaction():
            events.append(target.to_py())
            with doc.transaction():
                events.append(str(target))

    sub0 = text.observe(callback)  # noqa: F841
    sub1 = array.observe(callback)  # noqa: F841
    sub2 = map_.observe(callback)  # noqa: F841
    with text.doc.transaction():
        text += "hello"
        text += " world"
    array.append(1)
    map_["foo"] = "bar"
    assert events == [
        "hello world",
        "hello world",
        [1],
        "[1]",
        {"foo": "bar"},
        '{"foo":"bar"}',
    ]


def test_origin():
    doc0 = Doc()
    doc0["text"] = text = Text()

    class Origin:
        pass

    origin0 = Origin()
    origin1 = None

    def callback(event, txn):
        nonlocal origin1
        origin1 = txn.origin

    text.observe(callback)

    with doc0.transaction(origin=origin0) as txn:
        text += "Hello"

    assert origin1 is origin0

    with pytest.raises(RuntimeError) as excinfo:
        txn.origin

    assert str(excinfo.value) == "No current transaction"

    with pytest.raises(TypeError) as excinfo:
        doc0.transaction(origin={})

    assert str(excinfo.value) == "Origin must be hashable"

    with doc0.transaction() as txn:
        assert txn.origin is None

    doc1 = Doc()
    with doc0.transaction(origin=origin0) as txn0:
        with doc1.transaction(origin=origin0) as txn1:
            assert txn0.origin == origin0
            assert txn1.origin == origin0
            assert len(doc0._origins) == 1
            assert list(doc0._origins.values())[0] == origin0
            assert doc0._origins == doc1._origins
        assert len(doc0._origins) == 1
        assert list(doc0._origins.values())[0] == origin0
        assert len(doc1._origins) == 0
    assert len(doc0._origins) == 0
    assert len(doc1._origins) == 0

    with doc0.transaction(origin=123):
        with doc0.transaction(origin=123):
            with doc0.transaction():
                with pytest.raises(RuntimeError) as excinfo:
                    with doc0.transaction(origin=456):
                        pass  # pragma: no cover

    assert str(excinfo.value) == "Nested transactions must have same origin as root transaction"


def test_observe_callback_params():
    doc = Doc()
    doc["text"] = text = Text()

    cb0_called = False
    cb1_called = False
    cb2_called = False

    def callback0():
        nonlocal cb0_called
        cb0_called = True

    def callback1(event):
        nonlocal cb1_called
        cb1_called = True

    def callback2(event, txn):
        nonlocal cb2_called
        cb2_called = True

    text.observe(callback0)
    text.observe(callback1)
    text.observe(callback2)

    with doc.transaction():
        text += "Hello, World!"

    assert cb0_called
    assert cb1_called
    assert cb2_called


@pytest.mark.parametrize("method", ["observe", "observe_deep"])
def test_observe_callback_keyword_params(method):
    doc = Doc()
    doc["text"] = text = Text()
    calls = []

    def callback0(event, *, option=None):
        calls.append((event, option))

    def callback1(event, txn, **kwargs):
        calls.append((event, txn, kwargs))

    sub0 = getattr(text, method)(callback0)  # noqa: F841
    sub1 = getattr(text, method)(callback1)  # noqa: F841
    text += "Hello"

    assert len(calls) == 2
    assert calls[0][1] is None
    assert isinstance(calls[1][1], ReadTransaction)
    assert calls[1][2] == {}


def create_new_transaction(map0: Map, key: str, val: str) -> None:
    with map0.doc.new_transaction():
        time.sleep(0.1)
        map0[key] = val
    gc.collect()
    # looks like PyPy needs a second one:
    gc.collect()


async def create_new_transaction_async(map0: Map, key: str, val: str) -> None:
    async with map0.doc.new_transaction():
        await sleep(0.1)
        map0[key] = val


async def test_new_transaction_multithreading():
    doc = Doc(allow_multithreading=True)
    doc["map0"] = map0 = Map()
    gc.collect()

    def callback(events, event):
        events.append(None)

    events = []
    sid = doc.observe(partial(callback, events))

    async with create_task_group() as tg:
        tg.start_soon(to_thread.run_sync, partial(create_new_transaction, map0, "key0", "val0"))
        tg.start_soon(to_thread.run_sync, partial(create_new_transaction, map0, "key1", "val1"))

    assert len(events) == 2
    assert map0.to_py() == {"key0": "val0", "key1": "val1"}

    doc.unobserve(sid)


async def test_new_transaction_no_multithreading():
    doc = Doc(allow_multithreading=False)
    doc["map0"] = map0 = Map()
    gc.collect()

    def callback(events, event):
        events.append(None)

    events = []
    sid = doc.observe(partial(callback, events))

    with pytest.raises(ExceptionGroup) as excinfo:
        async with create_task_group() as tg:
            tg.start_soon(to_thread.run_sync, partial(create_new_transaction, map0, "key0", "val0"))
            tg.start_soon(to_thread.run_sync, partial(create_new_transaction, map0, "key1", "val1"))
    assert len(excinfo.value.exceptions) == 1
    assert isinstance(excinfo.value.exceptions[0], RuntimeError)
    assert str(excinfo.value.exceptions[0]) == "Already in a transaction"

    assert len(events) == 1
    assert len(map0.to_py()) == 1
    assert map0.to_py() in [{"key0": "val0"}, {"key1": "val1"}]

    doc.unobserve(sid)


def test_new_transaction_while_transaction():
    doc = Doc(allow_multithreading=True)

    with doc.transaction():
        with pytest.raises(TimeoutError) as excinfo:
            with doc.new_transaction(timeout=0.1):
                pass  # pragma: no cover
    assert str(excinfo.value) == "Could not acquire transaction"


async def test_new_transaction_while_async_transaction():
    doc = Doc(allow_multithreading=True)

    async with doc.new_transaction():
        with pytest.raises(TimeoutError) as excinfo:
            with doc.new_transaction(timeout=0.1):
                pass  # pragma: no cover
    assert str(excinfo.value) == "Could not acquire transaction"


async def test_new_async_transaction_while_transaction():
    doc = Doc(allow_multithreading=True)

    with doc.transaction():
        with pytest.raises(TimeoutError) as excinfo:
            async with doc.new_transaction(timeout=0.1):
                pass  # pragma: no cover
    assert str(excinfo.value) == "Could not acquire transaction"


async def test_new_async_transaction_while_async_transaction():
    doc = Doc(allow_multithreading=True)

    async with doc.new_transaction():
        with pytest.raises(TimeoutError):
            with fail_after(0.1):
                async with doc.new_transaction():
                    pass  # pragma: no cover


async def test_new_async_transaction_concurrent():
    doc = Doc(allow_multithreading=True)
    doc["map0"] = map0 = Map()

    def callback(events, event):
        events.append(event)

    events = []
    doc.observe(partial(callback, events))
    async with create_task_group() as tg:
        tg.start_soon(create_new_transaction_async, map0, "key0", "val0")
        tg.start_soon(create_new_transaction_async, map0, "key1", "val1")

    assert len(events) == 2
    assert map0.to_py() == {"key0": "val0", "key1": "val1"}


@pytest.mark.parametrize("allow_multithreading", [False, True])
async def test_concurrent_transactions_with_same_origin(allow_multithreading):
    doc = Doc(allow_multithreading=allow_multithreading)
    map0 = doc.get("map0", type=Map)
    origins = []
    first_entered = Event()
    second_created = Event()

    async def first_transaction():
        async with doc.new_transaction(origin="origin0") as txn:
            first_entered.set()
            await second_created.wait()
            map0["key0"] = "val"
            origins.append(txn.origin)

    async def second_transaction():
        await first_entered.wait()
        transaction = doc.new_transaction(origin="origin0")
        second_created.set()
        async with transaction as txn:
            map0["key1"] = "val"
            origins.append(txn.origin)

    with fail_after(5):
        async with create_task_group() as tg:
            tg.start_soon(first_transaction)
            tg.start_soon(second_transaction)

    assert origins == ["origin0", "origin0"]
    assert doc._origins == {}
    with doc.new_transaction(timeout=1):
        map0["key2"] = "val"
    assert map0.to_py() == {"key0": "val", "key1": "val", "key2": "val"}


@pytest.mark.parametrize("method", ["transaction", "new_transaction"])
def test_unentered_transaction_does_not_register_origin(method):
    doc = Doc()
    origin = object()
    transaction = getattr(doc, method)(origin=origin)
    assert doc._origins == {}

    with transaction as txn:
        assert txn.origin is origin
        assert doc._origins == {hash(origin): origin}
    assert doc._origins == {}


@pytest.mark.parametrize("waiting_origin", ["active", "waiting"])
def test_timed_out_transaction_does_not_register_origin(waiting_origin):
    doc = Doc(allow_multithreading=True)
    with doc.transaction(origin="active") as active:
        with pytest.raises(TimeoutError):
            with doc.new_transaction(origin=waiting_origin, timeout=0):
                pass  # pragma: no cover
        assert active.origin == "active"
        assert doc._origins == {hash("active"): "active"}

    assert doc._origins == {}
    with doc.new_transaction(origin=waiting_origin, timeout=1) as txn:
        assert txn.origin == waiting_origin
    assert doc._origins == {}


async def test_new_async_transaction_concurrent_no_multithreading():
    doc = Doc(allow_multithreading=False)
    doc["map0"] = map0 = Map()

    def callback(events, event):
        events.append(event)

    events = []
    doc.observe(partial(callback, events))
    async with create_task_group() as tg:
        tg.start_soon(create_new_transaction_async, map0, "key0", "val0")
        tg.start_soon(create_new_transaction_async, map0, "key1", "val1")

    assert len(events) == 2
    assert map0.to_py() == {"key0": "val0", "key1": "val1"}


def test_get_root_type_in_transaction():
    doc = Doc()
    with doc.transaction():
        text = doc.get("text", type=Text)
        array = doc.get("Array", type=Array)
        map0 = doc.get("map0", type=Map)
        frag = doc.get("xml", type=XmlFragment)
        text += "foo"
        array.append("bar")
        map0["key0"] = "val0"
        frag.children.append("baz")

    assert str(text) == "foo"
    assert array.to_py() == ["bar"]
    assert map0.to_py() == {"key0": "val0"}
    assert str(frag) == "baz"


async def test_async_callback_in_new_transaction():
    doc0 = Doc()
    update = None

    async def async_callback(event):
        nonlocal update
        update = event.update

    doc0.observe(async_callback)
    text0 = doc0.get("text", type=Text)

    async with doc0.new_transaction():
        text0 += "hello"

    doc1 = Doc()
    doc1.apply_update(update)
    text1 = doc1.get("text", type=Text)
    assert str(text1) == "hello"


async def test_async_callback_in_sync_transaction():
    doc = Doc()

    async def async_callback(event):
        pass  # pragma: nocover

    doc.observe(async_callback)
    text = doc.get("text", type=Text)

    with pytest.raises(RuntimeError) as excinfo:
        with doc.transaction():
            text += "hello"
    assert str(excinfo.value) == "Async callback in non-async transaction"


async def test_async_transaction_in_existing_async_transaction():
    doc0 = Doc()
    update = None

    async def async_callback(event):
        nonlocal update
        update = event.update

    doc0.observe(async_callback)
    text0 = doc0.get("text", type=Text)

    async with doc0.transaction():
        async with doc0.transaction():
            text0 += "hello"

    doc1 = Doc()
    doc1.apply_update(update)
    text1 = doc1.get("text", type=Text)
    assert str(text1) == "hello"


async def test_async_transaction_in_existing_sync_transaction():
    doc = Doc()
    with doc.transaction():
        with pytest.raises(RuntimeError) as excinfo:
            async with doc.transaction():
                pass  # pragma: nocover
        assert str(excinfo.value) == "Already in a non-async transaction"


async def test_concurrent_async_transactions():
    doc = Doc()

    async def create_async_transaction(seconds, task_status):
        async with doc.transaction():
            task_status.started()
            await sleep(seconds)

    async with create_task_group() as tg:
        await tg.start(create_async_transaction, 0.2)
        await tg.start(create_async_transaction, 0.1)


class Interrupt(BaseException):
    pass


def raise_once(exception, raised, event):
    if not raised:
        raised.append(None)
        raise exception


@pytest.mark.parametrize("origin", [None, "test-origin"])
def test_new_transaction_after_commit_error_multithreading(origin):
    doc = Doc(allow_multithreading=True)
    map0 = doc.get("map0", type=Map)
    sub = doc.observe(partial(raise_once, Interrupt(), []))  # noqa: F841

    with pytest.raises(Interrupt):
        with doc.transaction(origin=origin):
            map0["key0"] = "val0"

    assert doc._origins == {}
    with doc.new_transaction(origin=origin, timeout=1) as txn:
        assert txn.origin == origin
        map0["key1"] = "val1"
    assert doc._origins == {}
    assert map0.to_py() == {"key0": "val0", "key1": "val1"}


@pytest.mark.parametrize("anyio_backend", ["asyncio", "trio"])
@pytest.mark.parametrize("origin", [None, "test-origin"])
async def test_new_async_transaction_after_observer_error(anyio_backend, origin):
    doc = Doc()
    map0 = doc.get("map0", type=Map)
    sub = doc.observe(partial(raise_once, ValueError("error"), []))  # noqa: F841

    with pytest.RaisesGroup(ValueError, match="Observer callback error"):
        async with doc.new_transaction(origin=origin):
            map0["key0"] = "val0"

    assert doc._origins == {}

    async def create_new_async_transaction():
        async with doc.new_transaction(origin=origin) as txn:
            assert txn.origin == origin
            map0["key1"] = "val1"

    with fail_after(1):
        async with create_task_group() as tg:
            tg.start_soon(create_new_async_transaction)
    assert doc._origins == {}
    assert map0.to_py() == {"key0": "val0", "key1": "val1"}


@pytest.mark.parametrize("anyio_backend", ["asyncio", "trio"])
async def test_new_async_transaction_after_async_observer_error(anyio_backend):
    doc = Doc()
    map0 = doc.get("map0", type=Map)
    raised = []

    async def callback(event):
        raise_once(ValueError("error"), raised, event)

    sub = doc.observe(callback)  # noqa: F841

    with pytest.RaisesGroup(ValueError):
        async with doc.new_transaction():
            map0["key0"] = "val0"

    with fail_after(1):
        async with doc.new_transaction():
            map0["key1"] = "val1"
    assert map0.to_py() == {"key0": "val0", "key1": "val1"}


@pytest.mark.parametrize("anyio_backend", ["asyncio", "trio"])
async def test_async_transaction_after_observer_error(anyio_backend):
    doc = Doc()
    map0 = doc.get("map0", type=Map)
    sub0 = doc.observe(partial(raise_once, ValueError("error"), []))  # noqa: F841

    async def create_failing_async_transaction():
        with pytest.RaisesGroup(ValueError, match="Observer callback error"):
            async with doc.transaction():
                map0["key0"] = "val0"

    # the transaction's task group must be exited before the task that created it
    async with create_task_group() as tg:
        tg.start_soon(create_failing_async_transaction)

    events = []

    async def callback(event):
        events.append(event)

    sub1 = doc.observe(callback)  # noqa: F841
    async with doc.transaction():
        map0["key1"] = "val1"
    assert len(events) == 1
