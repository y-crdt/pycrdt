from functools import partial

import pytest
from anyio import TASK_STATUS_IGNORED, Event, create_task_group, sleep
from anyio.abc import TaskStatus
from pycrdt import Array, Doc, Map, Text

pytestmark = pytest.mark.anyio


def callback(events, event):
    events.append(event)


async def async_callback(events, event):
    events.append(event)
    await sleep(0)


def encode_client_id(client_id_bytes):
    client_id_len = len(client_id_bytes)
    b = []
    for i, n in enumerate(client_id_bytes[::-1]):
        j = n << i
        if i != client_id_len - 1:
            j |= 0x80
        b.append(j)
    return bytes(b)


def test_api():
    doc = Doc()

    with pytest.raises(RuntimeError) as excinfo:
        doc[0] = Array()
    assert str(excinfo.value) == "Key must be of type string"

    doc["a0"] = a0 = Array()
    doc["m0"] = m0 = Map()
    doc["t0"] = t0 = Text()
    a1 = doc.get("a1", type=Array)
    m1 = doc.get("m1", type=Map)
    t1 = doc.get("t1", type=Text)
    assert {key for key in doc} == {"a0", "m0", "t0", "a1", "m1", "t1"}
    assert {type(value) for value in doc.values()} == {
        type(value) for value in (a0, m0, t0, a1, m1, t1)
    }
    assert {(key, type(value)) for key, value in doc.items()} == {
        (key, type(value))
        for key, value in (
            ("a0", a0),
            ("m0", m0),
            ("t0", t0),
            ("a1", a1),
            ("m1", m1),
            ("t1", t1),
        )
    }


async def test_subdoc():
    doc0 = Doc()
    map0 = Map()
    doc0["map0"] = map0

    doc1 = Doc()
    map1 = Map()
    doc1["map1"] = map1

    doc2 = Doc()
    array2 = Array()
    doc2["array2"] = array2

    doc0["array0"] = Array(["hello", 1, doc1])
    map0.update({"key0": "val0", "key1": doc2})

    update0 = doc0.get_update()

    remote_doc = Doc()
    events = []
    aevents = []
    sub = remote_doc.observe_subdocs(partial(callback, events))  # noqa: F841
    asub = remote_doc.observe_subdocs(partial(async_callback, aevents))  # noqa: F841
    async with remote_doc.transaction():
        remote_doc.apply_update(update0)
    remote_array0 = Array()
    remote_map0 = Map()
    remote_doc["array0"] = remote_array0
    remote_doc["map0"] = remote_map0

    remote_doc1 = remote_array0[2]
    remote_doc2 = remote_map0["key1"]

    remote_map1 = Map()
    remote_array2 = Array()
    remote_doc1["map1"] = remote_map1
    remote_doc2["array2"] = remote_array2

    map1["foo"] = "bar"

    update1 = doc1.get_update()

    array2 += ["baz", 3]

    update2 = doc2.get_update()

    remote_doc1.apply_update(update1)
    remote_doc2.apply_update(update2)

    assert str(map1) == str(remote_map1)
    assert str(array2) == str(remote_array2)

    assert len(events) == 1
    assert len(aevents) == 1
    event = events[0]
    aevent = aevents[0]
    assert len(event.added) == 2
    assert len(aevent.added) == 2
    assert event.added[0] in (doc1.guid, doc2.guid)
    assert aevent.added[0] in (doc1.guid, doc2.guid)
    assert event.added[1] in (doc1.guid, doc2.guid)
    assert aevent.added[1] in (doc1.guid, doc2.guid)
    assert doc1.guid != doc2.guid
    assert event.removed == []
    assert aevent.removed == []
    assert event.loaded == []
    assert aevent.loaded == []


def test_doc_in_event():
    doc = Doc()
    doc["array"] = array = Array()
    events = []
    sub = array.observe(partial(callback, events))  # noqa: F841
    array.append(Doc())
    assert isinstance(events[0].delta[0]["insert"][0], Doc)


def test_transaction_event():
    doc = Doc()
    events = []
    sub = doc.observe(partial(callback, events))  # noqa: F841
    doc["text0"] = Text("Hello, World!")

    remote_doc = Doc()
    for event in events:
        remote_doc.apply_update(event.update)
    events.clear()

    doc.unobserve(sub)
    doc["text1"] = Text("Goodbye!")
    assert len(events) == 0

    remote_text0 = remote_doc.get("text0", type=Text)
    assert str(remote_text0) == "Hello, World!"
    remote_text1 = remote_doc.get("text1", type=Text)
    assert str(remote_text1) == ""


def test_client_id():
    doc0 = Doc()
    doc1 = Doc()
    assert doc0.client_id != doc1.client_id

    client_id_bytes = b"\x01\x02\x03\x04"
    client_id = int.from_bytes(client_id_bytes, byteorder="big")
    doc2 = Doc(client_id=client_id)
    assert doc2.client_id == client_id
    text = Text("Hello, World!")
    doc2["text"] = text
    update = doc2.get_update()

    b = encode_client_id(client_id_bytes)

    assert update[2 : 2 + len(b)] == b


def test_roots():
    remote_doc = Doc(
        {
            "a": Text("foo"),
            "b": Array([5, 2, 8]),
            "c": Map({"k1": 1, "k2": 2}),
        }
    )
    roots = dict(remote_doc)
    assert str(roots["a"]) == "foo"
    assert list(roots["b"]) == [5, 2, 8]
    assert dict(roots["c"]) == {"k1": 1, "k2": 2}

    local_doc = Doc()
    update = remote_doc.get_update()
    local_doc.apply_update(update)
    roots = dict(local_doc)
    assert roots["a"] is None
    assert roots["b"] is None
    assert roots["c"] is None
    # assert str(roots["a"]) == "foo"
    # assert list(roots["b"]) == [5, 2, 8]
    # assert dict(roots["c"]) == None  # {"k1": 1, "k2": 2}


def test_empty_update():
    doc = Doc()
    doc["text"] = Text()
    events = []
    sub = doc.observe(partial(callback, events))  # noqa: F841

    # this triggers an empty update
    doc["text"]
    # empty updates should not emit an event
    assert not events


def test_not_empty_update():
    doc = Doc()
    doc["text"] = text = Text()
    events = []
    sub = doc.observe(partial(callback, events))  # noqa: F841

    text += "helloo"
    events.clear()
    del text[5]
    assert events


def test_get_update_exception():
    doc = Doc()
    with pytest.raises(ValueError) as excinfo:
        doc.get_update(b"\x12")
    assert str(excinfo.value) == "Cannot decode state"


async def test_iterate_events():
    doc = Doc()
    updates = []

    async def iterate_events(done_event, *, task_status: TaskStatus[None] = TASK_STATUS_IGNORED):
        async with doc.events() as events:
            task_status.started()
            idx = 0
            async for event in events:
                updates.append(event.update)
                if idx == 1:
                    done_event.set()
                    return
                idx += 1

    async with create_task_group() as tg:
        done_event = Event()
        await tg.start(iterate_events, done_event)
        text = doc.get("text", type=Text)
        text += "Hello"
        text += ", World!"
        await done_event.wait()
        text += " Goodbye."

    assert len(updates) == 2
    assert updates[0].endswith(b"Hello\x00")
    assert updates[1].endswith(b", World!\x00")


async def test_iterate_events_with_async_transactions():
    doc = Doc()
    updates = []

    async def iterate_events(done_event, *, task_status: TaskStatus[None] = TASK_STATUS_IGNORED):
        async with doc.events(async_transactions=True) as events:
            task_status.started()
            idx = 0
            async for event in events:
                updates.append(event.update)
                if idx == 1:
                    done_event.set()
                    return
                idx += 1

    async with create_task_group() as tg:
        done_event = Event()
        await tg.start(iterate_events, done_event)
        async with doc.transaction():
            text = doc.get("text", type=Text)
        async with doc.transaction():
            text += "Hello"
        async with doc.transaction():
            text += ", World!"
        await done_event.wait()
        async with doc.transaction():
            text += " Goodbye."

    assert len(updates) == 2
    assert updates[0].endswith(b"Hello\x00")
    assert updates[1].endswith(b", World!\x00")
