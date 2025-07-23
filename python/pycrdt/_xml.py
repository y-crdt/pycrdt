from __future__ import annotations

from typing import TYPE_CHECKING, Iterator, overload

from ._base import BaseEvent, BaseType, base_types, event_types
from ._pycrdt import XmlElement as _XmlElement
from ._pycrdt import XmlEvent as _XmlEvent
from ._pycrdt import XmlFragment as _XmlFragment
from ._pycrdt import XmlText as _XmlText

if TYPE_CHECKING:
    from typing import Any, Iterable, Mapping, Sized, TypeVar

    from ._doc import Doc

    T = TypeVar("T")


def _integrated_to_wrapper(
    doc: Doc, inner: _XmlText | _XmlElement | _XmlFragment
) -> XmlText | XmlElement | XmlFragment:
    if isinstance(inner, _XmlElement):
        return XmlElement(_doc=doc, _integrated=inner)
    if isinstance(inner, _XmlFragment):
        return XmlFragment(_doc=doc, _integrated=inner)
    return XmlText(_doc=doc, _integrated=inner)


def _check_slice(value: Sized, key: slice) -> tuple[int, int]:
    if key.step is not None:
        raise RuntimeError("Step not supported")
    if key.start is None:
        start = 0
    elif key.start < 0:
        raise RuntimeError("Negative start not supported")
    else:
        start = key.start
    if key.stop is None:
        stop = len(value)
    elif key.stop < 0:
        raise RuntimeError("Negative stop not supported")
    else:
        stop = key.stop
    return start, stop


class _XmlBaseMixin(BaseType):
    _integrated: _XmlElement | _XmlText | _XmlFragment | None

    @property
    def parent(self) -> XmlFragment | XmlElement | XmlText | None:
        """
        The parent of this node, if any.
        """
        inner = self.integrated.parent()
        if inner is None:
            return None
        return _integrated_to_wrapper(self.doc, inner)

    def __str__(self):
        with self.doc.transaction() as txn:
            return self.integrated.get_string(txn._txn)

    def __eq__(self, other: object):
        if not isinstance(other, _XmlBaseMixin):
            return False
        return self.integrated == other.integrated

    def __hash__(self) -> int:
        return hash(self.integrated)


class _XmlFragmentTraitMixin(_XmlBaseMixin):
    _integrated: _XmlElement | _XmlFragment | None

    @property
    def children(self) -> XmlChildrenView:
        """
        A list-like view into this object's child nodes.
        """
        return XmlChildrenView(self)


class _XmlTraitMixin(_XmlBaseMixin):
    _integrated: _XmlElement | _XmlText | None

    @property
    def attributes(self) -> XmlAttributesView:
        """
        A dict-like view into this object's attributes.
        """
        return XmlAttributesView(self)


class XmlFragment(_XmlFragmentTraitMixin):
    _prelim: list[XmlFragment | XmlElement | XmlText] | None
    _integrated: _XmlFragment | None

    def __init__(
        self,
        init: Iterable[XmlFragment | XmlElement | XmlText] | None = None,
        *,
        _doc: Doc | None = None,
        _integrated: _XmlFragment | None = None,
    ) -> None:
        super().__init__(
            init=list(init) if init is not None else None,
            _doc=_doc,
            _integrated=_integrated,
        )

    def to_py(self) -> None:
        raise ValueError("XmlFragment has no Python equivalent")

    def _get_or_insert(self, name: str, doc: Doc) -> Any:
        assert doc._txn is not None
        assert doc._txn._txn is not None
        return doc._doc.get_or_insert_xml_fragment(doc._txn._txn, name)

    def _init(self, value: list[XmlElement | str] | None) -> None:
        if value is None:
            return
        for obj in value:
            self.children.append(obj)


class XmlElement(_XmlFragmentTraitMixin, _XmlTraitMixin):
    _prelim: tuple[str, list[tuple[str, str]], list[str | XmlElement | XmlText]] | None
    _integrated: _XmlElement | None

    def __init__(
        self,
        tag: str | None = None,
        attributes: dict[str, str] | Iterable[tuple[str, str]] | None = None,
        contents: Iterable[XmlFragment | XmlElement | XmlText] | None = None,
        *,
        _doc: Doc | None = None,
        _integrated: _XmlElement | None = None,
    ) -> None:
        """
        Creates an XML element.

        Args:
            tag: The tag of the element (required).
            attributes: The optional attributes of the element.
            contents: The optional contents of the element.
        """
        if _integrated is not None:
            super().__init__(init=None, _doc=_doc, _integrated=_integrated)
            return

        if tag is None:
            raise ValueError("XmlElement: tag is required")

        if isinstance(attributes, dict):
            init_attrs = list(attributes.items())
        elif attributes is not None:
            init_attrs = list(attributes)
        else:
            init_attrs = []

        super().__init__(
            init=(
                tag,
                init_attrs,
                list(contents) if contents is not None else [],
            )
        )

    def to_py(self) -> None:
        raise ValueError("XmlElement has no Python equivalent")

    def _get_or_insert(self, name: str, doc: Doc) -> Any:
        raise ValueError("Cannot get an XmlElement from a doc, get an XmlFragment instead")

    def _init(
        self, value: tuple[str, list[tuple[str, str]], list[str | XmlElement | XmlText]] | None
    ):
        assert value is not None
        _, attrs, contents = value
        with self.doc.transaction():
            for k, v in attrs:
                self.attributes[k] = v
            for child in contents:
                self.children.append(child)

    @property
    def tag(self) -> str | None:
        """The element's tag, if any."""
        return self.integrated.tag()


class XmlText(_XmlTraitMixin):
    """
    A piece of text in an XML tree.

    This is similar to a [Text][pycrdt.Text], but instead of existing in a [Doc][pycrdt.Doc] on its
    own, it is a child of [XmlElement][pycrdt.XmlElement] or [XmlFragment][pycrdt.XmlFragment].
    """

    _prelim: str
    _integrated: _XmlText | None

    def __init__(
        self,
        init: str = "",
        *,
        _doc: Doc | None = None,
        _integrated: _XmlText | None = None,
    ) -> None:
        super().__init__(
            init=init,
            _doc=_doc,
            _integrated=_integrated,
        )

    def _get_or_insert(self, _name: str, _doc: Doc) -> Any:
        raise ValueError("Cannot get an XmlText from a doc - get an XmlFragment instead.")

    def to_py(self) -> str:
        if self._integrated is None:
            return self._prelim
        return str(self)

    def _init(self, value: str | None) -> None:  # pragma: no cover
        assert value is not None
        with self.doc.transaction() as txn:
            self.integrated.insert(txn._txn, 0, value)

    def __len__(self) -> int:
        with self.doc.transaction() as txn:
            return self.integrated.len(txn._txn)

    def __iadd__(self, value: str) -> XmlText:
        with self.doc.transaction():
            self.insert(len(self), value)
        return self

    def insert(self, index: int, value: str, attrs: Mapping[str, Any] | None = None) -> None:
        """
        Inserts text at a given index, with optional attributes.

        Args:
            index: The index at which to insert the text.
            value: The text to insert.
            attrs: The optional attributes.
        """
        with self.doc.transaction() as txn:
            self._forbid_read_transaction(txn)
            self.integrated.insert(
                txn._txn, index, value, iter(attrs.items()) if attrs is not None else iter([])
            )

    def insert_embed(self, index: int, value: Any, attrs: dict[str, Any] | None = None) -> None:
        """
        Insert an embed at a given index in the text, with optional attributes.

        Args:
            index: The index at which to insert the embed.
            value: The embed to insert.
            attrs: The optional attributes.
        """
        with self.doc.transaction() as txn:
            self._forbid_read_transaction(txn)
            _attrs = iter(attrs.items()) if attrs is not None else None
            if isinstance(value, BaseType):
                # shared type
                assert txn._txn is not None
                self._do_and_integrate("insert", value, txn._txn, index, _attrs)
            else:
                # primitive type
                self.integrated.insert_embed(
                    txn._txn, index, value, _attrs
                )

    def format(self, start: int, stop: int, attrs: dict[str, Any]) -> None:
        """
        Formats existing text with attributes.

        Args:
            start: The index at which to start applying the attributes (included).
            stop: The index at which to stop applying the attributes (excluded).
            attrs: The attributes to apply.
        """
        with self.doc.transaction() as txn:
            self._forbid_read_transaction(txn)
            start, stop = _check_slice(self, slice(start, stop))
            length = stop - start
            if length > 0:
                self.integrated.format(txn._txn, start, length, iter(attrs.items()))

    def diff(self) -> list[tuple[Any, dict[str, Any] | None]]:
        """
        Returns:
            A list of formatted chunks that the current text corresponds to.
                Each list item is a tuple containing the chunk's contents and formatting attributes.
                The contents is usually the text as a string, but may be other data for embedded
                objects.
        """
        with self.doc.transaction() as txn:
            return self.integrated.diff(txn._txn)

    def __delitem__(self, key: int | slice) -> None:
        with self.doc.transaction() as txn:
            self._forbid_read_transaction(txn)
            if isinstance(key, int):
                self.integrated.remove_range(txn._txn, key, 1)
            elif isinstance(key, slice):
                start, stop = _check_slice(self, key)
                length = stop - start
                if length > 0:
                    self.integrated.remove_range(txn._txn, start, length)
            else:
                raise TypeError(f"Index not supported: {key}")

    def clear(self) -> None:
        """Removes the entire range of characters."""
        del self[:]


class XmlEvent(BaseEvent):
    __slots__ = ["children_changed", "target", "path", "delta", "keys"]


class XmlAttributesView:
    """
    A list-like view into an [XmlFragment][pycrdt.XmlFragment] or [XmlElement][pycrdt.XmlElement]'s
    child nodes.

    Supports `len`, `in`, and getting, setting, and deleting by index. Iteration will iterate over
    key/value tuples.
    """

    inner: _XmlTraitMixin

    def __init__(self, inner: _XmlTraitMixin) -> None:
        self.inner = inner

    def get(self, key: str) -> Any | None:
        """
        Args:
            key: The name of the attribute to get.

        Returns:
            The value of the attribute, or `None` if there is no attribute with the given name.
        """
        with self.inner.doc.transaction() as txn:
            v = self.inner.integrated.attribute(txn._txn, key)
            if v is None:
                return None
            return v

    def __getitem__(self, key: str) -> Any:
        """
        Args:
            key: The name of the attribute to get.

        Raises:
            KeyError: Attribute does not exist.

        Returns:
            The attribute's value.
        """
        v = self.get(key)
        if v is None:
            raise KeyError(key)
        return v

    def __setitem__(self, key: str, value: Any) -> None:
        """
        Args:
            key: The name of the attribute to set.
            value: The value of the attribute.
        """
        with self.inner.doc.transaction() as txn:
            self.inner._forbid_read_transaction(txn)
            self.inner.integrated.insert_attribute(txn._txn, key, value)

    def __delitem__(self, key: str) -> None:
        """
        Args:
            key: The value of the attribute to delete.
        """
        with self.inner.doc.transaction() as txn:
            self.inner._forbid_read_transaction(txn)
            self.inner.integrated.remove_attribute(txn._txn, key)

    def __contains__(self, key: str) -> bool:
        """
        Args:
            key: The name of the attribute to check.

        Returns:
            `True` if the attribute with the given name exists.
        """
        return self.get(key) is not None

    def __len__(self) -> int:
        """
        Returns:
            The number of attributes.
        """
        with self.inner.doc.transaction() as txn:
            return len(self.inner.integrated.attributes(txn._txn))

    def __iter__(self) -> Iterable[tuple[str, Any]]:
        """
        Returns:
            An iterable over each attribute, as key/value tuples.
        """
        with self.inner.doc.transaction() as txn:
            return iter(self.inner.integrated.attributes(txn._txn))


class XmlChildrenView:
    """
    A list-like view into an [XmlFragment][pycrdt.XmlFragment] or [XmlElement][pycrdt.XmlElement]'s
    child nodes.

    Supports `iter`, `len`, and getting, setting, and deleting by index.
    """

    inner: _XmlFragmentTraitMixin

    def __init__(self, inner: _XmlFragmentTraitMixin) -> None:
        self.inner = inner

    def __len__(self) -> int:
        """
        Returns:
            The number of child nodes.
        """
        with self.inner.doc.transaction() as txn:
            return self.inner.integrated.len(txn._txn)

    def __getitem__(self, index: int) -> XmlElement | XmlFragment | XmlText:
        """
        Args:
            index: The index of the child to get.

        Raises:
            IndexError: Index out of bounds.

        Returns:
            The child at the given index.
        """
        with self.inner.doc.transaction() as txn:
            if index >= len(self):
                raise IndexError(index)
            return _integrated_to_wrapper(
                self.inner.doc, self.inner.integrated.get(txn._txn, index)
            )

    def __delitem__(self, key: int | slice) -> None:
        """
        Args:
            key: The child index (`int`) or children `slice` to remove.
        """
        with self.inner.doc.transaction() as txn:
            self.inner._forbid_read_transaction(txn)
            if isinstance(key, int):
                self.inner.integrated.remove_range(txn._txn, key, 1)
            elif isinstance(key, slice):
                start, stop = _check_slice(self, key)
                length = stop - start
                if length > 0:
                    self.inner.integrated.remove_range(txn._txn, start, length)
            else:
                raise TypeError(f"Index not supported: {key}")

    def __setitem__(self, key: int, value: str | XmlText | XmlElement):
        """
        Replaces a child. Equivalent to deleting the index and then inserting the new value.

        Args:
            key: The index of the child to replace.
            value: The new value at the index.
        """
        with self.inner.doc.transaction():
            del self[key]
            self.insert(key, value)

    def __iter__(self) -> Iterator[XmlText | XmlElement | XmlFragment]:
        """
        Returns:
            An iterable over child nodes.
        """
        with self.inner.doc.transaction():
            children = [self[i] for i in range(len(self))]
        return iter(children)

    @overload
    def insert(self, index: int, element: str | XmlText) -> XmlText: ...
    @overload
    def insert(self, index: int, element: XmlElement) -> XmlElement: ...

    def insert(self, index: int, element: str | XmlText | XmlElement) -> XmlText | XmlElement:
        """
        Inserts a new node into the element's or fragment's children at the specified index.

        Passing in a `str` will convert it to an `XmlText`. Returns the passed in element, which
        will now be integrated into the tree.

        Args:
            index: The index at which to insert the element.
            element: The element to insert.

        Returns:
            The inserted element.
        """
        with self.inner.doc.transaction() as txn:
            self.inner._forbid_read_transaction(txn)
            if index > len(self):
                raise IndexError(index)
            if isinstance(element, str):
                integrated = self.inner.integrated.insert_str(txn._txn, index, element)
                return XmlText(_doc=self.inner.doc, _integrated=integrated)
            elif isinstance(element, XmlText):
                if element._integrated is not None:
                    raise ValueError("Cannot insert an integrated XmlText")
                integrated = self.inner.integrated.insert_str(txn._txn, index, element.prelim)
                element._integrate(self.inner.doc, integrated)
                return element
            elif isinstance(element, XmlElement):
                if element._integrated is not None:
                    raise ValueError("Cannot insert an integrated XmlElement")
                prelim = element.prelim
                integrated = self.inner.integrated.insert_element_prelim(txn._txn, index, prelim[0])
                element._integrate(self.inner.doc, integrated)
                element._init(prelim)
                return element
            else:
                raise TypeError("Cannot add value to XML: " + repr(element))

    @overload
    def append(self, element: str | XmlText) -> XmlText: ...
    @overload
    def append(self, element: XmlElement) -> XmlElement: ...

    def append(self, element: str | XmlText | XmlElement) -> XmlText | XmlElement:
        """
        Appends a new node to the end of the element's or fragment's children.

        Equivalent to `insert` at index `len(self)`.

        Args:
            element: The element to append.

        Returns:
            The appended element.
        """
        return self.insert(len(self), element)


base_types[_XmlFragment] = XmlFragment
base_types[_XmlElement] = XmlElement
base_types[_XmlText] = XmlText
event_types[_XmlEvent] = XmlEvent
