import pytest
from anyio import TASK_STATUS_IGNORED, Event, create_task_group
from anyio.abc import TaskStatus
from pycrdt import Array, Assoc, Doc, Map, StickyIndex, Text

pytestmark = pytest.mark.anyio

hello = "Hello"
world = ", World"
sir = " Sir"
punct = "!"


def test_iterate():
    doc = Doc()
    doc["text"] = text = Text("abc")
    assert [char for char in text] == ["a", "b", "c"]


def test_str():
    doc1 = Doc()
    text1 = Text()
    doc1["text"] = text1
    with doc1.transaction():
        text1 += hello
        with doc1.transaction():
            text1 += world
        text1 += punct

    assert str(text1) == hello + world + punct

    doc2 = Doc()
    array2 = Array()
    doc2["array"] = array2
    text2 = Text("val")
    map2 = Map({"key": text2})
    array2.append(map2)
    assert str(array2) == '[{"key":"val"}]'


def test_api():
    doc = Doc()
    text = Text(hello + punct)

    with pytest.raises(RuntimeError) as excinfo:
        text.integrated
    assert str(excinfo.value) == "Not integrated in a document yet"

    with pytest.raises(RuntimeError) as excinfo:
        text.doc
    assert str(excinfo.value) == "Not integrated in a document yet"

    assert text.is_prelim
    assert text.prelim == hello + punct
    assert not text.is_integrated

    doc["text"] = text
    assert str(text) == hello + punct
    text.insert(len(hello), world)
    assert str(text) == hello + world + punct
    text.clear()
    assert len(text) == 0
    text[:] = hello + world + punct
    assert str(text) == hello + world + punct
    text[len(hello) : len(hello) + len(world)] = sir
    assert str(text) == hello + sir + punct
    # single character replacement
    text[len(text) - 1] = "?"
    assert str(text) == hello + sir + "?"
    # deletion with only an index
    del text[len(text) - 1]
    assert str(text) == hello + sir
    # deletion of an arbitrary range
    del text[len(hello) : len(hello) + len(sir)]
    assert str(text) == hello
    # deletion with start index == range length
    text += str(text)
    del text[len(hello) : 2 * len(hello)]
    assert str(text) == hello
    # deletion with a range of 0
    del text[len(hello) : len(hello)]
    assert str(text) == hello
    assert "".join([char for char in text]) == hello
    assert "el" in text

    with pytest.raises(RuntimeError) as excinfo:
        del text["a"]
    assert str(excinfo.value) == "Index not supported: a"

    with pytest.raises(RuntimeError) as excinfo:
        text["a"] = "b"
    assert str(excinfo.value) == "Index not supported: a"

    with pytest.raises(RuntimeError) as excinfo:
        text[1] = "ab"
    assert str(excinfo.value) == "Single item assigned value must have a length of 1, not 2"


def test_to_py():
    doc = Doc()
    doc["text"] = text = Text(hello)
    assert text.to_py() == hello


def test_prelim():
    text = Text(hello)
    assert text.to_py() == hello


def test_slice():
    doc = Doc()
    doc["text"] = text = Text(hello)

    for i, c in enumerate(hello):
        assert text[i] == c

    with pytest.raises(RuntimeError) as excinfo:
        text[1::2] = "a"
    assert str(excinfo.value) == "Step not supported"

    with pytest.raises(RuntimeError) as excinfo:
        text[-1:] = "a"
    assert str(excinfo.value) == "Negative start not supported"

    with pytest.raises(RuntimeError) as excinfo:
        text[:-1] = "a"
    assert str(excinfo.value) == "Negative stop not supported"


def test_formatting():
    doc = Doc()
    doc["text"] = text = Text("")

    text.insert(0, "hello ")
    assert len(text) == len("hello "), str(text)
    text.insert(len(text), "world", {"bold": True})
    text.insert(len(text), "! I have formatting!", {})
    text.format(len("hello world! "), len("hello world! I have formatting!") + 1, {"font-size": 32})
    text.insert_embed(len(text), b"png blob", {"type": "image"})

    diff = text.diff()

    assert diff == [
        ("hello ", None),
        ("world", {"bold": True}),
        ("! ", None),
        ("I have formatting!", {"font-size": 32}),
        (bytearray(b"png blob"), {"type": "image"}),
    ]


def test_observe():
    doc = Doc()
    doc["text"] = text = Text()
    events = []

    def callback(event):
        nonlocal text
        with pytest.raises(RuntimeError) as excinfo:
            text += world
        assert (
            str(excinfo.value)
            == "Read-only transaction cannot be used to modify document structure"
        )
        events.append(event)

    sub = text.observe(callback)  # noqa: F841
    text += hello
    assert str(events[0]) == """{target: Hello, delta: [{'insert': 'Hello'}], path: []}"""


async def test_iterate_events():
    doc = Doc()
    text = doc.get("text", type=Text)
    deltas = []

    async def iterate_events(done_event, *, task_status: TaskStatus[None] = TASK_STATUS_IGNORED):
        async with text.events() as events:
            task_status.started()
            idx = 0
            async for event in events:
                deltas.append(event.delta)
                if idx == 1:
                    done_event.set()
                    return
                idx += 1

    async with create_task_group() as tg:
        done_event = Event()
        await tg.start(iterate_events, done_event)
        text += "Hello"
        text += ", World!"
        await done_event.wait()
        text += " Goodbye."

    assert len(deltas) == 2
    assert deltas[0] == [{"insert": "Hello"}]
    assert deltas[1] == [{"retain": 5}, {"insert": ", World!"}]


@pytest.mark.parametrize("serialize", ["to_json", "encode"])
def test_sticky_index(serialize: str):
    first = "$$$"
    second = "-----*--"
    idx = second.index("*")

    doc0 = Doc()
    text0 = doc0.get("text", type=Text)
    text0 += first

    doc1 = Doc()
    text1 = doc1.get("text", type=Text)
    text1 += second

    assert text1[idx] == "*"
    sticky_index = text1.sticky_index(idx, Assoc.AFTER)
    assert sticky_index.assoc == Assoc.AFTER
    if serialize == "to_json":
        data = sticky_index.to_json()
        sticky_index = StickyIndex.from_json(data, text1)
    else:
        data = sticky_index.encode()
        sticky_index = StickyIndex.decode(data, text1)

    doc1.apply_update(doc0.get_update())
    assert str(text1) in (first + second, second + first)
    new_idx = sticky_index.get_index()
    assert text1[new_idx] == "*"


def test_sticky_index_transaction():
    doc = Doc()
    text = doc.get("text", type=Text)
    sticky_index = text.sticky_index(0, Assoc.BEFORE)
    data = sticky_index.to_json()
    sticky_index = StickyIndex.from_json(data)

    with pytest.raises(RuntimeError) as excinfo:
        sticky_index.get_index()

    assert str(excinfo.value) == "No transaction available"

    with doc.transaction() as txn:
        idx = sticky_index.get_index(txn)

    assert idx == 0
