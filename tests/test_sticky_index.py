import pytest
from pycrdt import Array, Assoc, Doc, Map, StickyIndex, Text

SEQUENCE_CASES = [
    pytest.param(Text, "abc", id="text"),
    pytest.param(Array, ["a", "b", "c"], id="array"),
]
EMPTY_SEQUENCE_CASES = [
    pytest.param(Text, "", id="text"),
    pytest.param(Array, [], id="array"),
]


@pytest.mark.parametrize(("sequence_type", "value"), SEQUENCE_CASES)
@pytest.mark.parametrize("assoc", [Assoc.AFTER, Assoc.BEFORE])
@pytest.mark.parametrize("index", [0, 1, 3], ids=["start", "interior", "end"])
def test_resolve_owner_at_each_position(sequence_type, value, assoc: Assoc, index: int):
    doc = Doc(client_id=1)
    sequence = sequence_type(value)
    doc["owner"] = sequence
    state = doc.get_state()

    sticky_index = sequence.sticky_index(index, assoc)
    assert sticky_index.resolve(sequence) == index
    assert sticky_index.get_index() == index

    decoded = StickyIndex.decode(sticky_index.encode(), sequence)
    assert decoded.resolve(sequence) == index
    assert decoded.get_index() == index
    assert doc.get_state() == state


@pytest.mark.parametrize(("sequence_type", "value"), SEQUENCE_CASES)
@pytest.mark.parametrize("assoc", [Assoc.AFTER, Assoc.BEFORE])
def test_resolve_owner_across_replica_and_fresh_wrapper(sequence_type, value, assoc: Assoc):
    source = Doc(client_id=1)
    source_root = source.get("root", type=Map)
    owner = sequence_type(value)
    source_root["owner"] = owner
    encoded = owner.sticky_index(2, assoc).encode()

    replica = Doc(client_id=2)
    replica.apply_update(source.get_update())
    replica_root = replica.get("root", type=Map)
    replica_owner = replica_root["owner"]
    decoded = StickyIndex.decode(encoded, replica_owner)

    assert decoded.resolve(replica_owner) == 2
    assert decoded.resolve(replica_root["owner"]) == 2
    assert decoded.get_index() == 2


@pytest.mark.parametrize(("sequence_type", "value"), EMPTY_SEQUENCE_CASES)
@pytest.mark.parametrize("assoc", [Assoc.AFTER, Assoc.BEFORE])
def test_resolve_empty_sequence(sequence_type, value, assoc: Assoc):
    doc = Doc(client_id=1)
    sequence = sequence_type(value)
    doc["owner"] = sequence

    sticky_index = sequence.sticky_index(0, assoc)
    decoded = StickyIndex.from_json(sticky_index.to_json(), sequence)

    assert decoded.resolve(sequence) == 0
    assert decoded.get_index() == 0


@pytest.mark.parametrize(("sequence_type", "value"), SEQUENCE_CASES)
@pytest.mark.parametrize("assoc", [Assoc.AFTER, Assoc.BEFORE])
@pytest.mark.parametrize("serialization", ["binary", "json"])
def test_reject_sibling_owner(sequence_type, value, assoc: Assoc, serialization: str):
    doc = Doc(client_id=1)
    root = doc.get("root", type=Map)
    sibling = sequence_type(value)
    owner = sequence_type(value)
    root["sibling"] = sibling
    root["owner"] = owner
    sticky_index = owner.sticky_index(2, assoc)

    if serialization == "binary":
        decoded = StickyIndex.decode(sticky_index.encode(), sibling)
    else:
        decoded = StickyIndex.from_json(sticky_index.to_json(), sibling)

    state = doc.get_state()
    assert decoded.resolve(sibling) is None
    assert decoded.resolve(owner) == 2
    with pytest.raises(ValueError, match="Sticky index cannot be resolved"):
        decoded.get_index()
    with doc.transaction() as txn:
        with pytest.raises(ValueError, match="Sticky index cannot be resolved"):
            decoded.get_index(txn)
    assert doc.get_state() == state


@pytest.mark.parametrize("assoc", [Assoc.AFTER, Assoc.BEFORE])
def test_reject_cross_kind_owner(assoc: Assoc):
    doc = Doc(client_id=1)
    root = doc.get("root", type=Map)
    text = Text("abc")
    array = Array(["a", "b", "c"])
    root["text"] = text
    root["array"] = array

    for owner, sibling in ((text, array), (array, text)):
        decoded = StickyIndex.decode(owner.sticky_index(2, assoc).encode(), sibling)
        assert decoded.resolve(sibling) is None
        with pytest.raises(ValueError, match="Sticky index cannot be resolved"):
            decoded.get_index()


@pytest.mark.parametrize(("sequence_type", "value"), SEQUENCE_CASES)
def test_reject_deleted_owner(sequence_type, value):
    doc = Doc(client_id=1)
    root = doc.get("root", type=Map)
    owner = sequence_type(value)
    root["owner"] = owner
    sticky_index = owner.sticky_index(1, Assoc.AFTER)

    del root["owner"]

    assert sticky_index.resolve(owner) is None
    with pytest.raises(ValueError, match="Sticky index cannot be resolved"):
        sticky_index.get_index()


@pytest.mark.parametrize(("sequence_type", "value"), EMPTY_SEQUENCE_CASES)
def test_reject_detached_sequence(sequence_type, value):
    doc = Doc(client_id=1)
    owner = doc.get("owner", type=sequence_type)
    sticky_index = owner.sticky_index(0, Assoc.BEFORE)
    detached = sequence_type(value)
    decoded = StickyIndex.decode(sticky_index.encode(), detached)

    assert sticky_index.resolve(detached) is None
    with doc.transaction() as txn:
        with pytest.raises(ValueError, match="Sticky index cannot be resolved"):
            decoded.get_index(txn)


def test_unresolvable_position_returns_python_error_or_none():
    doc = Doc(client_id=1)
    text = doc.get("text", type=Text)
    data = {"item": {"client": 999, "clock": 0}, "assoc": 0}
    sticky_index = StickyIndex.from_json(data, text)

    assert sticky_index.resolve(text) is None
    with pytest.raises(ValueError, match="Sticky index cannot be resolved"):
        sticky_index.get_index()

    sticky_index = StickyIndex.from_json(data)
    with doc.transaction() as txn:
        with pytest.raises(ValueError, match="Sticky index cannot be resolved"):
            sticky_index.get_index(txn)


@pytest.mark.parametrize("data", [b"", b"\xff"])
def test_malformed_binary_raises_value_error(data: bytes):
    with pytest.raises(ValueError, match="Cannot decode sticky index"):
        StickyIndex.decode(data)


@pytest.mark.parametrize("data", [{}, {"item": "invalid", "assoc": 0}])
def test_malformed_json_raises_value_error(data: dict):
    with pytest.raises(ValueError, match="Cannot decode sticky index JSON"):
        StickyIndex.from_json(data)


@pytest.mark.parametrize(("sequence_type", "value"), SEQUENCE_CASES)
@pytest.mark.parametrize("assoc", [Assoc.AFTER, Assoc.BEFORE])
def test_out_of_range_position_raises_value_error(sequence_type, value, assoc: Assoc):
    doc = Doc(client_id=1)
    sequence = sequence_type(value)
    doc["owner"] = sequence

    with pytest.raises(ValueError, match="Index out of range"):
        sequence.sticky_index(4, assoc)


@pytest.mark.parametrize(("sequence_type", "value"), SEQUENCE_CASES)
@pytest.mark.parametrize("serialization", ["binary", "json"])
def test_get_index_with_transaction_remains_compatible(sequence_type, value, serialization: str):
    doc = Doc(client_id=1)
    sequence = sequence_type(value)
    doc["owner"] = sequence
    sticky_index = sequence.sticky_index(1, Assoc.BEFORE)

    if serialization == "binary":
        decoded = StickyIndex.decode(sticky_index.encode())
    else:
        decoded = StickyIndex.from_json(sticky_index.to_json())

    assert decoded.assoc == Assoc.BEFORE
    with doc.transaction() as txn:
        assert decoded.get_index(txn) == 1
