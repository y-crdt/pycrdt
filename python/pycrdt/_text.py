from __future__ import annotations

from typing import TYPE_CHECKING, Any, Callable, Iterator, cast

from ._base import BaseEvent, Sequence, base_types, event_types
from ._pycrdt import Subscription
from ._pycrdt import Text as _Text
from ._pycrdt import TextEvent as _TextEvent

if TYPE_CHECKING:
    from ._doc import Doc


class Text(Sequence):
    """
    A shared data type used for collaborative text editing, similar to a Python `str`.
    """

    _prelim: str | None
    _integrated: _Text | None

    def __init__(
        self,
        init: str | None = None,
        *,
        _doc: Doc | None = None,
        _integrated: _Text | None = None,
    ) -> None:
        """
        Creates a text with an optional initial value:
        ```py
        text = Text("Hello, World!")
        ```

        Args:
            init: The string from which to initialize the text.
        """
        super().__init__(
            init=init,
            _doc=_doc,
            _integrated=_integrated,
        )

    def _init(self, value: str | None) -> None:
        if value is None:
            return
        with self.doc.transaction() as txn:
            self.integrated.insert(txn._txn, 0, value)

    def _get_or_insert(self, name: str, doc: Doc) -> _Text:
        assert doc._txn is not None
        assert doc._txn._txn is not None
        return doc._doc.get_or_insert_text(doc._txn._txn, name)

    def __iter__(self) -> Iterator[str]:
        """
        ```py
        Doc()["text"] = text = Text("***")
        for character in text:
            assert character == "*"
        ```

        Returns:
            An iterable over the characters of the text.
        """
        return iter(str(self))

    def __contains__(self, item: str) -> bool:
        """
        Checks if the given string is in the text:
        ```py
        Doc()["text"] = text = Text("Hello, World!")
        assert "World" in text
        ```

        Args:
            item: The string to look for in the text.

        Returns:
            True if the string was found.
        """
        return item in str(self)

    def __len__(self) -> int:
        """
        ```py
        Doc()["text"] = text = Text("Hello")
        assert len(text) == 5
        ```

        Returns:
            The length of the text.
        """
        with self.doc.transaction() as txn:
            return self.integrated.len(txn._txn)

    def __str__(self) -> str:
        """
        Returns:
            The text as a Python `str`.
        """
        with self.doc.transaction() as txn:
            return self.integrated.get_string(txn._txn)

    def to_py(self) -> str | None:
        """
        Returns:
            The text as a Python `str`.
        """
        if self._integrated is None:
            return self._prelim
        return str(self)

    def __iadd__(self, value: str) -> Text:
        """
        Concatenates a string to the text:
        ```py
        Doc()["text"] = text = Text("Hello")
        text += ", World!"
        assert str(text) == "Hello, World!"
        ```

        Args:
            value: The string to concatenate.

        Returns:
            The concatenated text.
        """
        with self.doc.transaction() as txn:
            self._forbid_read_transaction(txn)
            self.integrated.insert(txn._txn, len(self), value)
            return self

    def _check_slice(self, key: slice) -> tuple[int, int]:
        if key.step is not None:
            raise RuntimeError("Step not supported")
        if key.start is None:
            start = 0
        elif key.start < 0:
            raise RuntimeError("Negative start not supported")
        else:
            start = key.start
        if key.stop is None:
            stop = len(self)
        elif key.stop < 0:
            raise RuntimeError("Negative stop not supported")
        else:
            stop = key.stop
        return start, stop

    def __delitem__(self, key: int | slice) -> None:
        """
        Removes the characters at the given index or slice:
        ```py
        Doc()["text"] = text = Text("Hello, World!")
        del text[5]
        assert str(text) == "Hello World!"
        del text[5:]
        assert str(text) == "Hello"
        ```

        Args:
            key: The index or the slice of the characters to remove.

        Raises:
            RuntimeError: Step not supported.
            RuntimeError: Negative start not supported.
            RuntimeError: Negative stop not supported.
        """
        with self.doc.transaction() as txn:
            self._forbid_read_transaction(txn)
            if isinstance(key, int):
                self.integrated.remove_range(txn._txn, key, 1)
            elif isinstance(key, slice):
                start, stop = self._check_slice(key)
                length = stop - start
                if length > 0:
                    self.integrated.remove_range(txn._txn, start, length)
            else:
                raise RuntimeError(f"Index not supported: {key}")

    def __getitem__(self, key: int | slice) -> str:
        """
        Gets the characters at the given index or slice:
        ```py
        Doc()["text"] = text = Text("Hello, World!")
        assert text[:5] == "Hello"
        ```

        Returns:
            The characters at the given index or slice.
        """
        value = str(self)
        return value[key]

    def __setitem__(self, key: int | slice, value: str) -> None:
        """
        Replaces the characters at the given index or slice with new characters:
        ```py
        Doc()["text"] = text = Text("Hello, World!")
        text[7:12] = "Brian"
        assert text == "Hello, Brian!"
        ```

        Args:
            key: The index or slice of the characters to replace.
            value: The new characters to set.

        Raises:
            RuntimeError: Step not supported.
            RuntimeError: Negative start not supported.
            RuntimeError: Negative stop not supported.
            RuntimeError: Single item assigned value must have a length of 1.
        """
        with self.doc.transaction() as txn:
            self._forbid_read_transaction(txn)
            if isinstance(key, int):
                value_len = len(value)
                if value_len != 1:
                    raise RuntimeError(
                        f"Single item assigned value must have a length of 1, not {value_len}"
                    )
                del self[key]
                self.integrated.insert(txn._txn, key, value)
            elif isinstance(key, slice):
                start, stop = self._check_slice(key)
                length = stop - start
                if length > 0:
                    self.integrated.remove_range(txn._txn, start, length)
                self.integrated.insert(txn._txn, start, value)
            else:
                raise RuntimeError(f"Index not supported: {key}")

    def clear(self) -> None:
        """Remove the entire range of characters."""
        del self[:]

    def insert(self, index: int, value: str, attrs: dict[str, Any] | None = None) -> None:
        """
        Inserts a string at a given index in the text, with optional attributes.
        ```py
        Doc()["text"] = text = Text("Hello World!")
        text.insert(5, ",")
        assert text == "Hello, World!"
        ```

        Args:
            index: The index where to insert the string.
            value: The string to insert in the text.
            attrs: The formatting of attributes to apply.
        """
        with self.doc.transaction() as txn:
            self._forbid_read_transaction(txn)
            self.integrated.insert(
                txn._txn, index, value, iter(attrs.items()) if attrs is not None else None
            )

    def insert_embed(self, index: int, value: Any, attrs: dict[str, Any] | None = None) -> None:
        """
        Insert a value as an embed at a given index in the text, with optional attributes.

        Args:
            index: The index where to insert the embedded content.
            value: The value to embed.
            attrs: The formatting attributes to apply.
        """
        with self.doc.transaction() as txn:
            self._forbid_read_transaction(txn)
            self.integrated.insert_embed(
                txn._txn, index, value, iter(attrs.items()) if attrs is not None else None
            )

    def format(self, start: int, stop: int, attrs: dict[str, Any]) -> None:
        """
        Applies formatting attributes to a section of text between given start and stop indices.

        Args:
            start: The index at which to start applying attributes (included).
            stop: The index at which to stop applying attributes (excluded).
            attrs: The formatting attributes to apply.
        """
        with self.doc.transaction() as txn:
            self._forbid_read_transaction(txn)
            start, stop = self._check_slice(slice(start, stop))
            length = stop - start
            if length > 0:
                self.integrated.format(txn._txn, start, length, iter(attrs.items()))

    def diff(self) -> list[tuple[Any, dict[str, Any] | None]]:
        """
        Returns:
            A list of formatted chunks that the current text corresponds to.
                Each list item is a tuple containing the chunk's content and formatting attributes.
                The content is usually the text as a string, but may be other data for embedded
                objects.
        """
        with self.doc.transaction() as txn:
            return self.integrated.diff(txn._txn)

    def observe(self, callback: Callable[[TextEvent], None]) -> Subscription:
        """
        Subscribes a callback to be called with the text event.

        Args:
            callback: The callback to call with the [TextEvent][pycrdt.TextEvent].
        """
        return super().observe(cast(Callable[[BaseEvent], None], callback))


class TextEvent(BaseEvent):
    """
    A text change event.

    Attributes:
        target (Text): The changed text.
        delta (list[dict[str, Any]]): A list of items describing the changes.
        path (list[int | str]): A list with the indices pointing to the text that was changed.
    """

    __slots__ = "target", "delta", "path"


base_types[_Text] = Text
event_types[_TextEvent] = TextEvent
