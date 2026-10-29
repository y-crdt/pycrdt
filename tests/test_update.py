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


def test_whole_numbers_encode_as_lib0_integers():
    # lib0 Any tags: 125 integer (varint), 124 float32, 123 float64. Yjs writes every
    # whole number up to 31 bits as an integer, whether it was written as 3 or 3.0.
    doc = Doc(client_id=1)
    map0 = doc.get("map", type=Map)
    map0["int"] = 3
    map0["whole"] = 14.0
    map0["half"] = 0.5
    map0["wide"] = 2**31
    update = doc.get_update()
    assert b"\x03int\x01\x7d\x03" in update
    assert b"\x05whole\x01\x7d\x0e" in update
    assert b"\x04half\x01\x7c" in update
    assert b"\x04wide\x01\x7c" in update
    remote = Doc()
    remote.apply_update(update)
    assert remote.get("map", type=Map).to_py() == {
        "int": 3.0,
        "whole": 14.0,
        "half": 0.5,
        "wide": 2147483648.0,
    }
