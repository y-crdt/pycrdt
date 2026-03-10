import json
from functools import partial

import pytest
from anyio import TASK_STATUS_IGNORED, Event, create_task_group
from anyio.abc import TaskStatus
from pycrdt import Array, Doc, Map, Text

pytestmark = pytest.mark.anyio


def callback(events, event):
    events.append(event)


def callback_deep(_events, events):
    _events.append(events)


def test_binary_entry():
    doc = Doc({"m": Map({"bytes": b"012"})})
    assert doc["m"]["bytes"] == b"012"


def test_str():
    doc = Doc()
    map2 = Map({"key2": "val2"})
    array1 = Array([0, 1, map2])
    map0 = Map({"key1": array1})
    doc["map"] = map0
    assert str(map0) == '{"key1":[0,1,{"key2":"val2"}]}'


def test_nested():
    doc = Doc()
    text1 = Text("my_text")
    array1 = Array([0, "foo", 2])
    map1 = Map({"foo": [3, 4, 5], "bar": "baz"})
    map0 = Map({"text1": text1, "array1": array1, "map1": map1})
    doc["map"] = map0
    ref = {
        "text1": "my_text",
        "array1": [0, "foo", 2],
        "map1": {"bar": "baz", "foo": [3, 4, 5]},
    }
    assert json.loads(str(map0)) == ref


def test_api():
    doc = Doc()
    n = 5
    keys = [f"key{i}" for i in range(n)]
    values = [f"value{i}" for i in range(n)]
    items = {keys[i]: values[i] for i in range(n)}
    map0 = Map(items)
    doc["map0"] = map0
    with pytest.raises(RuntimeError) as excinfo:
        map0[1] = 2
    assert str(excinfo.value) == "Key must be of type string"
    key_list = list(map0.keys())
    value_list = list(map0.values())
    assert len(key_list) == n
    assert len(value_list) == n
    # Yrs Map doesn't keep order
    assert {key for key in map0} == set(keys)
    assert set(key_list) == set(keys)
    assert set(value_list) == set(values)
    assert dict(map0.items()) == items
    assert "key0" in map0
    assert "key5" not in map0
    assert map0.get("key1") == "value1"
    assert map0.get("key5") is None
    assert map0.get("key5", "value5") == "value5"
    assert map0.pop("key0") == "value0"
    assert "key0" not in map0
    with pytest.raises(KeyError) as excinfo:
        del map0["key0"]
    assert str(excinfo.value) == "'key0'"
    with pytest.raises(KeyError) as excinfo:
        map0.pop("key5")
    assert map0.pop("key5", "value5") == "value5"
    with pytest.raises(RuntimeError) as excinfo:
        del map0[0]
    assert str(excinfo.value) == "Key must be of type string"
    map0.clear()
    assert len(map0) == 0

    # pop
    doc = Doc()
    map0 = Map({"foo": 1, "bar": 2})
    doc["map0"] = map0
    v = map0.pop("foo")
    assert v == 1
    assert str(map0) == '{"bar":2}'
    v = map0.pop("bar")
    assert v == 2
    assert str(map0) == "{}"

    # pop nested
    nested_doc = Doc()
    nested_doc["text"] = Text("text in subdoc")
    map0.update({"baz": nested_doc})
    v = map0.pop("baz")
    assert str(v["text"]) == "text in subdoc"
    assert str(map0) == "{}"

    nested_text = Text("abc")
    map0.update({"baz": nested_text})
    v = map0.pop("baz")
    assert v == "abc"
    assert str(map0) == "{}"

    nested_array = Array([1, 2, 3])
    map0.update({"baz": nested_array})
    v = map0.pop("baz")
    assert v == [1.0, 2.0, 3.0]
    assert str(map0) == "{}"

    nested_map = Map({"x": "y"})
    map0.update({"baz": nested_map})
    v = map0.pop("baz")
    assert v == {"x": "y"}
    assert str(map0) == "{}"


def test_to_py():
    doc = Doc()
    submap = Map({"foo": "bar"})
    subarray = Array([0, submap])
    doc["map_"] = map_ = Map({"key0": "val0", "key1": subarray})
    assert map_.to_py() == {"key0": "val0", "key1": [0, {"foo": "bar"}]}


def test_prelim():
    map0 = Map({"0": 1})
    assert map0.to_py() == {"0": 1}

    map1 = Map()
    assert map1.to_py() is None


def test_observe():
    doc = Doc()
    doc["map0"] = map0 = Map()
    doc["map1"] = map1 = Map()
    events = []

    sub = map0.observe(partial(callback, events))
    map0["0"] = 0
    assert (
        str(events[0])
        == """{target: {"0":0}, keys: {'0': {'action': 'add', 'newValue': 0.0}}, path: []}"""
    )
    events.clear()
    map0.unobserve(sub)
    map0["1"] = 1
    assert events == []

    deep_events = []
    sub = map1.observe_deep(partial(callback_deep, deep_events))
    map1["1"] = 1
    assert (
        str(deep_events[0][0])
        == """{target: {"1":1}, keys: {'1': {'action': 'add', 'newValue': 1.0}}, path: []}"""
    )
    deep_events.clear()
    map1.unobserve(sub)
    map1["0"] = 0
    assert deep_events == []


async def test_iterate_events():
    doc = Doc()
    map0 = doc.get("map0", type=Map)
    keys = []

    async def iterate_events(done_event, *, task_status: TaskStatus[None] = TASK_STATUS_IGNORED):
        async with map0.events() as events:
            task_status.started()
            idx = 0
            async for event in events:
                print(event)
                keys.append(event.keys)
                if idx == 1:
                    done_event.set()
                    return
                idx += 1

    async with create_task_group() as tg:
        done_event = Event()
        await tg.start(iterate_events, done_event)
        map0["key0"] = "Hello"
        map0["key1"] = ", World!"
        await done_event.wait()
        map0["key2"] = " Goodbye."

    assert len(keys) == 2
    assert keys[0] == {"key0": {"action": "add", "newValue": "Hello"}}
    assert keys[1] == {"key1": {"action": "add", "newValue": ", World!"}}


def test_tuple_handling():
    """Test that tuples in nested dictionaries are properly preserved.

    Related to issue #368 where tuples in nested dictionaries were being
    converted to None values.
    """
    doc = Doc()
    map0 = doc.get("map0", type=Map)

    # Test basic tuple handling
    test_data = {
        "simple_tuple": (1, 2, 3),
        "mixed_tuple": (1, "hello", True, None),
        "empty_tuple": (),
        "single_tuple": (42,),
        "nested_dict": {"position": (5, 0), "range": (10, 20), "content": "hello"},
    }

    map0.update(test_data)

    result = map0.to_py()

    # Tuples should be converted to lists
    assert result["simple_tuple"] == [1.0, 2.0, 3.0]
    assert result["mixed_tuple"] == [1.0, "hello", True, None]
    assert result["empty_tuple"] == []
    assert result["single_tuple"] == [42.0]

    # Nested dictionary with tuples
    nested = result["nested_dict"]
    assert nested["position"] == [5.0, 0.0]
    assert nested["range"] == [10.0, 20.0]
    assert nested["content"] == "hello"

    # Test direct assignment
    map0["direct_tuple"] = (100, 200)
    assert map0["direct_tuple"] == [100.0, 200.0]

    # Test the original issue case
    selection_data = {"selection": {"start": (5, 0), "end": (10, 0), "content": "hello"}}
    map0.update(selection_data)
    selection_result = map0["selection"]

    assert selection_result["start"] == [5.0, 0.0]
    assert selection_result["end"] == [10.0, 0.0]
    assert selection_result["content"] == "hello"
