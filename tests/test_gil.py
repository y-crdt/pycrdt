import sys
import threading

import pytest
from pycrdt import Doc, Map, get_state, get_update, merge_updates


@pytest.fixture(scope="module")
def update() -> bytes:
    doc = Doc()
    map0 = doc.get("map", type=Map)
    with doc.transaction():
        for i in range(100_000):
            map0[str(i)] = i
    return doc.get_update()


def apply_update(update: bytes, doc: Doc) -> None:
    Doc().apply_update(update)


def get_doc_update(update: bytes, doc: Doc) -> None:
    doc.get_update()


def merge(update: bytes, doc: Doc) -> None:
    merge_updates(update, update)


def get_update_state(update: bytes, doc: Doc) -> None:
    get_state(update)


def diff_update(update: bytes, doc: Doc) -> None:
    get_update(update, b"\x00")


@pytest.mark.parametrize(
    "call", [apply_update, get_doc_update, merge, get_update_state, diff_update]
)
def test_releases_gil(update, call):
    # With a switch interval far longer than the test, a thread waiting for the GIL
    # only gets it when the holding thread releases it: the main thread can run
    # while the worker is busy only if the call released the GIL.
    doc = Doc()
    doc.apply_update(update)
    calls = 0
    calls_seen = []

    def worker():
        nonlocal calls
        for _ in range(10):
            call(update, doc)
            calls += 1

    interval = sys.getswitchinterval()
    sys.setswitchinterval(60)
    try:
        thread = threading.Thread(target=worker)
        thread.start()
        calls_seen.append(calls)
        thread.join()
    finally:
        sys.setswitchinterval(interval)
    assert calls == 10
    assert calls_seen[0] < 10


def test_read_doc_while_applying_update(update):
    doc = Doc()
    applied = threading.Event()

    def worker():
        doc.apply_update(update)
        applied.set()

    interval = sys.getswitchinterval()
    sys.setswitchinterval(60)
    try:
        thread = threading.Thread(target=worker)
        thread.start()
        # The worker holds the document while the update is applied.
        client_id = doc.client_id
        guid = doc.guid
        thread.join()
    finally:
        sys.setswitchinterval(interval)
    assert applied.is_set()
    assert client_id == doc.client_id
    assert guid == doc.guid
