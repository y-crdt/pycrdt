import pytest
from pycrdt import (
    AttrRange,
    ContentAttribute,
    Doc,
    IdMap,
    IdSet,
    Text,
    UndoManager,
)

# JSON-compatible attribute values used to exercise the value conversion / serialization paths.
JSON_VALUES = [
    None,
    True,
    False,
    0,
    42,
    -7,
    2**53,  # large int (above the JS safe-integer range)
    3.14,
    "alice",
    "",
    [1, 2, 3],
    ["a", "b"],
    {"r": 1, "g": 2, "b": 3},
    {"nested": [1, {"deep": True}], "name": "x"},
    [],
    {},
]


def attr(name="author", value="alice"):
    return ContentAttribute(name, value)


# ContentAttribute


def test_content_attribute_name_and_value():
    a = ContentAttribute("author", "alice")
    assert a.name == "author"
    assert a.value == "alice"


@pytest.mark.parametrize("value", JSON_VALUES)
def test_content_attribute_value_types(value):
    a = ContentAttribute("k", value)
    assert a.value == value


def test_attribute_values_use_js_number_semantics():
    # Attribute values are encoded like native yrs/Yjs IdMaps, so they follow the same JS-number
    # rules as every other pycrdt value: integers within the JS safe-integer range come back as
    # floats, larger integers stay ints (BigInt).
    assert ContentAttribute("k", 5).value == 5.0
    assert isinstance(ContentAttribute("k", 5).value, float)
    assert isinstance(ContentAttribute("k", 2**53).value, int)
    # integers nested in arrays/objects normalize too
    nested = ContentAttribute("k", {"n": 1, "xs": [2, 3]}).value
    assert isinstance(nested["n"], float)
    assert nested["xs"] == [2.0, 3.0]


def test_content_attribute_equality_and_hash():
    a = ContentAttribute("author", "alice")
    b = ContentAttribute("author", "alice")
    c = ContentAttribute("author", "bob")
    d = ContentAttribute("editor", "alice")
    assert a == b
    assert a != c
    assert a != d
    # equal attributes hash equally and can live in a set
    assert hash(a) == hash(b)
    assert len({a, b, c}) == 2


def test_content_attribute_dict_key_order_invariant():
    # AttrValue equality/hashing uses sorted-key canonical JSON (BTreeMap-backed),
    # so dicts with same k/v but different insertion order must compare equal.
    a = ContentAttribute("k", {"a": 1, "b": 2})
    b = ContentAttribute("k", {"b": 2, "a": 1})
    assert a == b
    assert hash(a) == hash(b)


def test_content_attribute_repr():
    a = ContentAttribute("author", "alice")
    assert "author" in repr(a)
    assert "alice" in repr(a)


def test_content_attribute_invalid_value():
    with pytest.raises(TypeError):
        ContentAttribute("k", object())


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf")])
def test_content_attribute_rejects_non_finite(bad):
    with pytest.raises(ValueError):
        ContentAttribute("k", bad)


# IdMap basics


def test_empty_id_map():
    m = IdMap()
    assert m.is_empty()
    assert not m.contains(1, 0)


def test_insert_and_contains():
    m = IdMap()
    m.insert(1, 0, 5, [attr()])
    assert not m.is_empty()
    assert m.contains(1, 0)
    assert m.contains(1, 4)
    assert not m.contains(1, 5)
    assert not m.contains(2, 0)


def test_insert_empty_attributes_is_noop():
    m = IdMap()
    m.insert(1, 0, 5, [])
    assert m.is_empty()


def test_insert_zero_length_is_noop():
    m = IdMap()
    m.insert(1, 0, 0, [attr()])
    assert m.is_empty()


def test_remove():
    m = IdMap()
    m.insert(1, 0, 10, [attr()])
    m.remove(1, 0, 4)
    assert not m.contains(1, 0)
    assert not m.contains(1, 3)
    assert m.contains(1, 4)
    assert m.contains(1, 9)


# attributions / entries


def test_attributions():
    m = IdMap()
    m.insert(1, 0, 5, [ContentAttribute("author", "alice")])
    m.insert(1, 5, 3, [ContentAttribute("author", "bob")])

    ranges = m.attributions(1, 0, 8)
    assert all(isinstance(r, AttrRange) for r in ranges)
    spans = [(r.start, r.end, [(a.name, a.value) for a in r.attributes]) for r in ranges]
    assert spans == [
        (0, 5, [("author", "alice")]),
        (5, 8, [("author", "bob")]),
    ]


def test_attributions_fills_gaps_with_empty_attributes():
    m = IdMap()
    m.insert(1, 2, 2, [attr()])  # only [2, 4) is attributed

    ranges = m.attributions(1, 0, 6)
    spans = [(r.start, r.end, len(r.attributes)) for r in ranges]
    # leading gap [0,2), the attributed [2,4), trailing gap [4,6)
    assert spans == [(0, 2, 0), (2, 4, 1), (4, 6, 0)]


def test_attributions_of_unattributed_range():
    m = IdMap()
    ranges = m.attributions(1, 0, 3)
    assert len(ranges) == 1
    assert (ranges[0].start, ranges[0].end) == (0, 3)
    assert ranges[0].attributes == []


def test_entries():
    m = IdMap()
    m.insert(1, 0, 2, [ContentAttribute("a", 1)])
    m.insert(2, 0, 2, [ContentAttribute("b", 2)])

    entries = m.entries()
    by_client = {client: r for client, r in entries}
    assert set(by_client) == {1, 2}
    assert by_client[1].attributes[0].name == "a"
    assert by_client[2].attributes[0].name == "b"


# encode / decode


def test_encode_returns_bytes():
    m = IdMap()
    m.insert(1, 0, 5, [attr()])
    assert isinstance(m.encode(), bytes)


def test_encode_decode_empty():
    m = IdMap()
    assert IdMap.decode(m.encode()) == m


@pytest.mark.parametrize("value", JSON_VALUES)
def test_encode_decode_roundtrip_preserves_values(value):
    m = IdMap()
    m.insert(7, 3, 4, [ContentAttribute("k", value)])
    restored = IdMap.decode(m.encode())
    assert restored == m
    # the value round-trips numerically (integers normalize to floats per JS number rules, so
    # `42 == 42.0` still holds - see test_attribute_values_use_js_number_semantics)
    assert restored.attributions(7, 3, 4)[0].attributes[0].value == value


def test_encode_decode_multiple_clients_and_attrs():
    m = IdMap()
    m.insert(1, 0, 5, [ContentAttribute("author", "alice"), ContentAttribute("rev", 1)])
    m.insert(2, 10, 3, [ContentAttribute("author", "bob")])
    assert IdMap.decode(m.encode()) == m


def test_decode_invalid_bytes_raises():
    with pytest.raises(ValueError):
        IdMap.decode(b"\xff\xff\xff\xff\xff")


# IdSet interop


def test_as_id_set():
    m = IdMap()
    m.insert(1, 0, 5, [attr()])
    s = m.as_id_set()
    assert isinstance(s, IdSet)
    # round-trips through the IdSet codec
    assert IdSet.decode(s.encode()).encode() == s.encode()


def test_from_set_round_trips_ranges():
    m = IdMap()
    m.insert(1, 0, 5, [ContentAttribute("author", "alice")])
    m.insert(2, 4, 2, [ContentAttribute("author", "bob")])
    id_set = m.as_id_set()

    rebuilt = IdMap.from_set(id_set, [ContentAttribute("author", "carol")])
    # same ranges, new (overwritten) attribution
    assert rebuilt.as_id_set().encode() == id_set.encode()
    for _client, r in rebuilt.entries():
        assert [(a.name, a.value) for a in r.attributes] == [("author", "carol")]


def test_from_set_empty():
    rebuilt = IdMap.from_set(IdSet(), [attr()])
    assert rebuilt.is_empty()


# merge / intersect / diff


def test_merge_with():
    a = IdMap()
    a.insert(1, 0, 3, [attr("u", "a")])
    b = IdMap()
    b.insert(2, 0, 3, [attr("u", "b")])
    a.merge_with(b)
    assert a.contains(1, 0)
    assert a.contains(2, 0)


def test_merge_many_matches_merge_with():
    a = IdMap()
    a.insert(1, 0, 3, [attr("u", "a")])
    b = IdMap()
    b.insert(2, 0, 3, [attr("u", "b")])
    c = IdMap()
    c.insert(3, 0, 3, [attr("u", "c")])

    merged = IdMap.merge_many([a, b, c])
    assert merged.contains(1, 0)
    assert merged.contains(2, 0)
    assert merged.contains(3, 0)

    step = IdMap()
    step.merge_with(a)
    step.merge_with(b)
    step.merge_with(c)
    assert step == merged


def test_merge_many_empty():
    assert IdMap.merge_many([]).is_empty()


def test_intersect_with():
    a = IdMap()
    a.insert(1, 0, 10, [attr("t", "1")])
    b = IdMap()
    b.insert(1, 4, 10, [attr("t", "2")])
    a.intersect_with(b)
    assert not a.contains(1, 0)
    assert not a.contains(1, 3)
    assert a.contains(1, 4)
    assert a.contains(1, 9)
    assert not a.contains(1, 10)


def test_diff_with_id_map():
    a = IdMap()
    a.insert(1, 0, 10, [attr("t", "1")])
    sub = IdMap()
    sub.insert(1, 0, 3, [attr("t", "1")])
    a.diff_with(sub)
    assert not a.contains(1, 0)
    assert not a.contains(1, 2)
    assert a.contains(1, 3)
    assert a.contains(1, 9)


def test_diff_with_id_set():
    a = IdMap()
    a.insert(1, 0, 10, [attr("t", "1")])
    other = IdMap()
    other.insert(1, 0, 4, [attr("t", "x")])
    a.diff_with(other.as_id_set())
    assert not a.contains(1, 0)
    assert not a.contains(1, 3)
    assert a.contains(1, 4)


def test_diff_with_empty_id_set_is_noop():
    a = IdMap()
    a.insert(1, 0, 5, [attr()])
    before = a.encode()
    a.diff_with(IdSet())
    assert a.encode() == before


def test_diff_with_invalid_type_raises():
    a = IdMap()
    a.insert(1, 0, 5, [attr()])
    with pytest.raises(TypeError):
        a.diff_with(123)


# filter


def test_filter():
    m = IdMap()
    m.insert(1, 0, 2, [ContentAttribute("author", "alice")])
    m.insert(1, 2, 2, [ContentAttribute("author", "bob")])

    only_alice = m.filter(
        lambda attrs: any(a.name == "author" and a.value == "alice" for a in attrs)
    )
    assert only_alice.contains(1, 0)
    assert not only_alice.contains(1, 2)
    # the original map is unchanged
    assert m.contains(1, 0)
    assert m.contains(1, 2)


def test_filter_none():
    m = IdMap()
    m.insert(1, 0, 2, [attr()])
    assert m.filter(lambda attrs: False).is_empty()


def test_filter_propagates_exception():
    m = IdMap()
    m.insert(1, 0, 2, [attr()])

    def boom(attrs):
        raise ValueError("boom")

    with pytest.raises(ValueError, match="boom"):
        m.filter(boom)


# equality


def test_equality():
    a = IdMap()
    a.insert(1, 0, 5, [attr()])
    b = IdMap()
    b.insert(1, 0, 5, [attr()])
    c = IdMap()
    c.insert(1, 0, 5, [attr("author", "bob")])
    assert a == b
    assert a != c
    assert a != "not an id map"


# Pythonic operators, truthiness and iteration


def test_bool():
    assert not IdMap()
    m = IdMap()
    m.insert(1, 0, 3, [attr()])
    assert m
    assert bool(m) is (not m.is_empty())


def test_iter_matches_entries():
    m = IdMap()
    m.insert(1, 0, 2, [ContentAttribute("a", 1)])
    m.insert(2, 0, 2, [ContentAttribute("b", 2)])
    from_iter = [(c, r.start, r.end) for c, r in m]
    from_entries = [(c, r.start, r.end) for c, r in m.entries()]
    assert from_iter == from_entries
    assert len(list(m)) == 2


def test_or_union():
    a = IdMap()
    a.insert(1, 0, 3, [attr("u", "a")])
    b = IdMap()
    b.insert(2, 0, 3, [attr("u", "b")])
    union = a | b
    assert union.contains(1, 0)
    assert union.contains(2, 0)
    # operands are left unchanged
    assert not a.contains(2, 0)
    assert not b.contains(1, 0)


def test_or_matches_merge_with():
    a = IdMap()
    a.insert(1, 0, 3, [attr("u", "a")])
    b = IdMap()
    b.insert(2, 0, 3, [attr("u", "b")])
    via_method = IdMap()
    via_method.merge_with(a)
    via_method.merge_with(b)
    assert (a | b) == via_method


def test_ior_in_place():
    a = IdMap()
    a.insert(1, 0, 3, [attr("u", "a")])
    b = IdMap()
    b.insert(2, 0, 3, [attr("u", "b")])
    alias = a
    a |= b
    assert a.contains(1, 0)
    assert a.contains(2, 0)
    # truly in place: the same object is mutated, so an alias observes it
    assert alias is a
    assert alias.contains(2, 0)


def test_and_intersection():
    a = IdMap()
    a.insert(1, 0, 10, [attr("t", "1")])
    b = IdMap()
    b.insert(1, 4, 10, [attr("t", "2")])
    inter = a & b
    assert not inter.contains(1, 0)
    assert inter.contains(1, 4)
    assert inter.contains(1, 9)
    assert a.contains(1, 0)  # unchanged


def test_iand_in_place():
    a = IdMap()
    a.insert(1, 0, 10, [attr("t", "1")])
    b = IdMap()
    b.insert(1, 4, 10, [attr("t", "2")])
    a &= b
    assert not a.contains(1, 0)
    assert a.contains(1, 4)


def test_sub_difference_idmap():
    a = IdMap()
    a.insert(1, 0, 10, [attr("t", "1")])
    sub = IdMap()
    sub.insert(1, 0, 3, [attr("t", "1")])
    diff = a - sub
    assert not diff.contains(1, 0)
    assert diff.contains(1, 3)
    assert a.contains(1, 0)  # unchanged


def test_isub_difference_idmap():
    a = IdMap()
    a.insert(1, 0, 10, [attr("t", "1")])
    sub = IdMap()
    sub.insert(1, 0, 3, [attr("t", "1")])
    a -= sub
    assert not a.contains(1, 0)
    assert a.contains(1, 3)


def test_sub_difference_idset():
    a = IdMap()
    a.insert(1, 0, 10, [attr("t", "1")])
    other = IdMap()
    other.insert(1, 0, 4, [attr("t", "x")])
    diff = a - other.as_id_set()
    assert not diff.contains(1, 0)
    assert diff.contains(1, 4)


def test_isub_difference_idset():
    a = IdMap()
    a.insert(1, 0, 10, [attr("t", "1")])
    other = IdMap()
    other.insert(1, 0, 4, [attr("t", "x")])
    a -= other.as_id_set()
    assert not a.contains(1, 0)
    assert a.contains(1, 4)


@pytest.mark.parametrize("op", ["or", "and", "sub"])
def test_operators_reject_bad_operands(op):
    m = IdMap()
    m.insert(1, 0, 3, [attr()])
    with pytest.raises(TypeError):
        if op == "or":
            m | 5
        elif op == "and":
            m & 5
        else:
            m - 5


# realistic flow: attribute the IDs tracked by an UndoManager


def test_attribution_of_undo_insertions():
    doc = Doc()
    doc["text"] = text = Text()
    undo_manager = UndoManager(scopes=[text], capture_timeout_millis=0)

    text += "Hello"

    insertions = undo_manager.undo_stack[0].insertions
    assert not insertions.encode() == IdSet().encode()  # there were insertions

    # attach authorship metadata to every inserted ID
    attributed = IdMap.from_set(insertions, [ContentAttribute("author", "alice")])
    assert not attributed.is_empty()
    # the attributed ranges cover exactly the inserted IDs
    assert attributed.as_id_set().encode() == insertions.encode()
    for _client, r in attributed.entries():
        assert [(a.name, a.value) for a in r.attributes] == [("author", "alice")]
