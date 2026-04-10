import pytest
from anyio import TASK_STATUS_IGNORED, Event, create_task_group
from anyio.abc import TaskStatus
from pycrdt import Array, Assoc, Doc, Map, StickyIndex, Text

pytestmark = pytest.mark.anyio

hello = "Hello"
world = ", World"
sir = " Sir"
punct = "!"


def test_iterate():
    doc = Doc()
    doc["text"] = text = Text("abc")
    assert [char for char in text] == ["a", "b", "c"]


def test_str():
    doc1 = Doc()
    text1 = Text()
    doc1["text"] = text1
    with doc1.transaction():
        text1 += hello
        with doc1.transaction():
            text1 += world
        text1 += punct

    assert str(text1) == hello + world + punct

    doc2 = Doc()
    array2 = Array()
    doc2["array"] = array2
    text2 = Text("val")
    map2 = Map({"key": text2})
    array2.append(map2)
    assert str(array2) == '[{"key":"val"}]'


def test_api():
    doc = Doc()
    text = Text(hello + punct)

    with pytest.raises(RuntimeError) as excinfo:
        text.integrated
    assert str(excinfo.value) == "Not integrated in a document yet"

    with pytest.raises(RuntimeError) as excinfo:
        text.doc
    assert str(excinfo.value) == "Not integrated in a document yet"

    assert text.is_prelim
    assert text.prelim == hello + punct
    assert not text.is_integrated

    doc["text"] = text
    assert str(text) == hello + punct
    text.insert(len(hello), world)
    assert str(text) == hello + world + punct
    text.clear()
    assert len(text) == 0
    text[:] = hello + world + punct
    assert str(text) == hello + world + punct
    text[len(hello) : len(hello) + len(world)] = sir
    assert str(text) == hello + sir + punct
    # single character replacement
    text[len(text) - 1] = "?"
    assert str(text) == hello + sir + "?"
    # deletion with only an index
    del text[len(text) - 1]
    assert str(text) == hello + sir
    # deletion of an arbitrary range
    del text[len(hello) : len(hello) + len(sir)]
    assert str(text) == hello
    # deletion with start index == range length
    text += str(text)
    del text[len(hello) : 2 * len(hello)]
    assert str(text) == hello
    # deletion with a range of 0
    del text[len(hello) : len(hello)]
    assert str(text) == hello
    assert "".join([char for char in text]) == hello
    assert "el" in text

    with pytest.raises(RuntimeError) as excinfo:
        del text["a"]
    assert str(excinfo.value) == "Index not supported: a"

    with pytest.raises(RuntimeError) as excinfo:
        text["a"] = "b"
    assert str(excinfo.value) == "Index not supported: a"

    with pytest.raises(RuntimeError) as excinfo:
        text[1] = "ab"
    assert str(excinfo.value) == "Single item assigned value must have a length of 1, not 2"


def test_to_py():
    doc = Doc()
    doc["text"] = text = Text(hello)
    assert text.to_py() == hello


def test_prelim():
    text = Text(hello)
    assert text.to_py() == hello


def test_slice():
    doc = Doc()
    doc["text"] = text = Text(hello)

    for i, c in enumerate(hello):
        assert text[i] == c

    with pytest.raises(RuntimeError) as excinfo:
        text[1::2] = "a"
    assert str(excinfo.value) == "Step not supported"

    with pytest.raises(RuntimeError) as excinfo:
        text[-1:] = "a"
    assert str(excinfo.value) == "Negative start not supported"

    with pytest.raises(RuntimeError) as excinfo:
        text[:-1] = "a"
    assert str(excinfo.value) == "Negative stop not supported"


def test_formatting():
    doc = Doc()
    doc["text"] = text = Text("")

    text.insert(0, "hello ")
    assert len(text) == len("hello "), str(text)
    text.insert(len(text), "world", {"bold": True})
    text.insert(len(text), "! I have formatting!", {})
    text.format(len("hello world! "), len("hello world! I have formatting!") + 1, {"font-size": 32})
    text.insert_embed(len(text), b"png blob", {"type": "image"})

    diff = text.diff()

    assert diff == [
        ("hello ", None),
        ("world", {"bold": True}),
        ("! ", None),
        ("I have formatting!", {"font-size": 32}),
        (bytearray(b"png blob"), {"type": "image"}),
    ]


def test_observe():
    doc = Doc()
    doc["text"] = text = Text()
    events = []

    def callback(event):
        nonlocal text
        with pytest.raises(RuntimeError) as excinfo:
            text += world
        assert (
            str(excinfo.value)
            == "Read-only transaction cannot be used to modify document structure"
        )
        events.append(event)

    sub = text.observe(callback)  # noqa: F841
    text += hello
    assert str(events[0]) == """{target: Hello, delta: [{'insert': 'Hello'}], path: []}"""


async def test_iterate_events():
    doc = Doc()
    text = doc.get("text", type=Text)
    deltas = []

    async def iterate_events(done_event, *, task_status: TaskStatus[None] = TASK_STATUS_IGNORED):
        async with text.events() as events:
            task_status.started()
            idx = 0
            async for event in events:
                deltas.append(event.delta)
                if idx == 1:
                    done_event.set()
                    return
                idx += 1

    async with create_task_group() as tg:
        done_event = Event()
        await tg.start(iterate_events, done_event)
        text += "Hello"
        text += ", World!"
        await done_event.wait()
        text += " Goodbye."

    assert len(deltas) == 2
    assert deltas[0] == [{"insert": "Hello"}]
    assert deltas[1] == [{"retain": 5}, {"insert": ", World!"}]


@pytest.mark.parametrize("serialize", ["to_json", "encode"])
def test_sticky_index(serialize: str):
    first = "$$$"
    second = "-----*--"
    idx = second.index("*")

    doc0 = Doc()
    text0 = doc0.get("text", type=Text)
    text0 += first

    doc1 = Doc()
    text1 = doc1.get("text", type=Text)
    text1 += second

    assert text1[idx] == "*"
    sticky_index = text1.sticky_index(idx, Assoc.AFTER)
    assert sticky_index.assoc == Assoc.AFTER
    if serialize == "to_json":
        data = sticky_index.to_json()
        sticky_index = StickyIndex.from_json(data, text1)
    else:
        data = sticky_index.encode()
        sticky_index = StickyIndex.decode(data, text1)

    doc1.apply_update(doc0.get_update())
    assert str(text1) in (first + second, second + first)
    new_idx = sticky_index.get_index()
    assert text1[new_idx] == "*"


def test_unicode_emoji_insert():
    """Text.insert() after emoji characters should use character positions, not byte offsets."""
    doc = Doc()
    doc["text"] = text = Text()

    text += "A📊B"
    assert str(text) == "A📊B"
    assert len(text) == 3

    # Insert at position 2 = between 📊 and B
    text.insert(2, "X")
    assert str(text) == "A📊XB", f"Got {str(text)!r}, emoji insert position is wrong"


def test_unicode_emoji_sequential_inserts():
    """Sequential inserts after emoji should maintain correct positions."""
    doc = Doc()
    doc["text"] = text = Text()

    text += "# Analysis 📊\n"
    text.insert(len(text), "model = fit()\n")
    text.insert(len(text), "# 特征工程\n")
    text.insert(len(text), 'print("done")\n')

    expected = '# Analysis 📊\nmodel = fit()\n# 特征工程\nprint("done")\n'
    assert str(text) == expected, f"Got {str(text)!r}"


def test_unicode_emoji_len():
    """len() should return Python character count, not byte count."""
    doc = Doc()
    doc["text"] = text = Text()

    text += "A📊B"
    assert len(text) == 3  # 3 chars, not 6 bytes or 4 UTF-16 code units

    text += "🎉"
    assert len(text) == 4


def test_unicode_emoji_delete():
    """Deleting a character after an emoji should work correctly."""
    doc = Doc()
    doc["text"] = text = Text("A📊BC")

    del text[2]  # delete B (after emoji)
    assert str(text) == "A📊C", f"Got {str(text)!r}"


def test_unicode_emoji_delete_emoji():
    """Deleting an emoji character itself should work correctly."""
    doc = Doc()
    doc["text"] = text = Text("A📊B")

    del text[1]  # delete 📊
    assert str(text) == "AB", f"Got {str(text)!r}"


def test_unicode_emoji_slice_delete():
    """Slice deletion across emoji boundaries should work correctly."""
    doc = Doc()
    doc["text"] = text = Text("A📊B🎉C")

    del text[1:4]  # delete 📊B🎉
    assert str(text) == "AC", f"Got {str(text)!r}"


def test_unicode_emoji_setitem():
    """Replacing a character after an emoji should work correctly."""
    doc = Doc()
    doc["text"] = text = Text("A📊BC")

    text[2] = "X"  # replace B (after emoji)
    assert str(text) == "A📊XC", f"Got {str(text)!r}"


def test_unicode_emoji_slice_setitem():
    """Slice replacement spanning emoji should work correctly."""
    doc = Doc()
    doc["text"] = text = Text("A📊B🎉C")

    text[1:4] = "XYZ"  # replace 📊B🎉 with XYZ
    assert str(text) == "AXYZC", f"Got {str(text)!r}"


def test_unicode_cjk():
    """CJK characters (BMP, 1 UTF-16 code unit each) should work correctly."""
    doc = Doc()
    doc["text"] = text = Text()

    text += "价格"
    text.insert(2, "X")
    assert str(text) == "价格X", f"Got {str(text)!r}"
    assert len(text) == 3


def test_unicode_mixed_scripts():
    """Mixed ASCII, CJK, Cyrillic, and emoji in one text."""
    doc = Doc()
    doc["text"] = text = Text()

    text += "Hello"
    text.insert(5, " 世界")
    text.insert(8, " 📊")
    text.insert(11, " мир")
    text.insert(15, "!")

    expected = "Hello 世界 📊 мир!"
    assert str(text) == expected, f"Got {str(text)!r}"
    assert len(text) == 15


def test_unicode_supplementary_plane():
    """Characters outside BMP (require UTF-16 surrogate pairs)."""
    doc = Doc()
    doc["text"] = text = Text()

    # 𝒜 (U+1D49C) = Mathematical Script Capital A
    # 𠀀 (U+20000) = CJK Unified Ideograph Extension B
    text += "A𝒜B𠀀C"
    assert len(text) == 5

    text.insert(2, "X")  # between 𝒜 and B
    assert str(text) == "A𝒜XB𠀀C", f"Got {str(text)!r}"

    text.insert(5, "Y")  # between 𠀀 and C
    assert str(text) == "A𝒜XB𠀀YC", f"Got {str(text)!r}"


def test_unicode_cross_doc_sync():
    """Updates with Unicode content should sync correctly between two pycrdt docs."""
    doc1 = Doc()
    doc1["text"] = text1 = Text()

    # Capture updates from doc1
    updates = []
    doc1.observe(lambda event: updates.append(event.update))

    text1 += "# Analysis 📊\n"
    text1.insert(len(text1), "model = fit()\n")
    text1.insert(len(text1), "# 特征工程\n")

    # Apply to doc2
    doc2 = Doc()
    doc2["text"] = Text()
    for update in updates:
        doc2.apply_update(update)

    assert str(doc2["text"]) == str(text1), (
        f"Docs diverged: doc1={str(text1)!r} doc2={str(doc2['text'])!r}"
    )


# Test cases adapted from jupyter-server/jupyter_ydoc#370 (prior art for
# the workaround at the jupyter_ydoc layer). These exercise pycrdt's Text
# operations directly with the same Unicode edge cases. Each test sets
# initial content, then applies a granular edit (using SequenceMatcher on
# byte offsets, matching how jupyter_ydoc.YUnicode.set() works), and verifies
# the result is correct.
from difflib import SequenceMatcher


def _apply_diff(text, old_value, new_value):
    """Apply a granular diff from old_value to new_value using character-level
    SequenceMatcher. With the UTF-16 offset fix, pycrdt Text indices are
    character-based, so we diff on characters (not bytes)."""
    matcher = SequenceMatcher(a=old_value, b=new_value)

    offset = 0
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "replace":
            text[i1 + offset : i2 + offset] = new_value[j1:j2]
            offset += (j2 - j1) - (i2 - i1)
        elif tag == "delete":
            del text[i1 + offset : i2 + offset]
            offset -= i2 - i1
        elif tag == "insert":
            text.insert(i1 + offset, new_value[j1:j2])
            offset += j2 - j1


@pytest.mark.parametrize(
    "initial, updated",
    [
        # emojis swapped
        (
            "I like security 🎨 but I really love painting 🔒",
            "I like security 🔒 but I really love painting 🎨",
        ),
        # text changes, emojis stay in place
        (
            "Here is a rocket: ⭐ and a star: 🚀",
            "Here is a star: ⭐ and a rocket: 🚀",
        ),
        # change of text and emojis
        (
            "Here are some happy faces: 😀😁😂",
            "Here are some sad faces: 😞😢😭",
        ),
        # change of characters with combining marks
        (
            "Combining characters: á é í ó ú",
            "Combining characters: ú ó í é á",
        ),
        # flags (regional indicator sequences)
        (
            "Flags: 🇺🇸🇬🇧🇨🇦",
            "Flags: 🇨🇦🇬🇧🇺🇸",
        ),
        # Zero-width joiner sequences (family emoji)
        (
            "A family 👨\u200d👩\u200d👧\u200d👦 (with two children)",
            "A family 👨\u200d👩\u200d👧 (with one child)",
        ),
        # Mixed RTL/LTR text
        (
            "Hello שלום world",
            "Hello עולם world",
        ),
        # Keycap sequences
        (
            "Numbers: 1️⃣2️⃣3️⃣",
            "Numbers: 3️⃣2️⃣1️⃣",
        ),
        # Emoji at boundaries
        (
            "👋 middle text 🎉",
            "🎉 middle text 👋",
        ),
        # Japanese characters
        (
            "こんにちは世界",
            "こんにちは地球",
        ),
        # Julia math operators
        (
            "x ∈ [1, 2, 3] && y ≥ 0",
            "x ∉ [1, 2, 3] || y ≤ 0",
        ),
    ],
    ids=[
        "emoji_swap",
        "text_change_emoji_stay",
        "emoji_change",
        "combining_marks",
        "flags",
        "zwj_family",
        "rtl_ltr",
        "keycap",
        "emoji_boundaries",
        "japanese",
        "math_operators",
    ],
)
def test_unicode_granular_diff(initial, updated):
    """Granular text edits with multi-byte Unicode should produce correct results.

    Test cases adapted from jupyter-server/jupyter_ydoc#370.
    """
    doc = Doc()
    doc["text"] = text = Text()

    text += initial
    assert str(text) == initial

    _apply_diff(text, initial, updated)
    assert str(text) == updated, f"Got {str(text)!r}, expected {updated!r}"


def test_sticky_index_transaction():
    doc = Doc()
    text = doc.get("text", type=Text)
    sticky_index = text.sticky_index(0, Assoc.BEFORE)
    data = sticky_index.to_json()
    sticky_index = StickyIndex.from_json(data)

    with pytest.raises(RuntimeError) as excinfo:
        sticky_index.get_index()

    assert str(excinfo.value) == "No transaction available"

    with doc.transaction() as txn:
        idx = sticky_index.get_index(txn)

    assert idx == 0
