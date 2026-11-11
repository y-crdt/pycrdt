from __future__ import annotations

import threading
from abc import ABC, abstractmethod
from functools import partial
from inspect import signature
from types import UnionType
from typing import (
    TYPE_CHECKING,
    Any,
    Callable,
    Literal,
    Type,
    Union,
    cast,
    get_args,
    get_origin,
    get_type_hints,
    overload,
)

import anyio
from anyio import BrokenResourceError, create_memory_object_stream
from anyio.abc import TaskGroup
from anyio.streams.memory import MemoryObjectReceiveStream, MemoryObjectSendStream

from ._pycrdt import Doc as _Doc
from ._pycrdt import SubdocChanges, Subscription
from ._pycrdt import Transaction as _Transaction
from ._sticky_index import Assoc, StickyIndex
from ._transaction import ReadTransaction, Transaction

if TYPE_CHECKING:
    from ._doc import Doc


base_types: dict[Any, type[BaseType | BaseDoc]] = {}
event_types: dict[Any, type[BaseEvent]] = {}


def forbid_read_transaction(txn: Transaction):
    if isinstance(txn, ReadTransaction):
        raise RuntimeError("Read-only transaction cannot be used to modify document structure")


class BaseDoc:
    _doc: _Doc
    _twin_doc: BaseDoc | None
    _txn: Transaction | None
    _exceptions: list[Exception]
    _txn_lock: threading.Lock
    _txn_async_lock: anyio.Lock
    _allow_multithreading: bool
    _Model: Any
    _subscriptions: list[Subscription]
    _origins: dict[int, Any]
    _task_group: TaskGroup | None
    _subdocs: dict[str, list[BaseDoc]]
    _subdoc_nb: int
    _new_subdocs: dict[int, BaseDoc]
    _inserted_subdocs: list[BaseDoc]
    _subdoc_changes: SubdocChanges | None

    def __init__(
        self,
        *,
        client_id: int | None = None,
        skip_gc: bool | None = None,
        guid: str | None = None,
        doc: _Doc | None = None,
        Model=None,
        allow_multithreading: bool = False,
        **data,
    ) -> None:
        super().__init__(**data)
        if doc is None:
            doc = _Doc(client_id, skip_gc, guid)
        self._doc = doc
        self._txn = None
        self._exceptions = []
        self._txn_lock = threading.Lock()
        self._txn_async_lock = anyio.Lock()
        self._Model = Model
        self._subscriptions = []
        self._origins = {}
        self._allow_multithreading = allow_multithreading
        self._task_group = None
        self._subdocs = {}
        self._subdoc_nb = 0
        self._new_subdocs = {}
        self._inserted_subdocs = []
        self._subdoc_changes = None

    def _get_subdoc(self, doc: _Doc) -> BaseDoc:
        # A subdocument is always accessed through the same object, so that its transactions
        # and observers are shared, and kept alive as long as it is in this document.
        subdoc = self._find_subdoc(doc)
        if subdoc is None:
            doc_type = cast(Type[BaseDoc], base_types[_Doc])
            subdoc = doc_type(doc=doc)
            self._keep_subdoc(subdoc)
        return subdoc

    def _add_subdoc(self, subdoc: BaseDoc) -> None:
        # called when the subdocument is inserted in this document
        if self._find_subdoc(subdoc._doc) is None:
            self._keep_subdoc(subdoc)
            self._inserted_subdocs.append(subdoc)

    def _find_subdoc(self, doc: _Doc) -> BaseDoc | None:
        for subdoc in self._subdocs.get(doc.guid(), []):
            if subdoc._doc.is_same(doc):
                return subdoc
        return None

    def _keep_subdoc(self, subdoc: BaseDoc) -> None:
        self._subdocs.setdefault(subdoc._doc.guid(), []).append(subdoc)
        self._subdoc_nb += 1
        self._new_subdocs[id(subdoc)] = subdoc

    def _forget_subdoc(self, doc: _Doc) -> None:
        guid = doc.guid()
        subdocs = self._subdocs.get(guid, [])
        for index, subdoc in enumerate(subdocs):
            if subdoc._doc.is_same(doc):
                del subdocs[index]
                if not subdocs:
                    del self._subdocs[guid]
                self._subdoc_nb -= 1
                self._new_subdocs.pop(id(subdoc), None)
                return

    def _forget_removed_subdocs(self) -> None:
        # Called after a commit, while holding the transaction lock. Yrs destroys
        # the subdocuments that are removed, with their observers.
        if self._subdoc_changes is None:
            if not self._new_subdocs:
                return
            # The changes are tracked from the first kept subdocument. The changes that
            # were committed before cannot be known, so check the subdocuments instead.
            self._subdoc_changes = self._doc.track_subdocs()
            if self._subdoc_changes is not None:
                self._check_new_subdocs()
            return
        added, removed = self._subdoc_changes.take()
        for doc in removed:
            self._forget_subdoc(doc)
        for doc in added:
            subdoc = self._find_subdoc(doc)
            if subdoc is not None:
                self._new_subdocs.pop(id(subdoc), None)
        for subdoc in self._inserted_subdocs:
            if id(subdoc) in self._new_subdocs:
                # inserted and removed in the same transaction
                self._forget_subdoc(subdoc._doc)
        self._inserted_subdocs.clear()
        # The other new subdocuments were accessed, which happens when they were already in
        # this document, unless they were also added and removed by the same transaction.
        # Check them when there are as many as the other kept subdocuments.
        if len(self._new_subdocs) >= max(16, self._subdoc_nb - len(self._new_subdocs)):
            self._check_new_subdocs()

    def _check_new_subdocs(self) -> None:
        subdocs = list(self._new_subdocs.values())
        found = self._doc.contains_subdocs([subdoc._doc for subdoc in subdocs])
        if found is None:  # pragma: no cover
            # a transaction is in progress outside of the transaction lock, check them later
            return
        for subdoc, in_doc in zip(subdocs, found):
            if not in_doc:
                self._forget_subdoc(subdoc._doc)
        self._new_subdocs.clear()
        self._inserted_subdocs.clear()


class BaseType(ABC):
    _doc: Doc | None
    _prelim: Any | None
    _integrated: Any
    _type_name: str

    def __init__(
        self,
        init: Any = None,
        *,
        _doc: Doc | None = None,
        _integrated: Any = None,
    ) -> None:
        self._type_name = self.__class__.__name__.lower()
        self._send_streams: dict[bool, set[MemoryObjectSendStream[BaseEvent | list[BaseEvent]]]] = {
            False: set(),
            True: set(),
        }
        self._event_subscription: dict[bool, Subscription] = {}
        # private API
        if _integrated is not None:
            self._doc = _doc
            self._prelim = None
            self._integrated = _integrated
            return
        # public API
        self._doc = None
        self._prelim = init
        self._integrated = None

    @abstractmethod
    def to_py(self) -> Any: ...

    @abstractmethod
    def _get_or_insert(self, name: str, doc: Doc) -> Any: ...

    @abstractmethod
    def _init(self, value: Any | None) -> None: ...

    def _forbid_read_transaction(self, txn: Transaction):
        forbid_read_transaction(txn)

    def _integrate(self, doc: Doc, integrated: Any) -> Any:
        prelim = self._prelim
        self._doc = doc
        self._prelim = None
        self._integrated = integrated
        return prelim

    def _do_and_integrate(self, action: str, value: BaseType, txn: _Transaction, *args) -> None:
        method = getattr(self._integrated, f"{action}_{value.type_name}_prelim")
        integrated = method(txn, *args)
        assert self._doc is not None
        prelim = value._integrate(self._doc, integrated)
        value._init(prelim)

    def _maybe_as_type_or_doc(self, obj: Any) -> Any:
        for k, v in base_types.items():
            if isinstance(obj, k):
                if issubclass(v, BaseDoc):
                    return self.doc._get_subdoc(obj)
                # create a BaseType
                return v(_doc=self.doc, _integrated=obj)
        # that was a primitive value, just return it
        return obj

    @property
    def integrated(self) -> Any:
        if self._integrated is None:
            raise RuntimeError("Not integrated in a document yet")
        return self._integrated

    @property
    def doc(self) -> Doc:
        """
        The document this shared type belongs to.

        Raises:
            RuntimeError: Not integrated in a document yet.
        """
        if self._doc is None:
            raise RuntimeError("Not integrated in a document yet")
        return self._doc

    @property
    def is_prelim(self) -> bool:
        return self._prelim is not None

    @property
    def is_integrated(self) -> bool:
        return self._integrated is not None

    @property
    def prelim(self) -> Any:
        return self._prelim

    @property
    def type_name(self) -> str:
        return self._type_name

    def observe(self, callback: Callable[[BaseEvent], None]) -> Subscription:
        param_nb = len(signature(callback).parameters)
        _callback = partial(observe_callback, callback, self.doc, param_nb)
        subscription = self.integrated.observe(_callback)
        self.doc._subscriptions.append(subscription)
        return subscription

    def observe_deep(self, callback: Callable[[list[BaseEvent]], None]) -> Subscription:
        """
        Subscribes a callback for all events emitted by this and nested collaborative types.

        Args:
            callback: The callback to call with the list of events.
        """
        param_nb = len(signature(callback).parameters)
        _callback = partial(observe_deep_callback, callback, self.doc, param_nb)
        subscription = self.integrated.observe_deep(_callback)
        self.doc._subscriptions.append(subscription)
        return subscription

    def unobserve(self, subscription: Subscription) -> None:
        """
        Unsubscribes to changes using the given subscription.

        Args:
            subscription: The subscription to unregister.
        """
        self.doc._subscriptions.remove(subscription)
        subscription.drop()

    @overload
    def events(
        self,
        deep: Literal[False],
        max_buffer_size: float = float("inf"),
    ) -> MemoryObjectReceiveStream[BaseEvent]: ...

    @overload
    def events(
        self,
        deep: Literal[True],
        max_buffer_size: float = float("inf"),
    ) -> MemoryObjectReceiveStream[list[BaseEvent]]: ...

    def events(
        self,
        deep: bool = False,
        max_buffer_size: float = float("inf"),
    ):
        """
        Allows to asynchronously iterate over the shared type events, without using a callback.
        A buffer is used to store the events, allowing to iterate at a (temporarily) slower rate
        than they are produced.

        This method must be used with an async context manager and an async for-loop:

        ```py
        async def main():
            async with doc.events() as events:
                async for event in events:
                    update: bytes = event.update
                    ...
        ```

        Args:
            deep: Whether to iterate over the nested events.
            max_buffer_size: Maximum number of events that can be buffered.

        Returns:
            An async iterator over the shared type events.
        """
        observe = self.observe_deep if deep else self.observe
        if not self._send_streams[deep]:
            self._event_subscription[deep] = observe(partial(self._send_event, deep))
        send_stream, receive_stream = create_memory_object_stream[
            Union[BaseEvent, list[BaseEvent]]
        ](max_buffer_size=max_buffer_size)
        self._send_streams[deep].add(send_stream)
        return receive_stream

    def _send_event(self, deep: bool, event: BaseEvent | list[BaseEvent]):
        to_remove: list[MemoryObjectSendStream[BaseEvent | list[BaseEvent]]] = []
        send_streams = self._send_streams[deep]
        for send_stream in send_streams:
            try:
                send_stream.send_nowait(event)
            except BrokenResourceError:
                to_remove.append(send_stream)
        for send_stream in to_remove:
            send_stream.close()
            send_streams.remove(send_stream)
        if not send_streams:
            self.unobserve(self._event_subscription[deep])


class Sequence(BaseType):
    def sticky_index(self, index: int, assoc: Assoc = Assoc.AFTER) -> StickyIndex:
        """
        A permanent position that sticks to the same place even when
        concurrent updates are made.

        Args:
            index: The index at which to stick.
            assoc: The [Assoc][pycrdt.Assoc] specifying whether to stick to the location
                before or after the index.

        Returns:
            A [StickyIndex][pycrdt.StickyIndex] that can be used to retrieve the index after
            an update was applied.
        """
        return StickyIndex.new(self, index, assoc)


def observe_callback(
    callback: Callable[[], None] | Callable[[Any], None] | Callable[[Any, ReadTransaction], None],
    doc: Doc,
    param_nb: int,
    event: Any,
):
    with doc._read_transaction(event.transaction) as txn:
        _event = event_types[type(event)](event, doc)
        _event.transaction = txn
        params = (_event, txn)
        try:
            callback(*params[:param_nb])  # type: ignore[arg-type]
        except Exception as exc:
            doc._exceptions.append(exc)


def observe_deep_callback(
    callback: Callable[[], None] | Callable[[Any], None] | Callable[[Any, ReadTransaction], None],
    doc: Doc,
    param_nb: int,
    events: list[Any],
):
    with doc._read_transaction(events[0].transaction) as txn:
        for idx, event in enumerate(events):
            _event = event_types[type(event)](event, doc)
            _event.transaction = txn
            events[idx] = _event
        params = (events, txn)
        try:
            callback(*params[:param_nb])  # type: ignore[arg-type]
        except Exception as exc:
            doc._exceptions.append(exc)


class BaseEvent:
    transaction: ReadTransaction
    __slots__ = ("transaction",)

    def __init__(self, event: Any, doc: Doc):
        slot: str
        for slot in self.__slots__:
            processed = process_event(getattr(event, slot), doc)
            setattr(self, slot, processed)

    def __str__(self):
        str_list = []
        slot: Any
        for slot in self.__slots__:
            val = str(getattr(self, slot))
            str_list.append(f"{slot}: {val}")
        ret = ", ".join(str_list)
        return "{" + ret + "}"


def process_event(value: Any, doc: Doc) -> Any:
    if isinstance(value, list):
        for idx, val in enumerate(value):
            value[idx] = process_event(val, doc)
    elif isinstance(value, dict):
        for key, val in value.items():
            value[key] = process_event(val, doc)
    else:
        val_type = type(value)
        if val_type in base_types:
            if val_type is _Doc:
                value = doc._get_subdoc(value)
            else:
                base_type = cast(Type[BaseType], base_types[val_type])
                value = base_type(_integrated=value, _doc=doc)
    return value


class Typed:
    _: Any

    def __init__(self) -> None:
        self.__dict__["annotations"] = {
            name: _type
            for name, _type in get_type_hints(type(self).mro()[0]).items()
            if name != "_"
        }

    if not TYPE_CHECKING:

        def __getattr__(self, key: str) -> Any:
            annotations = self.__dict__["annotations"]
            if key not in annotations:
                raise AttributeError(f'"{type(self).mro()[0]}" has no attribute "{key}"')
            expected_type = annotations[key]
            try:
                value = self._[key]
            except KeyError:
                # getattr() and hasattr() expect an AttributeError
                raise AttributeError(f'"{type(self).mro()[0]}" has no attribute "{key}"') from None
            if hasattr(expected_type, "mro") and Typed in expected_type.mro():
                return expected_type(value)
            return value

        def __setattr__(self, key: str, value: Any) -> None:
            if key == "_":
                self.__dict__["_"] = value
                return
            annotations = self.__dict__["annotations"]
            if key not in annotations:
                raise AttributeError(f'"{type(self).mro()[0]}" has no attribute "{key}"')
            expected_type = annotations[key]
            origin = get_origin(expected_type)
            if origin in (Union, UnionType):
                expected_types = get_args(expected_type)
            elif origin is not None:
                expected_type = origin
                expected_types = (expected_type,)
            else:
                expected_types = (expected_type,)
            if type(value) not in expected_types:
                raise TypeError(
                    f'Incompatible types in assignment (expression has type "{expected_type}", '
                    f'variable has type "{type(value)}")'
                )
            if isinstance(value, Typed):
                value = value._
            self._[key] = value
