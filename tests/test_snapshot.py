import subprocess
import sys
from textwrap import dedent

import pytest
from pycrdt import Doc, Snapshot, Text


def test_snapshot_encode_roundtrip():
    doc = Doc(client_id=1, skip_gc=True)
    doc["test"] = Text()
    with doc.transaction():
        text = doc["test"]
        text.insert(0, "hello world")
    # Encode snapshot
    snapshot = Snapshot.from_doc(doc)
    encoded = snapshot.encode()
    # Decode snapshot
    snapshot2 = Snapshot.decode(encoded)
    encoded2 = snapshot2.encode()
    assert encoded == encoded2

    # Should fail on invalid bytes
    with pytest.raises(ValueError):
        Snapshot.decode(b"notavalidsnapshot")


def test_snapshot_multiple_edits():
    doc = Doc(client_id=2, skip_gc=True)
    doc["test"] = Text()
    with doc.transaction():
        text = doc["test"]
        text.insert(0, "abc")
    with doc.transaction():
        text = doc["test"]
        text.insert(3, "def")
    snapshot = Snapshot.from_doc(doc)
    encoded = snapshot.encode()
    assert isinstance(encoded, bytes)
    assert len(encoded) > 0
    # The encoded snapshot should change after edits
    with doc.transaction():
        text = doc["test"]
        text.insert(6, "ghi")
    snapshot2 = Snapshot.from_doc(doc)
    encoded2 = snapshot2.encode()
    assert encoded != encoded2


def test_doc_from_snapshot():
    doc = Doc(client_id=42, skip_gc=True)
    doc["test"] = Text()
    with doc.transaction():
        text = doc["test"]
        text.insert(0, "old")
    snapshot = Snapshot.from_doc(doc)
    # Make additional changes after snapshot
    with doc.transaction():
        text = doc["test"]
        text.insert(0, "new ")
    # Restore to snapshot in a new doc
    doc_restored = Doc.from_snapshot(snapshot, doc)
    # Should revert to snapshot state in restored doc
    assert "test" in doc_restored
    with doc_restored.transaction():
        text = doc_restored["test"]
    assert str(text) == "old"
    # Original doc should have both changes
    with doc.transaction():
        text = doc["test"]
    assert str(text) == "new old"


def test_edit_doc_from_snapshot():
    doc = Doc(skip_gc=True)
    text = doc.get("text", type=Text)
    text += "hello"
    snapshot = Snapshot.from_doc(doc)
    text += " world"
    doc_restored = Doc.from_snapshot(snapshot, doc)
    text_restored = doc_restored.get("text", type=Text)
    text_restored += "!!!"

    update = doc.get_update()
    doc.apply_update(doc_restored.get_update())
    doc_restored.apply_update(update)

    assert str(text) == str(text_restored)
    assert str(text) in ("hello world!!!", "hello!!! world")
    assert doc_restored.client_id != doc.client_id


def test_snapshot_in_transaction():
    # A deadlock can hold the GIL, so enforce the timeout from another process.
    code = dedent(
        """
        from pycrdt import Doc, Snapshot, Text

        doc = Doc(skip_gc=True)
        text = doc.get("test", type=Text)
        with doc.transaction():
            text += "old"
            snapshot = Snapshot.from_doc(doc)
            doc_restored = Doc.from_snapshot(snapshot, doc)
            text += " new"
        assert str(doc_restored.get("test", type=Text)) == "old"
        assert str(text) == "old new"
        """
    )
    subprocess.run([sys.executable, "-c", code], check=True, timeout=10)


def test_snapshot_after_deletion_in_transaction():
    # A deadlock can hold the GIL, so enforce the timeout from another process.
    code = dedent(
        """
        from pycrdt import Doc, Snapshot, Text

        doc = Doc(skip_gc=True)
        doc["test"] = text = Text("hello world")
        with doc.transaction():
            del text[5:]
            snapshot = Snapshot.from_doc(doc)
            doc_restored = Doc.from_snapshot(snapshot, doc)
            assert str(doc_restored.get("test", type=Text)) == "hello"
            del text[:1]
        assert str(doc_restored.get("test", type=Text)) == "hello"
        assert str(text) == "ello"
        """
    )
    subprocess.run([sys.executable, "-c", code], check=True, timeout=10)


def test_snapshot_in_observer_callback():
    # A deadlock can hold the GIL, so enforce the timeout from another process.
    code = dedent(
        """
        from pycrdt import Doc, Snapshot, Text

        doc = Doc(skip_gc=True)
        text = doc.get("test", type=Text)
        restored = []

        def callback(event):
            snapshot = Snapshot.from_doc(doc)
            restored.append(str(Doc.from_snapshot(snapshot, doc).get("test", type=Text)))

        sub = text.observe(callback)
        text += "hello"
        assert restored == ["hello"]
        """
    )
    subprocess.run([sys.executable, "-c", code], check=True, timeout=10)


def test_doc_from_snapshot_without_skip_gc():
    doc = Doc()
    doc["test"] = Text("hello")
    snapshot = Snapshot.from_doc(doc)
    with pytest.raises(ValueError) as excinfo:
        Doc.from_snapshot(snapshot, doc)
    assert str(excinfo.value) == "Restoring a snapshot requires a document with skip_gc=True"
