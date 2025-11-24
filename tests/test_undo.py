import pytest
from pycrdt import Array, Doc, Map, StackItem, Text, UndoManager


def undo_redo(data, undo_manager, val0, val1, val3):
    assert undo_manager.can_undo()
    undone = undo_manager.undo()
    assert undone
    assert data.to_py() == val1
    assert undo_manager.can_undo()
    undone = undo_manager.undo()
    assert undone
    assert data.to_py() == val0
    assert not undo_manager.can_undo()
    undone = undo_manager.undo()
    assert not undone
    assert undo_manager.can_redo()
    redone = undo_manager.redo()
    assert redone
    assert data.to_py() == val1
    assert undo_manager.can_redo()
    redone = undo_manager.redo()
    assert redone
    assert data.to_py() == val3
    assert not undo_manager.can_redo()
    redone = undo_manager.redo()
    assert not redone
    assert undo_manager.can_undo()
    undo_manager.clear()
    assert not undo_manager.can_undo()


def test_text_undo():
    doc = Doc()
    doc["data"] = data = Text()
    undo_manager = UndoManager(scopes=[data], capture_timeout_millis=0)
    val0 = ""
    val1 = "Hello"
    val2 = ", World!"
    val3 = val1 + val2
    data += val1
    assert data.to_py() == val1
    data += val2
    assert data.to_py() == val3
    undo_redo(data, undo_manager, val0, val1, val3)


def test_array_undo():
    doc = Doc()
    doc["data"] = data = Array()
    undo_manager = UndoManager(scopes=[data], capture_timeout_millis=0)
    val0 = []
    val1 = ["foo"]
    val2 = ["bar"]
    val3 = val1 + val2
    data += val1
    assert data.to_py() == val1
    data += val2
    assert data.to_py() == val3
    undo_redo(data, undo_manager, val0, val1, val3)


def test_map_undo():
    doc = Doc()
    doc["data"] = data = Map()
    undo_manager = UndoManager(scopes=[data], capture_timeout_millis=0)
    val0 = {}
    val1 = {"key0": "val0"}
    val2 = {"key1": "val1"}
    val3 = dict(**val1, **val2)
    data.update(val1)
    assert data.to_py() == val1
    data.update(val2)
    assert data.to_py() == val3
    undo_redo(data, undo_manager, val0, val1, val3)


def test_scopes():
    doc = Doc()
    doc["text"] = text = Text()
    doc["array"] = array = Array()
    doc["map"] = map = Map()
    undo_manager = UndoManager(scopes=[text], capture_timeout_millis=0)

    text += "Hello"
    text += ", World!"
    assert str(text) == "Hello, World!"
    undo_manager.undo()
    assert str(text) == "Hello"

    array.append(0)
    assert array.to_py() == [0]
    undo_manager.undo()
    assert array.to_py() == [0]
    undo_manager.expand_scope(array)
    array.append(1)
    assert array.to_py() == [0, 1]
    undo_manager.undo()
    assert array.to_py() == [0]

    map["key0"] = "val0"
    assert map.to_py() == {"key0": "val0"}
    undo_manager.undo()
    assert map.to_py() == {"key0": "val0"}
    undo_manager.expand_scope(map)
    map["key1"] = "val1"
    assert map.to_py() == {"key0": "val0", "key1": "val1"}
    undo_manager.undo()
    assert map.to_py() == {"key0": "val0"}


def test_wrong_creation():
    with pytest.raises(RuntimeError) as excinfo:
        UndoManager()
    assert str(excinfo.value) == "UndoManager must be created with doc or scopes"

    doc = Doc()
    doc["text"] = text = Text()
    with pytest.raises(RuntimeError) as excinfo:
        UndoManager(doc=doc, scopes=[text])
    assert str(excinfo.value) == "UndoManager must be created with doc or scopes"


def test_undo_redo_stacks():
    doc = Doc()
    doc["text"] = text = Text()
    undo_manager = UndoManager(scopes=[text], capture_timeout_millis=0)
    assert len(undo_manager.undo_stack) == 0
    assert len(undo_manager.redo_stack) == 0
    text += "Hello"
    assert len(undo_manager.undo_stack) == 1
    assert len(undo_manager.redo_stack) == 0
    text += ", World!"
    assert len(undo_manager.undo_stack) == 2
    assert len(undo_manager.redo_stack) == 0
    undo_manager.undo()
    assert len(undo_manager.undo_stack) == 1
    assert len(undo_manager.redo_stack) == 1
    undo_manager.undo()
    assert len(undo_manager.undo_stack) == 0
    assert len(undo_manager.redo_stack) == 2


def test_origin():
    doc = Doc()
    doc["text"] = text = Text()
    undo_manager = UndoManager(scopes=[text], capture_timeout_millis=0)

    class Origin:
        pass

    origin = Origin()
    undo_manager.include_origin(origin)
    text += "Hello"
    assert not undo_manager.can_undo()
    with doc.transaction(origin=origin):
        text += ", World!"
    assert str(text) == "Hello, World!"
    assert undo_manager.can_undo()
    undo_manager.undo()
    assert str(text) == "Hello"
    assert not undo_manager.can_undo()
    undo_manager.exclude_origin(origin)
    text += ", World!"
    assert str(text) == "Hello, World!"
    assert undo_manager.can_undo()
    undo_manager.undo()
    assert str(text) == "Hello"
    assert not undo_manager.can_undo()


def test_timestamp():
    timestamp = 0
    timestamp_called = 0

    def timestamp_callback():
        nonlocal timestamp, timestamp_called
        timestamp_called += 1
        return timestamp

    doc = Doc()
    doc["text"] = text = Text()
    undo_manager = UndoManager(
        scopes=[text], capture_timeout_millis=1, timestamp=timestamp_callback
    )
    text += "a"
    timestamp += 1
    text += "b"
    text += "c"
    timestamp += 1
    undo_manager.undo()
    assert str(text) == "a"
    assert timestamp_called == 4


def test_stack_item_serialization():
    """Test serializing and deserializing a StackItem"""
    doc = Doc()
    doc["text"] = text = Text()
    undo_manager = UndoManager(scopes=[text], capture_timeout_millis=0)

    # Make some changes
    text += "Hello"
    text += ", World!"

    # Get a stack item
    undo_stack = undo_manager.undo_stack
    assert len(undo_stack) == 2
    original_item = undo_stack[0]

    # Serialize it
    deletions_bytes, insertions_bytes = original_item.encode()
    assert isinstance(deletions_bytes, bytes)
    assert isinstance(insertions_bytes, bytes)

    # Deserialize it
    restored_item = StackItem.decode(deletions_bytes, insertions_bytes)
    assert restored_item is not None

    # Verify the deletions and insertions are preserved
    original_deletions_bytes, original_insertions_bytes = original_item.encode()
    restored_deletions_bytes, restored_insertions_bytes = restored_item.encode()

    assert original_deletions_bytes == restored_deletions_bytes
    assert original_insertions_bytes == restored_insertions_bytes


def test_stack_item_deletions_insertions():
    """Test accessing deletions and insertions from StackItem"""
    doc = Doc()
    doc["text"] = text = Text()
    undo_manager = UndoManager(scopes=[text], capture_timeout_millis=0)

    # Make a change
    text += "Hello"

    # Get the stack item
    undo_stack = undo_manager.undo_stack
    assert len(undo_stack) == 1
    item = undo_stack[0]

    # Access deletions and insertions (now properties)
    deletions = item.deletions
    insertions = item.insertions

    # They should be DeleteSet objects
    assert deletions is not None
    assert insertions is not None

    # They should be encodable
    deletions_bytes = deletions.encode()
    insertions_bytes = insertions.encode()
    assert isinstance(deletions_bytes, bytes)
    assert isinstance(insertions_bytes, bytes)


def test_deleteset_to_json_string():
    """Test that DeleteSet.to_json_string produces valid JSON"""
    doc = Doc()
    doc["text"] = text = Text()
    undo_manager = UndoManager(scopes=[text], capture_timeout_millis=0)
    text += "Hello"
    text += ", World!"
    item = undo_manager.undo_stack[0]
    deletions = item.deletions
    json_str = deletions.to_json_string()
    import json

    parsed = json.loads(json_str)
    assert isinstance(parsed, dict)


def test_stack_item_multiple_changes():
    """Test serialization with multiple types of changes"""
    doc = Doc()
    doc["text"] = text = Text()
    doc["array"] = array = Array()
    undo_manager = UndoManager(scopes=[text, array], capture_timeout_millis=0)

    # Make various changes
    text += "Hello"
    array.append(1)
    array.append(2)
    text += " World"

    # Get all stack items
    undo_stack = undo_manager.undo_stack
    assert len(undo_stack) == 4

    # Serialize and deserialize all items
    for original_item in undo_stack:
        deletions_bytes, insertions_bytes = original_item.encode()
        restored_item = StackItem.decode(deletions_bytes, insertions_bytes)

        # Verify they match
        orig_del, orig_ins = original_item.encode()
        rest_del, rest_ins = restored_item.encode()
        assert orig_del == rest_del
        assert orig_ins == rest_ins


def test_push_undo_stack():
    """Test pushing a StackItem back onto the undo stack"""
    doc = Doc()
    doc["text"] = text = Text()
    undo_manager = UndoManager(scopes=[text], capture_timeout_millis=0)

    # Make some changes
    text += "Hello"
    text += ", World!"

    # Get and save the first stack item
    assert len(undo_manager.undo_stack) == 2
    saved_item = undo_manager.undo_stack[0]

    # Serialize it
    deletions_bytes, insertions_bytes = saved_item.encode()

    # Clear the undo manager
    undo_manager.clear()
    assert len(undo_manager.undo_stack) == 0
    assert str(text) == "Hello, World!"

    # Restore the item from bytes
    restored_item = StackItem.decode(deletions_bytes, insertions_bytes)

    # Push it back onto the stack
    undo_manager.push_undo_stack(restored_item)
    assert len(undo_manager.undo_stack) == 1

    # Verify we can undo with the restored item
    assert undo_manager.can_undo()
    undo_manager.undo()
    assert str(text) == ", World!"


def test_push_multiple_stack_items():
    """Test pushing multiple StackItems onto the undo stack"""
    doc = Doc()
    doc["text"] = text = Text()
    undo_manager = UndoManager(scopes=[text], capture_timeout_millis=0)

    # Make changes
    text += "First"
    text += " Second"
    text += " Third"

    # Save all items
    assert len(undo_manager.undo_stack) == 3
    saved_items = [item for item in undo_manager.undo_stack]

    # Clear and restore
    undo_manager.clear()
    assert len(undo_manager.undo_stack) == 0

    # Push items back in order
    for item in saved_items:
        undo_manager.push_undo_stack(item)

    assert len(undo_manager.undo_stack) == 3

    # Undo all changes
    undo_manager.undo()
    assert str(text) == "First Second"
    undo_manager.undo()
    assert str(text) == "First"
    undo_manager.undo()
    assert str(text) == ""


def test_push_undo_stack_deletion():
    """Push a deletion StackItem and undo to restore deleted content."""
    doc = Doc()
    doc["text"] = text = Text()
    undo_manager = UndoManager(scopes=[text], capture_timeout_millis=0)

    # Insert initial content -> first stack item
    text += "Hello world"
    assert str(text) == "Hello world"
    assert len(undo_manager.undo_stack) == 1

    # Perform deletion of suffix -> second stack item represents deletion
    del text[6:]
    assert str(text) == "Hello "
    assert len(undo_manager.undo_stack) == 2
    deletion_item = undo_manager.undo_stack[-1]

    # Serialize the deletion stack item
    deletions_bytes, insertions_bytes = deletion_item.encode()
    # Clear manager state (drops both items but leaves document as-is)
    undo_manager.clear()
    assert len(undo_manager.undo_stack) == 0
    assert str(text) == "Hello "

    # Recreate StackItem from bytes and push back
    restored = StackItem.decode(deletions_bytes, insertions_bytes)
    undo_manager.push_undo_stack(restored)
    assert len(undo_manager.undo_stack) == 1
    assert undo_manager.can_undo()

    # Undo should revert the deletion restoring original content
    undo_manager.undo()
    assert str(text) == "Hello world"
    assert not undo_manager.can_undo()


def test_stack_item_merge():
    """Merging two stack items should allow undoing both changes at once."""
    doc = Doc()
    doc["text"] = text = Text()
    undo_manager = UndoManager(scopes=[text], capture_timeout_millis=0)

    text += "Hello"
    text += " world"
    assert len(undo_manager.undo_stack) == 2
    item1, item2 = undo_manager.undo_stack

    merged = StackItem.merge(item1, item2)
    # Clear existing items and push merged
    undo_manager.clear()
    undo_manager.push_undo_stack(merged)
    assert len(undo_manager.undo_stack) == 1
    assert str(text) == "Hello world"

    # Undo should remove both insertions
    assert undo_manager.can_undo()
    undo_manager.undo()
    assert str(text) == ""
    assert not undo_manager.can_undo()
