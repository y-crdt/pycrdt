"""Owned objects can move between threads; borrowed views stay thread-affine."""

import gc
import sys
import threading
import weakref

import pytest
from pycrdt import Array, Assoc, Doc, Map, Snapshot, Text, UndoManager, XmlFragment

KINDS = [
    "transaction",
    "borrowed_transaction",
    "subscription",
    "undo_manager",
    "sticky_index",
    "snapshot",
    "text_event",
    "array_event",
    "map_event",
    "xml_event",
    "transaction_event",
    "subdocs_event",
]


OWNED_KINDS = {
    "transaction",
    "subscription",
    "undo_manager",
    "sticky_index",
    "snapshot",
    "subdocs_event",
}
BORROWED_KINDS = [kind for kind in KINDS if kind not in OWNED_KINDS]


def run_in_thread(function):
    errors = []

    def run():
        try:
            function()
        except BaseException as exc:
            errors.append(exc)

    thread = threading.Thread(target=run)
    thread.start()
    thread.join(timeout=10)
    assert not thread.is_alive(), "Worker thread did not finish"
    if errors:
        raise errors[0]


@pytest.mark.parametrize("exception_type", [RuntimeError, BaseException])
def test_worker_exception_is_reraised(exception_type):
    error = exception_type("worker failed")

    def fail():
        raise error

    with pytest.raises(exception_type, match="worker failed") as exc:
        run_in_thread(fail)
    assert exc.value is error


def make_object(kind):
    doc = Doc()
    text = doc.get("text", type=Text)
    if kind == "transaction":
        return doc, doc._doc.create_transaction(), "origin", True, []
    if kind == "subscription":
        return doc, text.integrated.observe(lambda event: None), "drop", True, []
    if kind == "undo_manager":
        manager = UndoManager(scopes=[text])
        return doc, manager._undo_manager, "can_undo", True, []
    if kind == "sticky_index":
        text += "a"
        return doc, text.sticky_index(0, Assoc.AFTER)._sticky_index, "encode", True, []
    if kind == "snapshot":
        return doc, Snapshot.from_doc(doc)._snapshot, "encode", True, []

    captured = []

    def callback(event):
        # Fill caches while the borrowed Yrs event and transaction are alive.
        # Borrowed wrappers remain thread-affine, including cached getters.
        if kind == "subdocs_event":
            event.added
        elif kind in ("transaction_event", "borrowed_transaction"):
            event.before_state
            event.after_state
            event.delete_set
            event.update
            event.transaction
        else:
            event.target
            event.path
            if kind == "map_event":
                event.keys
            else:
                event.delta
            event.transaction
        captured.append(event.transaction if kind == "borrowed_transaction" else event)

    if kind in ("transaction_event", "borrowed_transaction"):
        subscription = doc._doc.observe(callback)
        text += "a"
        attribute = "origin" if kind == "borrowed_transaction" else "before_state"
    elif kind == "subdocs_event":
        subscription = doc._doc.observe_subdocs(callback)
        doc.get("children", type=Array).append(Doc())
        attribute = "added"
    else:
        shared = {
            "text_event": Text,
            "array_event": Array,
            "map_event": Map,
            "xml_event": XmlFragment,
        }[kind]
        target = doc.get("target", type=shared)
        subscription = target.integrated.observe(callback)
        if kind == "text_event":
            target += "a"
        elif kind == "array_event":
            target.append("a")
        elif kind == "map_event":
            target["key"] = "a"
        else:
            target.children.append("a")
        attribute = "target"
    assert len(captured) == 1
    return doc, captured.pop(), attribute, kind == "borrowed_transaction", [subscription]


@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize("cyclic", [False, True], ids=["last_reference", "cyclic_gc"])
def test_destroy_on_another_thread(kind, cyclic, monkeypatch):
    unraisable = []
    monkeypatch.setattr(sys, "unraisablehook", unraisable.append)
    doc, obj, _, _, subscriptions = make_object(kind)
    was_enabled = gc.isenabled()
    gc.disable()
    try:
        holder = [obj]
        if cyclic:
            holder.append(holder)
        del obj

        def collect():
            nonlocal holder
            holder = None
            gc.collect()
            gc.collect()  # PyPy may require another collection.

        run_in_thread(collect)
        assert not unraisable
        # Dropping an owned transaction must release its document's write lock.
        with doc.transaction():
            pass
    finally:
        if was_enabled:
            gc.enable()
    for subscription in subscriptions:
        subscription.drop()


@pytest.mark.parametrize("kind", BORROWED_KINDS)
def test_access_remains_thread_affine(kind):
    doc, obj, attribute, call, subscriptions = make_object(kind)

    def access():
        with pytest.raises(BaseException, match="Object accessed from a different thread") as exc:
            value = getattr(obj, attribute)
            if call:
                value()
        assert type(exc.value).__name__ == "PanicException"

    run_in_thread(access)
    for subscription in subscriptions:
        subscription.drop()


@pytest.mark.parametrize("kind", sorted(OWNED_KINDS))
def test_owned_object_access_on_another_thread(kind):
    doc, obj, attribute, call, subscriptions = make_object(kind)
    results = []
    lock = threading.Lock()

    def access():
        with lock:
            value = getattr(obj, attribute)
            results.append(value() if call else value)

    run_in_thread(access)
    assert len(results) == 1
    # Objects remain usable after returning to the creating thread too.
    with lock:
        value = getattr(obj, attribute)
        assert (value() if call else value) == results[0]
    if kind == "transaction":
        obj.drop()
    for subscription in subscriptions:
        subscription.drop()


@pytest.mark.parametrize("cyclic", [False, True])
@pytest.mark.parametrize("explicit", [False, True], ids=["gc", "unsubscribe"])
def test_subscription_releases_callback_on_another_thread(cyclic, explicit):
    doc = Doc()
    text = doc.get("text", type=Text)
    calls = []

    class Callback:
        def __call__(self, event):
            calls.append(True)

    callback = Callback()
    ref = weakref.ref(callback)
    holder = [text.integrated.observe(callback)]
    if cyclic:
        holder.append(holder)
    del callback
    text += "a"
    assert calls == [True]

    def collect():
        nonlocal holder
        if explicit:
            holder[0].drop()
        else:
            holder = None
        gc.collect()
        gc.collect()

    run_in_thread(collect)
    assert ref() is None, "Rust subscription leaked its Python callback"
    text += "b"
    assert calls == [True]


def test_uncommitted_transaction_is_committed_on_another_thread():
    doc = Doc()
    text = doc.get("text", type=Text)
    holder = [doc._doc.create_transaction()]
    text.integrated.insert(holder[0], 0, "hello")
    run_in_thread(holder.clear)
    assert str(text) == "hello"


def test_undo_manager_releases_python_state_on_another_thread():
    doc = Doc()
    text = doc.get("text", type=Text)

    class Clock:
        def __call__(self):
            return 0

    clock = Clock()
    ref = weakref.ref(clock)
    holder = [UndoManager(scopes=[text], timestamp=clock)]
    del clock
    text += "a"
    run_in_thread(holder.clear)
    gc.collect()
    assert ref() is None, "Rust undo manager leaked its Python clock"
    # Its document observers must have been removed too.
    text += "b"
    assert str(text) == "ab"


def test_owned_transaction_moves_between_threads():
    doc = Doc()
    text = doc.get("text", type=Text)
    txn = doc._doc.create_transaction_with_origin(7)
    lock = threading.Lock()
    with lock:
        text.integrated.insert(txn, 0, "hello")
        sticky = text.integrated.sticky_index(txn, 1, Assoc.AFTER)

    def edit_and_commit():
        with lock:
            assert txn.origin() == 7
            assert text.integrated.len(txn) == 5
            assert sticky.get_offset(txn) == 1
            text.integrated.insert(txn, 5, " world")
            txn.commit()
            txn.drop()

    run_in_thread(edit_and_commit)
    assert str(text) == "hello world"
    with pytest.raises(RuntimeError, match="Transaction is no longer valid"):
        txn.origin()


def test_undo_redo_on_another_thread():
    doc = Doc()
    text = doc.get("text", type=Text)
    manager = UndoManager(scopes=[text])
    text += "hello"
    lock = threading.Lock()

    def undo():
        with lock:
            assert manager.can_undo()
            assert manager.undo()
            assert str(text) == ""

    def redo():
        with lock:
            assert manager.can_redo()
            assert manager.redo()
            assert str(text) == "hello"

    run_in_thread(undo)
    run_in_thread(redo)
    assert str(text) == "hello"


def test_borrowed_views_reject_worker_access_during_callback():
    doc = Doc()
    text = doc.get("text", type=Text)
    observed = []

    def callback(event):
        txn = event.transaction

        def access():
            for operation in (txn.origin, lambda: event.target):
                with pytest.raises(BaseException, match="Object accessed from a different thread"):
                    operation()

        run_in_thread(access)
        # The failed worker access must not invalidate the active callback.
        assert txn.origin() is None
        assert text.integrated.len(txn) == 1
        observed.append(True)

    sub = text.integrated.observe(callback)
    text += "a"
    assert observed == [True]
    sub.drop()
