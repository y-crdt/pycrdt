import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from functools import partial

import pytest
from pycrdt import Doc, Map, _pycrdt, get_state, get_update, merge_updates

pytestmark = pytest.mark.skipif(
    hasattr(sys, "_is_gil_enabled") and not sys._is_gil_enabled(),
    reason="These tests verify GIL release and require the GIL to be enabled",
)

# The same value as DETACH_MIN_SIZE in src/update.rs.
DETACH_MIN_SIZE = 64 * 1024


@pytest.fixture(scope="module")
def update() -> bytes:
    doc = Doc()
    map0 = doc.get("map", type=Map)
    with doc.transaction():
        for i in range(100_000):
            map0[str(i)] = i
    return doc.get_update()


def update_of_size(size: int, client_id: int = 1) -> bytes:
    # Small map entries take the longest time per byte to process, so a call on
    # this update does the most work that its size allows.
    # A string value pads the update to the exact size. From 128 to 16383 bytes,
    # its length prefix is two bytes, so each padding byte adds one byte to the update.
    def build(padding: int) -> bytes:
        doc = Doc(client_id=client_id)
        map0 = doc.get("map", type=Map)
        with doc.transaction():
            for i in range(size // 20):
                map0[str(i)] = i
            map0["padding"] = "x" * padding
        return doc.get_update()

    padding = 128
    padding += size - len(build(padding))
    assert 128 <= padding < 16384, f"Cannot pad an update to {size} bytes"
    update = build(padding)
    assert len(update) == size
    return update


def probe_during_call(call, probe=lambda: None, timeout: float = 0.5) -> bool:
    # Return True if the worker ran while the native call was running.
    # The worker waits behind a locked gate. Unlike thread.start(), releasing the
    # gate does not release the GIL. With periodic switching disabled, the worker
    # can run only while the native call releases the GIL.
    # Switching is disabled before the worker starts, so that no GIL wait in the
    # worker can end after the default interval and force a switch.
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

    interval = sys.getswitchinterval()
    sys.setswitchinterval(60)
    try:
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(worker)
            started = ready.wait(timeout=10)
            active = True
            # Release the gate even if the worker did not start, so that the pool
            # can shut down.
            gate.release()
            try:
                # On a busy machine the worker can get no CPU time during one call,
                # so repeat the call until the worker has run or the timeout ends.
                deadline = time.monotonic() + timeout
                call()
                while not future.done() and time.monotonic() < deadline:
                    call()
            finally:
                active = False
            assert started, "Probe worker failed to start"
            # Propagate worker exceptions into the test, rather than losing them in
            # an unhandled-thread warning. Waiting happens after active is cleared.
            return future.result(timeout=10)
    finally:
        sys.setswitchinterval(interval)


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
        assert probe_during_call(calls[operation]), "Worker did not run during the native call"


@pytest.mark.parametrize("operation", ["apply", "merge", "state", "diff"])
@pytest.mark.parametrize("size,releases", [(DETACH_MIN_SIZE - 1, False), (DETACH_MIN_SIZE, True)])
def test_releases_gil_from_threshold(operation, size, releases):
    update = update_of_size(size)
    # merge_updates compares the total size of the updates with the threshold.
    half = size // 2
    halves = (update_of_size(half, client_id=1), update_of_size(size - half, client_id=2))
    doc = Doc()
    with doc.transaction() as txn:
        calls = {
            "apply": partial(doc._doc.apply_update, txn._txn, update),
            "merge": partial(_pycrdt.merge_updates, halves),
            "state": partial(_pycrdt.get_state, update),
            "diff": partial(_pycrdt.get_update, update, b"\x00"),
        }
        assert probe_during_call(calls[operation]) is releases


def test_error_without_gil(update):
    # The truncated update is larger than the threshold, so each error is raised
    # while the GIL is released.
    truncated = update[:-1]
    with pytest.raises(ValueError, match="Cannot decode update"):
        Doc().apply_update(truncated)
    with pytest.raises(ValueError, match="Cannot merge updates"):
        merge_updates(truncated, truncated)
    with pytest.raises(ValueError, match="Cannot encode state vector from update"):
        get_state(truncated)
    with pytest.raises(ValueError, match="Cannot diff updates"):
        get_update(truncated, b"\x00")


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
        assert probe_during_call(call, probe), "Worker did not run during the native call"
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
