import pytest
from pycrdt import Doc, Map, Text, get_state, get_update, merge_updates


def test_update():
    data0 = Map({"key0": "val0"})
    doc0 = Doc()
    doc0["data"] = data0

    data1 = Map({"key1": "val1"})
    doc1 = Doc()
    doc1["data"] = data1

    update0 = doc0.get_update()
    update1 = doc1.get_update()

    del doc0
    del doc1
    state0 = get_state(update0)
    state1 = get_state(update1)

    update01 = get_update(update0, state1)
    update10 = get_update(update1, state0)

    # sync clients
    update0 = merge_updates(update0, update10)
    update1 = merge_updates(update1, update01)
    assert update0 == update1

    doc0 = Doc()
    data0 = doc0.get("data", type=Map)
    doc0.apply_update(update0)
    doc1 = Doc()
    data1 = doc1.get("data", type=Map)
    doc1.apply_update(update1)

    assert data0.to_py() == data1.to_py() == {"key0": "val0", "key1": "val1"}


def test_update_transaction():
    doc0 = Doc()
    text0 = doc0.get("test", type=Text)
    text0 += "Hello"

    update0 = doc0.get_update()

    text0 += " World!"
    update1 = doc0.get_update()
    del doc0

    doc1 = Doc()
    with doc1.transaction():
        doc1.apply_update(update0)
        doc1.apply_update(update1)

    assert str(doc1.get("test", type=Text)) == "Hello World!"


def test_merge_updates_invalid():
    with pytest.raises(TypeError):
        merge_updates("not an update")  # type: ignore[arg-type]

    with pytest.raises(ValueError) as excinfo:
        merge_updates(b"\xff")
    assert str(excinfo.value) == "Cannot merge updates"
