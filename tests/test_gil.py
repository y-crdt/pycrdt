import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from functools import partial

import pytest
from pycrdt import Doc, Map, _pycrdt

pytestmark = pytest.mark.skipif(
    hasattr(sys, "_is_gil_enabled") and not sys._is_gil_enabled(),
    reason="These tests verify GIL release and require the GIL to be enabled",
)


@pytest.fixture(scope="module")
def update() -> bytes:
    doc = Doc()
    map0 = doc.get("map", type=Map)
    with doc.transaction():
        for i in range(100_000):
            map0[str(i)] = i
    return doc.get_update()


def probe_during_call(call, probe=lambda: None):
    # Start the worker before changing the switch interval, then park it behind
    # a locked gate. Unlike thread.start(), releasing this gate does not release
    # the GIL. With periodic switching disabled, the worker can observe active
    # only if the native call itself releases the GIL.
    gate = threading.Lock()
    gate.acquire()
    ready = threading.Event()
    active = False

    def worker():
        ready.set()
        with gate:
            observed = active
            if observed:
                probe()
            return observed

    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(worker)
        assert ready.wait(timeout=10), "Probe worker failed to start"
        interval = sys.getswitchinterval()
        sys.setswitchinterval(60)
        try:
            active = True
            gate.release()
            call()
        finally:
            active = False
            sys.setswitchinterval(interval)
        # Propagate worker exceptions into the test, rather than losing them in
        # an unhandled-thread warning. Waiting happens after active is cleared.
        assert future.result(timeout=10), "Worker did not run during the native call"


@pytest.mark.parametrize("operation", ["apply", "encode", "merge", "state", "diff"])
def test_releases_gil(update, operation):
    doc = Doc()
    doc.apply_update(update)
    with doc.transaction() as txn:
        # Call the bindings directly so Python transaction setup, commit,
        # callbacks and document destruction cannot satisfy the GIL assertion.
        calls = {
            "apply": partial(doc._doc.apply_update, txn._txn, update),
            "encode": partial(doc._doc.get_update, txn._txn, b"\x00"),
            "merge": partial(_pycrdt.merge_updates, (update, update)),
            "state": partial(_pycrdt.get_state, update),
            "diff": partial(_pycrdt.get_update, update, b"\x00"),
        }
        probe_during_call(calls[operation])


@pytest.mark.parametrize("operation", ["apply", "encode"])
def test_concurrent_transaction_access(update, operation):
    doc = Doc()
    if operation == "encode":
        doc.apply_update(update)
    expected_metadata = doc.client_id, doc.guid

    with doc.transaction() as txn:
        raw_txn = txn._txn

        def probe():
            assert (doc.client_id, doc.guid) == expected_metadata
            # apply_update holds a mutable PyO3 borrow of the transaction;
            # get_update instead rejects access through its transaction mutex.
            message = "Already mutably borrowed|Transaction already borrowed"
            with pytest.raises(RuntimeError, match=message):
                raw_txn.origin()
            with pytest.raises(RuntimeError, match="Already in a transaction"):
                doc._doc.create_transaction()

        if operation == "apply":
            call = partial(doc._doc.apply_update, raw_txn, update)
        else:
            call = partial(doc._doc.get_update, raw_txn, b"\x00")
        probe_during_call(call, probe)
        assert raw_txn.origin() is None

    # Failed concurrent access must leave the transaction and store usable.
    map0 = doc.get("map", type=Map)
    assert len(map0) == 100_000
    assert map0["99999"] == 99999
    map0["after"] = "ok"
    assert map0["after"] == "ok"
    restored = Doc()
    restored.apply_update(doc.get_update())
    assert restored.get("map", type=Map)["after"] == "ok"
