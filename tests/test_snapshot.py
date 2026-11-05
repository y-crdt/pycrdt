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


def test_snapshot_in_transaction():
    doc = Doc(skip_gc=True)
    text = doc.get("test", type=Text)
    with doc.transaction():
        text += "old"
        snapshot = Snapshot.from_doc(doc)
        doc_restored = Doc.from_snapshot(snapshot, doc)
        text += " new"
    assert str(doc_restored.get("test", type=Text)) == "old"
    assert str(text) == "old new"


def test_snapshot_in_observer_callback():
    doc = Doc(skip_gc=True)
    text = doc.get("test", type=Text)
    restored = []

    def callback(event):
        snapshot = Snapshot.from_doc(doc)
        restored.append(str(Doc.from_snapshot(snapshot, doc).get("test", type=Text)))

    sub = text.observe(callback)  # noqa: F841
    text += "hello"
    assert restored == ["hello"]


def test_doc_from_snapshot_without_skip_gc():
    doc = Doc()
    doc["test"] = Text("hello")
    snapshot = Snapshot.from_doc(doc)
    with pytest.raises(ValueError) as excinfo:
        Doc.from_snapshot(snapshot, doc)
    assert str(excinfo.value) == "Restoring a snapshot requires a document with skip_gc=True"
