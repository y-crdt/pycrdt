"""Character positions include one position per embed, in either offset kind."""

import pytest
from pycrdt import Array, Doc, Map, Text


@pytest.fixture(params=["utf8", "utf16"])
def doc(request):
    # Exercise the independently-added GUID option alongside offset_kind.
    return Doc(offset_kind=request.param, guid="embed-offset-regression")


@pytest.fixture(
    params=["bytes", "dict", "number", "bool", "null", "empty_string", "map", "array", "text"]
)
def embed(request):
    return {
        "bytes": lambda: b"image",
        "dict": lambda: {"image": "url"},
        "number": lambda: 42,
        "bool": lambda: True,
        "null": lambda: None,
        "empty_string": lambda: "",
        "map": lambda: Map({"name": "mention"}),
        "array": lambda: Array(["item"]),
        "text": lambda: Text("nested 📊"),
    }[request.param]()


def test_embed_positions(doc, embed):
    doc["t"] = text = Text("A📊B")
    text.insert_embed(2, embed)
    assert doc.guid == "embed-offset-regression"
    assert str(text) == "A📊B"
    assert len(text) == 4
    assert text[:] == "A📊\ufffcB"
    assert list(text) == list(text[:])
    assert text[2] == "\ufffc"
    assert text[-1] == "B"
    assert "\ufffcB" in text

    text.insert(3, "界")
    assert text[:] == "A📊\ufffc界B"
    text.insert(len(text), "!")
    text += "?"
    assert text[:] == "A📊\ufffc界B!?"
    text.format(2, 4, {"bold": True})
    chunks = text.diff()
    assert chunks[1][1] == {"bold": True}  # embedded object
    assert chunks[2] == ("界", {"bold": True})

    text[2] = "X"  # replace exactly the embed, not the following character
    assert text[:] == "A📊X界B!?"
    del text[3]
    assert str(text) == "A📊XB!?"
    del text[-1]
    assert str(text) == "A📊XB!"


def test_embed_delete_and_replace_slices(doc, embed):
    doc["t"] = text = Text("📊界B")
    text.insert_embed(1, embed)
    text[1:3] = "Z"  # both the embed and the CJK character
    assert text.diff() == [("📊ZB", None)]
    text.insert_embed(0, b"first")
    text.insert_embed(len(text), b"last")
    del text[1:100]
    assert text.diff() == [(bytearray(b"first"), None)]
    assert len(text) == 1
    del text[0]
    assert text.diff() == []


def test_consecutive_embeds_and_literal_placeholders(doc):
    doc["t"] = text = Text("\0\ufffc📊e\u0301")
    text.insert_embed(0, Map())
    text.insert_embed(1, b"second")
    text.insert_embed(len(text), b"last")
    assert text[:] == "\ufffc\ufffc\0\ufffc📊e\u0301\ufffc"
    assert len(text) == 8
    text.insert(-1, "界")
    assert text[-2:] == "界\ufffc"
    text[-1] = "!"
    assert text[-2:] == "界!"
    del text[3]  # literal U+FFFC occupies three UTF-8 bytes, unlike an embed
    assert text[:] == "\ufffc\ufffc\0📊e\u0301界!"
    text.format(0, 2, {"bold": True})
    assert all(attrs == {"bold": True} for _, attrs in text.diff()[:2])
    text.clear()
    assert text.diff() == []


def test_offsets_survive_sync(doc):
    doc["t"] = text = Text("A📊B")
    text.insert_embed(2, Map({"n": 1}))
    peer = Doc(offset_kind="utf16" if doc.offset_kind == "utf8" else "utf8")
    peer.apply_update(doc.get_update())
    other = peer.get("t", type=Text)
    assert other[:] == text[:]
    other.insert(3, "界")
    del other[2]
    doc.apply_update(peer.get_update())
    assert text[:] == other[:] == "A📊界B"


@pytest.mark.parametrize("value", ["x", "📊", "several characters"])
def test_string_embeds_fail_closed_without_partial_edits(doc, value):
    # Yrs' public diff loses the distinction between these embeds and text.
    # Refuse ambiguous indexing rather than editing the wrong position.
    doc["t"] = text = Text("AB")
    text.insert_embed(1, value)
    before = text.diff()
    for operation in [
        lambda: len(text),
        lambda: text[:],
        lambda: list(text),
        lambda: text.insert(2, "X"),
        lambda: text.insert_embed(2, Map()),
        lambda: text.__delitem__(1),
        lambda: text.__setitem__(1, "X"),
        lambda: text.__setitem__(slice(0, 2), "X"),
        lambda: text.format(0, 2, {"bold": True}),
    ]:
        with pytest.raises(ValueError, match="string-valued embeds"):
            operation()
        assert text.diff() == before
    assert str(text) == "AB"
    text += "!"  # raw end-offset operations are still unambiguous
    assert str(text) == "AB!"
    text.clear()
    assert text.diff() == []
