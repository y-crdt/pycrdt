from typing import TypedDict, cast

import pytest
from pycrdt import Array, Doc, Map, Text, TypedArray, TypedMap, TypedDoc


@pytest.mark.mypy_testing
def mypy_test_array():
    doc = Doc[Array[int]]()
    array0 = doc.get("array0", type=Array)
    array0.append(0)
    array0.append("foo")  # E: Argument 1 to "append" of "Array" has incompatible type "str"; expected "int"  [arg-type]
    doc.get("array1", type=Array[str])  # E: Argument "type" to "get" of "Doc" has incompatible type "type[pycrdt._array.Array[str]]"; expected "type[pycrdt._array.Array[int]]"


@pytest.mark.mypy_testing
def mypy_test_uniform_map():
    doc = Doc[Map[bool]]()
    map0 = doc.get("map0", type=Map)
    map0["foo"] = True
    map0["foo"] = 3  # E: Incompatible types in assignment (expression has type "int", target has type "bool")
    v0: str = map0.pop("foo")  # E: Incompatible types in assignment (expression has type "bool", variable has type "str")
    v1: bool = map0.pop("foo")


@pytest.mark.mypy_testing
def mypy_test_typed_map():
    doc = Doc[Map]()

    MyMap = TypedDict(
        "MyMap",
        {
            "name": str,
            "toggle": bool,
            "nested": Array[bool],
        },
    )
    map0 = cast(MyMap, doc.get("map0", type=Map))
    map0["name"] = "foo"
    map0["toggle"] = False
    map0["toggle"] = 3  # E: Value of "toggle" has incompatible type "int"; expected "bool"
    array0 = Array([1, 2, 3])
    map0["nested"] = array0  # E: Value of "nested" has incompatible type "Array[int]"; expected "Array[bool]"
    array1 = Array([False, True])
    map0["nested"] = array1
    v0: str = map0["name"]
    v1: str = map0["toggle"]  # E: Incompatible types in assignment (expression has type "bool", variable has type "str")
    v2: bool = map0["toggle"]
    map0["key0"]  # E: TypedDict "MyMap" has no key "key0"


@pytest.mark.mypy_testing
def mypy_test_uniform_doc():
    doc = Doc[Text]()
    doc.get("text0", type=Text)
    doc.get("array0", type=Array)  # E: Argument "type" to "get" of "Doc" has incompatible type "type[pycrdt._array.Array[Any]]"; expected "type[Text]"
    doc.get("Map0", type=Map)  # E:  Argument "type" to "get" of "Doc" has incompatible type "type[pycrdt._map.Map[Any]]"; expected "type[Text]"


@pytest.mark.mypy_testing
def mypy_test_typed_doc():
    MyMap = TypedDict(
        "MyMap",
        {
            "name": str,
            "toggle": bool,
            "nested": Array[bool],
        },
    )

    MyDoc = TypedDict(
        "MyDoc",
        {
            "text0": Text,
            "array0": Array[int],
            "map0": MyMap,
        }
    )
    doc = cast(MyDoc, Doc())
    map0 = cast(MyMap, Map())
    doc["map0"] = map0
    doc["map0"] = Array()  # E: Value of "map0" has incompatible type "Array[Never]"; expected "MyMap"
    doc["map0"] = Map()  # E: Value of "map0" has incompatible type "Map[Never]"; expected "MyMap"
    doc["text0"] = Text()
    doc["array0"] = Array[bool]()  # E: Value of "array0" has incompatible type "Array[bool]"; expected "Array[int]"
    doc["array0"] = Array()


@pytest.mark.mypy_testing
def mypy_test_typed():

    class MyTypedArray(TypedArray[bool]):
        type: bool

    class MyTypedMap0(TypedMap):
        k0: bool

    class MyTypedMap1(TypedMap):
        key0: str
        key1: int
        key2: MyTypedMap0

    class MySubTypedDoc(TypedDoc):
        my_typed_map: MyTypedMap1

    class MyTypedDoc(MySubTypedDoc):
        my_array: MyTypedArray

    my_typed_doc = MyTypedDoc()
    my_typed_doc.my_typed_map.key0 = "foo"
    my_typed_doc.my_typed_map.key0 = 3  # E: Incompatible types in assignment (expression has type "int", variable has type "str")
    my_typed_doc.my_typed_map.key1 = 123
    my_typed_doc.my_typed_map.key1 = "bar"  # E: Incompatible types in assignment (expression has type "str", variable has type "int")
    my_typed_doc.my_typed_map.key2.k0 = 3  # E: Incompatible types in assignment (expression has type "int", variable has type "bool")
    my_typed_doc.my_typed_map.key2.k0 = False
    my_typed_doc.my_typed_map.key2.k1  # E: "MyTypedMap0" has no attribute "k1"
    my_typed_doc.my_array.append(True)
    my_typed_doc.my_array.append(2)  # E: Argument 1 to "append" of "TypedArray" has incompatible type "int"; expected "bool"
    my_typed_doc.my_wrong_root  # E: "MyTypedDoc" has no attribute "my_wrong_root"
    my_typed_doc.my_typed_map.wrong_key  # E: "MyTypedMap1" has no attribute "wrong_key"
