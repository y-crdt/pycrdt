from __future__ import annotations

import pytest
from pycrdt import Array, Doc, Map, TypedArray, TypedDoc, TypedMap


def test_typed_init():
    doc0 = Doc()

    typed_doc0 = TypedDoc(doc0)
    assert typed_doc0._ is doc0

    typed_doc1 = TypedDoc(typed_doc0)
    assert typed_doc1._ is doc0

    array0 = doc0.get("array0", type=Array)
    map0 = doc0.get("map0", type=Map)

    typed_array0 = TypedArray(array0)
    assert typed_array0._ is array0

    typed_array1 = TypedArray(typed_array0)
    assert typed_array1._ is array0

    typed_map0 = TypedMap(map0)
    assert typed_map0._ is map0

    typed_map1 = TypedMap(typed_map0)
    assert typed_map1._ is map0


class MyTypedArray(TypedArray[bool]):
    type: bool


class MyTypedMap0(TypedMap):
    k0: bool


class MyTypedMap1(TypedMap):
    key0: str
    key1: int
    key2: MyTypedMap0
    key3: Array[int]
    key4: str | int


class MySubTypedDoc(TypedDoc):
    my_typed_map: MyTypedMap1


class MyTypedDoc(MySubTypedDoc):
    my_array: MyTypedArray


def test_typed():
    doc = Doc()
    assert MyTypedDoc(doc)._ is doc

    my_typed_doc = MyTypedDoc()
    my_typed_doc.my_typed_map.key0 = "foo"

    with pytest.raises(TypeError) as excinfo:
        my_typed_doc.my_typed_map.key0 = 3
    assert str(excinfo.value) == (
        "Incompatible types in assignment (expression has type "
        "\"<class 'str'>\", variable has type \"<class 'int'>\")"
    )

    my_typed_doc.my_typed_map.key1 = 123
    my_typed_doc.my_typed_map.key2 = MyTypedMap0()
    my_typed_doc.my_typed_map.key2.k0 = False
    my_typed_doc.my_typed_map.key3 = Array([1, 2, 3])
    my_typed_doc.my_typed_map.key4 = "bar"
    assert my_typed_doc.my_typed_map.key4 == "bar"

    with pytest.raises(AttributeError) as excinfo:
        my_typed_doc.my_typed_map.wrong_key = "foo"
    assert str(excinfo.value) == '"<class \'test_typed.MyTypedMap1\'>" has no attribute "wrong_key"'

    with pytest.raises(AttributeError) as excinfo:
        my_typed_doc.my_typed_map.wrong_key
    assert str(excinfo.value) == '"<class \'test_typed.MyTypedMap1\'>" has no attribute "wrong_key"'

    assert len(my_typed_doc.my_array) == 0
    my_typed_doc.my_array.append(True)
    assert len(my_typed_doc.my_array) == 1
    assert my_typed_doc.my_array[0] is True
    my_typed_doc.my_array[0] = False
    assert my_typed_doc.my_array[0] is False
    my_typed_doc.my_array.extend([True])

    update = my_typed_doc._.get_update()

    my_other_doc = Doc()
    my_other_doc.apply_update(update)
    my_map = my_other_doc.get("my_typed_map", type=Map)
    assert my_map.to_py() == {
        "key0": "foo",
        "key1": 123.0,
        "key2": {"k0": False},
        "key3": [1.0, 2.0, 3.0],
        "key4": "bar",
    }
    my_array = my_other_doc.get("my_array", type=Array[bool])
    assert my_array.to_py() == [False, True]
