"""Borrowed Yrs views expire when their individual observer invocation exits."""

import pytest
from pycrdt import Array, Doc, Map, Text, XmlElement, XmlFragment, XmlText

KINDS = ["text", "array", "map", "xml_fragment", "xml_element", "xml_text", "doc"]
EXPIRED = "Observer callback has finished"


def make_target(kind):
    doc = Doc()
    if kind in ("text", "doc"):
        target = doc.get("target", type=Text)

        def change():
            return target.insert(0, "a")
    elif kind == "array":
        target = doc.get("target", type=Array)

        def change():
            return target.append("a")
    elif kind == "map":
        target = doc.get("target", type=Map)

        def change():
            return target.update({"key": "a"})
    else:
        fragment = doc.get("target", type=XmlFragment)
        if kind == "xml_fragment":
            target = fragment

            def change():
                return target.children.append("a")
        elif kind == "xml_element":
            fragment.children.append(XmlElement("p"))
            target = fragment.children[0]

            def change():
                return target.children.append("a")
        else:
            fragment.children.append(XmlText())
            target = fragment.children[0]

            def change():
                return target.insert(0, "a")

    return doc, target, change


def subscribe(doc, target, kind, deep, callback):
    if kind == "doc":
        return doc._doc.observe(callback)
    return getattr(target.integrated, "observe_deep" if deep else "observe")(callback)


def event_fields(kind):
    if kind == "doc":
        return ["before_state", "after_state", "delete_set", "update"]
    if kind.startswith("xml"):
        return ["target", "path", "delta", "keys", "children_changed"]
    return ["target", "path", "keys" if kind == "map" else "delta"]


CASES = [(kind, deep) for kind in KINDS for deep in (False, True) if kind != "doc" or not deep]


@pytest.mark.parametrize("kind,deep", CASES)
def test_uncached_event_access_after_callback(kind, deep):
    doc, target, change = make_target(kind)
    events = []
    sub = subscribe(
        doc, target, kind, deep, lambda value: events.extend(value if deep else [value])
    )
    change()
    assert len(events) == 1
    event = events.pop()
    try:
        # XML fields are already owned; transaction update bytes are eager too.
        if not kind.startswith("xml"):
            for field in event_fields(kind):
                if kind == "doc" and field == "update":
                    assert isinstance(event.update, bytes)
                    continue
                with pytest.raises(RuntimeError, match=EXPIRED):
                    getattr(event, field)
            if kind != "doc":
                with pytest.raises(RuntimeError, match=EXPIRED):
                    repr(event)
        with pytest.raises(RuntimeError, match=EXPIRED):
            event.transaction
    finally:
        sub.drop()


@pytest.mark.parametrize("kind,deep", CASES)
def test_copied_fields_survive_but_borrowed_transaction_expires(kind, deep):
    doc, target, change = make_target(kind)
    events = []
    values = []
    transactions = []

    def callback(value):
        for event in value if deep else [value]:
            values.append([getattr(event, field) for field in event_fields(kind)])
            txn = event.transaction
            assert txn.origin() is None
            assert target.integrated.len(txn) > 0
            events.append(event)
            transactions.append(txn)

    sub = subscribe(doc, target, kind, deep, callback)
    change()
    try:
        assert len(events) == 1
        assert [getattr(events[0], field) for field in event_fields(kind)] == values[0]
        txn = transactions[0]
        for operation in (txn.origin, txn.commit, lambda: target.integrated.len(txn)):
            with pytest.raises(RuntimeError, match=EXPIRED):
                operation()
        # Cleanup of an expired borrowed view remains safe and idempotent.
        txn.drop()
        txn.drop()
    finally:
        sub.drop()


@pytest.mark.parametrize("kind,deep", CASES)
@pytest.mark.parametrize("exception", [ValueError, BaseException])
def test_callback_exception_invalidates_views(kind, deep, exception):
    doc, target, change = make_target(kind)
    events = []
    transactions = []

    def callback(value):
        event = value[0] if deep else value
        events.append(event)
        transactions.append(event.transaction)
        raise exception("callback failed")

    sub = subscribe(doc, target, kind, deep, callback)
    try:
        with pytest.raises(exception, match="callback failed"):
            change()
        with pytest.raises(RuntimeError, match=EXPIRED):
            transactions[0].origin()
        with pytest.raises(RuntimeError, match=EXPIRED):
            events[0].transaction
        # The failed callback must not leave the document locked.
        sub.drop()
        change()
    finally:
        sub.drop()


def test_each_observer_has_its_own_scope():
    doc = Doc()
    text = doc.get("text", type=Text)
    transactions = []

    def callback(event):
        for previous in transactions:
            with pytest.raises(RuntimeError, match=EXPIRED):
                previous.origin()
        current = event.transaction
        assert current.origin() is None
        transactions.append(current)

    subs = [text.integrated.observe(callback), text.integrated.observe(callback)]
    text += "a"
    assert len(transactions) == 2
    for txn in transactions:
        with pytest.raises(RuntimeError, match=EXPIRED):
            txn.origin()
    for sub in subs:
        sub.drop()


def test_nested_callback_preserves_outer_scope():
    outer_doc, outer, outer_change = make_target("text")
    inner_doc, inner, inner_change = make_target("text")
    inner_transactions = []
    outer_transactions = []

    def inner_callback(event):
        txn = event.transaction
        assert txn.origin() is None
        inner_transactions.append(txn)

    def outer_callback(event):
        txn = event.transaction
        outer_transactions.append(txn)
        inner_change()
        assert txn.origin() is None
        with pytest.raises(RuntimeError, match=EXPIRED):
            inner_transactions[0].origin()

    inner_sub = inner.integrated.observe(inner_callback)
    outer_sub = outer.integrated.observe(outer_callback)
    outer_change()
    with pytest.raises(RuntimeError, match=EXPIRED):
        outer_transactions[0].origin()
    outer_sub.drop()
    inner_sub.drop()


def test_all_deep_events_expire_together():
    doc = Doc()
    root = Map({"first": Map(), "second": Map()})
    doc["root"] = root
    events = []
    transactions = []

    def callback(value):
        assert len(value) == 2
        for event in value:
            events.append(event)
            transactions.append(event.transaction)
            assert event.transaction.origin() is None

    sub = root.integrated.observe_deep(callback)
    with doc.transaction():
        root["first"]["key"] = "a"
        root["second"]["key"] = "b"
    for event, txn in zip(events, transactions):
        with pytest.raises(RuntimeError, match=EXPIRED):
            event.keys
        with pytest.raises(RuntimeError, match=EXPIRED):
            txn.origin()
    sub.drop()
