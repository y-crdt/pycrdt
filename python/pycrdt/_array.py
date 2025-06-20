from __future__ import annotations

from typing import TYPE_CHECKING, Any, Callable, Generic, TypeVar, cast, overload

from ._base import BaseDoc, BaseEvent, BaseType, Sequence, Typed, base_types, event_types
from ._pycrdt import Array as _Array
from ._pycrdt import ArrayEvent as _ArrayEvent
from ._pycrdt import Subscription

if TYPE_CHECKING:
    from ._doc import Doc

T = TypeVar("T")


class Array(Sequence, Generic[T]):
    """
    A collection used to store data in an indexed sequence structure, similar to a Python `list`.
    """

    _prelim: list[T] | None
    _integrated: _Array | None

    def __init__(
        self,
        init: list[T] | None = None,
        *,
        _doc: Doc | None = None,
        _integrated: _Array | None = None,
    ) -> None:
        """
        Creates an array with an optional initial value:
        ```py
        array0 = Array()
        array1 = Array(["foo", 3, array0])
        ```

        Args:
            init: The list from which to initialize the array.
        """
        super().__init__(
            init=init,
            _doc=_doc,
            _integrated=_integrated,
        )

    def _init(self, value: list[T] | None) -> None:
        if value is None:
            return
        with self.doc.transaction():
            for i, v in enumerate(value):
                self._set(i, v)

    def _set(self, index: int, value: T) -> None:
        with self.doc.transaction() as txn:
            self._forbid_read_transaction(txn)
            if isinstance(value, BaseDoc):
                # subdoc
                self.integrated.insert_doc(txn._txn, index, value._doc)
            elif isinstance(value, BaseType):
                # shared type
                assert txn._txn is not None
                self._do_and_integrate("insert", value, txn._txn, index)
            else:
                # primitive type
                self.integrated.insert(txn._txn, index, value)

    def _get_or_insert(self, name: str, doc: Doc) -> _Array:
        assert doc._txn is not None
        assert doc._txn._txn is not None
        return doc._doc.get_or_insert_array(doc._txn._txn, name)

    def __len__(self) -> int:
        """
        ```py
        Doc()["array"] = array = Array([2, 3, 0])
        assert len(array) == 3
        ```

        Returns:
            The length of the array.
        """
        with self.doc.transaction() as txn:
            return self.integrated.len(txn._txn)

    def append(self, value: T) -> None:
        """
        Appends an item to the array.

        Args:
            value: The item to append to the array.
        """
        with self.doc.transaction():
            self += [value]

    def extend(self, value: list[T]) -> None:
        """
        Extends the array with a list of items.

        Args:
            value: The items that will extend the array.
        """
        with self.doc.transaction():
            self += value

    def clear(self) -> None:
        """
        Removes all items from the array.
        """
        del self[:]

    def insert(self, index: int, object: T) -> None:
        """
        Inserts an item at a given index in the array.

        Args:
            index: The index where to insert the item.
            object: The item to insert in the array.
        """
        self[index:index] = [object]

    def pop(self, index: int = -1) -> T:
        """
        Removes the item at the given index from the array, and returns it.
        If no index is passed, removes and returns the last item.

        Args:
            index: The optional index of the item to pop.

        Returns:
            The item at the given index, or the last item.
        """
        with self.doc.transaction():
            index = self._check_index(index)
            res = self[index]
            if isinstance(res, BaseType):
                res = res.to_py()
            del self[index]
            return res

    def move(self, source_index: int, destination_index: int) -> None:
        """
        Moves an item in the array from a source index to a destination index.

        Args:
            source_index: The index of the item to move.
            destination_index: The index where the item will be inserted.
        """
        with self.doc.transaction() as txn:
            self._forbid_read_transaction(txn)
            source_index = self._check_index(source_index)
            destination_index = self._check_index(destination_index)
            self.integrated.move_to(txn._txn, source_index, destination_index)

    def __add__(self, value: list[T]) -> Array[T]:
        """
        Extends the array with a list of items:
        ```py
        Doc()["array"] = array = Array(["foo"])
        array += ["bar", "baz"]
        assert array.to_py() == ["foo", "bar", "baz"]
        ```

        Args:
            value: The items that will extend the array.

        Returns:
            The extended array.
        """
        with self.doc.transaction():
            length = len(self)
            self[length:length] = value
            return self

    def __radd__(self, value: list[T]) -> Array[T]:
        """
        Prepends a list of items to the array:
        ```py
        Doc()["array"] = array = Array(["bar", "baz"])
        array = ["foo"] + array
        assert array.to_py() == ["foo", "bar", "baz"]
        ```

        Args:
            value: The list of items to prepend.

        Returns:
            The prepended array.
        """
        with self.doc.transaction():
            self[0:0] = value
            return self

    @overload
    def __setitem__(self, key: int, value: T) -> None: ...

    @overload
    def __setitem__(self, key: slice, value: list[T]) -> None: ...

    def __setitem__(self, key, value):
        """
        Replaces the item at the given index with a new item:
        ```py
        Doc()["array"] = array = Array(["foo", "bar"])
        array[1] = "baz"
        assert array.to_py() == ["foo", "baz"]
        ```

        Args:
            key: The index of the item to replace.
            value: The new item to set.

        Raises:
            RuntimeError: Index must be of type integer.
        """
        with self.doc.transaction():
            if isinstance(key, int):
                key = self._check_index(key)
                del self[key]
                self[key:key] = [value]
            elif isinstance(key, slice):
                if key.step is not None:
                    raise RuntimeError("Step not supported")
                if key.start != key.stop:
                    raise RuntimeError("Start and stop must be equal")
                if key.start > len(self) or key.start < 0:
                    raise RuntimeError("Index out of range")
                for i, v in enumerate(value):
                    self._set(i + key.start, v)
            else:
                raise RuntimeError("Index must be of type integer")

    def _check_index(self, idx: int) -> int:
        if not isinstance(idx, int):
            raise RuntimeError("Index must be of type integer")
        length = len(self)
        if idx < 0:
            idx += length
        if idx < 0 or idx >= length:
            raise IndexError("Array index out of range")
        return idx

    def __delitem__(self, key: int | slice) -> None:
        """
        Removes the item at the given index from the array:
        ```py
        Doc()["array"] = array = Array(["foo", "bar", "baz"])
        del array[2]
        assert array.to_py() == ["foo", "bar"]
        ```

        Args:
            key: The index of the item to remove.

        Raises:
            RuntimeError: Array indices must be integers or slices.
        """
        with self.doc.transaction() as txn:
            self._forbid_read_transaction(txn)
            if isinstance(key, int):
                key = self._check_index(key)
                self.integrated.remove_range(txn._txn, key, 1)
            elif isinstance(key, slice):
                if key.step is not None:
                    raise RuntimeError("Step not supported")
                if key.start is None:
                    i = 0
                elif key.start < 0:
                    raise RuntimeError("Negative start not supported")
                else:
                    i = key.start
                if key.stop is None:
                    n = len(self) - i
                elif key.stop < 0:
                    raise RuntimeError("Negative stop not supported")
                else:
                    n = key.stop - i
                self.integrated.remove_range(txn._txn, i, n)
            else:
                raise TypeError(
                    f"Array indices must be integers or slices, not {type(key).__name__}"
                )

    @overload
    def __getitem__(self, key: int) -> T: ...

    @overload
    def __getitem__(self, key: slice) -> list[T]: ...

    def __getitem__(self, key):
        """
        Gets the item at the given index:
        ```py
        Doc()["array"] = array = Array(["foo", "bar", "baz"])
        assert array[1] == "bar"
        ```

        Returns:
            The item at the given index.
        """
        with self.doc.transaction() as txn:
            if isinstance(key, int):
                key = self._check_index(key)
                return self._maybe_as_type_or_doc(self.integrated.get(txn._txn, key))
            elif isinstance(key, slice):
                i0 = 0 if key.start is None else key.start
                i1 = len(self) if key.stop is None else key.stop
                step = 1 if key.step is None else key.step
                return [self[i] for i in range(i0, i1, step)]

    def __iter__(self) -> ArrayIterator:
        """
        ```py
        Doc()["array"] = array = Array(["foo", "foo"])
        for value in array:
            assert value == "foo"
        ```
        Returns:
            An iterable over the items of the array.
        """
        return ArrayIterator(self)

    def __contains__(self, item: T) -> bool:
        """
        Checks if the given item is in the array:
        ```py
        Doc()["array"] = array = Array(["foo", "bar"])
        assert "baz" not in array
        ```

        Args:
            item: The item to look for in the array.

        Returns:
            True if the item was found.
        """
        return item in [value for value in self]

    def __str__(self) -> str:
        """
        ```py
        Doc()["array"] = array = Array([2, 3, 0])
        assert str(array) == "[2,3,0]"
        ```

        Returns:
            The string representation of the array.
        """
        with self.doc.transaction() as txn:
            return self.integrated.to_json(txn._txn)

    def to_py(self) -> list[T] | None:
        """
        Recursively converts the array's items to Python objects, and
        returns them in a list. If the array was not yet inserted in a document,
        returns `None` if the array was not initialized.

        Returns:
            The array recursively converted to Python objects, or `None`.
        """
        if self._integrated is None:
            py = self._prelim
            if py is None:
                return None
        else:
            py = [value for value in self]
        for idx, val in enumerate(py):
            if isinstance(val, BaseType):
                py[idx] = val.to_py()
        return py

    def observe(self, callback: Callable[[ArrayEvent], None]) -> Subscription:
        """
        Subscribes a callback to be called with the array event.

        Args:
            callback: The callback to call with the [ArrayEvent][pycrdt.ArrayEvent].
        """
        return super().observe(cast(Callable[[BaseEvent], None], callback))


class ArrayEvent(BaseEvent):
    """
    An array change event.

    Attributes:
        target (Array): The changed array.
        delta (list[dict[str, Any]]): A list of items describing the changes.
        path (list[int | str]): A list with the indices pointing to the array that was changed.
    """

    __slots__ = "target", "delta", "path"


class ArrayIterator:
    def __init__(self, array: Array):
        self.array = array
        self.length = len(array)
        self.idx = 0

    def __iter__(self) -> ArrayIterator:
        return self  # pragma: nocover

    def __next__(self) -> Any:
        if self.idx == self.length:
            raise StopIteration

        res = self.array[self.idx]
        self.idx += 1
        return res


class TypedArray(Typed, Generic[T]):
    """
    A container for an [Array][pycrdt.Array.__init__] where values have types that can be
    other typed containers, e.g. a [TypedMap][pycrdt.TypedMap]. The subclass of `TypedArray[T]`
    must have a special `type: T` annotation where `T` is the same type.
    The underlying `Array` can be accessed with the special `_` attribute.

    ```py
    from pycrdt import Array, TypedArray, TypedDoc, TypedMap

    class MyMap(TypedMap):
        name: str
        toggle: bool
        nested: Array[bool]

    class MyArray(TypedArray[MyMap]):
        type: MyMap

    class MyDoc(TypedDoc):
        array0: MyArray

    doc = MyDoc()

    map0 = MyMap()
    doc.array0.append(map0)
    map0.name = "foo"
    map0.toggle = True
    map0.nested = Array([True, False])

    print(doc.array0._.to_py())
    # [{'name': 'foo', 'toggle': True, 'nested': [True, False]}]
    print(doc.array0[0].name)
    # foo
    print(doc.array0[0].toggle)
    # True
    print(doc.array0[0].nested.to_py())
    # [True, False]
    ```
    """

    type: T
    _: Array

    def __init__(self, array: TypedArray | Array | None = None) -> None:
        super().__init__()
        if array is None:
            array = Array()
        elif isinstance(array, TypedArray):
            array = array._
        self._ = array
        self.__dict__["type"] = self.__dict__["annotations"]["type"]

    def __getitem__(self, key: int) -> T:
        return self.__dict__["type"](self._[key])

    def __setitem__(self, key: int, value: T) -> None:
        item = value._ if isinstance(value, Typed) else value
        self._[key] = item

    def append(self, value: T) -> None:
        item = value._ if isinstance(value, Typed) else value
        self._.append(item)

    def extend(self, value: list[T]) -> None:
        items = [item._ if isinstance(item, Typed) else item for item in value]
        self._.extend(items)

    def __len__(self) -> int:
        return len(self._)


base_types[_Array] = Array
event_types[_ArrayEvent] = ArrayEvent
