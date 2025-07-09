import pytest
from pycrdt import Array, Doc, Map, XmlElement, XmlFragment, XmlText


def test_plain_text():
    doc1 = Doc()
    frag = XmlFragment()
    doc1["test"] = frag
    with doc1.transaction():
        frag.children.append("Hello")
        with doc1.transaction():
            frag.children.append(", World")
        frag.children.append("!")

    assert str(frag) == "Hello, World!"


def test_api():
    doc = Doc()
    frag = XmlFragment(
        [
            XmlText("Hello "),
            XmlElement("em", {"class": "bold"}, [XmlText("World")]),
            XmlText("!"),
        ]
    )

    with pytest.raises(RuntimeError) as excinfo:
        frag.integrated
    assert str(excinfo.value) == "Not integrated in a document yet"

    with pytest.raises(RuntimeError) as excinfo:
        frag.doc
    assert str(excinfo.value) == "Not integrated in a document yet"

    with pytest.raises(ValueError):
        frag.to_py()

    doc["test"] = frag
    assert frag.parent is None
    assert str(frag) == 'Hello <em class="bold">World</em>!'
    assert len(frag.children) == 3
    assert str(frag.children[0]) == "Hello "
    assert str(frag.children[1]) == '<em class="bold">World</em>'
    assert str(frag.children[2]) == "!"
    assert list(frag.children) == [frag.children[0], frag.children[1], frag.children[2]]
    assert frag.children[0].parent == frag
    assert hash(frag.children[0].parent) == hash(frag)
    assert frag != object()

    frag.children.insert(1, XmlElement("strong", None, ["wonderful"]))
    frag.children.insert(2, " ")
    assert str(frag) == 'Hello <strong>wonderful</strong> <em class="bold">World</em>!'
    assert len(frag.children) == 5

    el = frag.children[3]
    assert el.tag == "em"
    assert len(el.attributes) == 1
    assert el.attributes.get("class") == "bold"
    assert el.attributes["class"] == "bold"
    assert "class" in el.attributes
    assert el.attributes.get("non-existent") is None
    assert "non-existent" not in el.attributes
    with pytest.raises(KeyError):
        el.attributes["non-existent"]
    assert list(el.attributes) == [("class", "bold")]

    del frag.children[2]
    del frag.children[1]
    assert str(frag) == 'Hello <em class="bold">World</em>!'


def test_text():
    text = XmlText("Hello")
    assert text.to_py() == "Hello"

    doc = Doc()

    with pytest.raises(ValueError):
        doc["test"] = XmlText("test")

    doc["test"] = XmlFragment([text])

    assert str(text) == "Hello"
    assert text.to_py() == "Hello"
    assert len(text) == len("Hello")

    text.clear()
    assert str(text) == ""

    text += "Goodbye"
    assert str(text) == "Goodbye"

    text.insert(1, " ")
    assert str(text) == "G oodbye"
    del text[1]
    assert str(text) == "Goodbye"

    text.insert(1, "  ")
    del text[1:3]
    assert str(text) == "Goodbye"

    assert text.diff() == [("Goodbye", None)]
    text.format(1, 3, {"bold": True})
    assert text.diff() == [
        ("G", None),
        ("oo", {"bold": True}),
        ("dbye", None),
    ]

    text.insert_embed(0, b"PNG!", {"type": "image"})
    assert text.diff() == [
        (b"PNG!", {"type": "image"}),
        ("G", None),
        ("oo", {"bold": True}),
        ("dbye", None),
    ]

    text.insert(len(text), " World!", {"href": "some-url"})
    assert text.diff() == [
        (b"PNG!", {"type": "image"}),
        ("G", None),
        ("oo", {"bold": True}),
        ("dbye", None),
        (" World!", {"href": "some-url"}),
    ]

    del text[0]
    assert text.diff() == [
        ("G", None),
        ("oo", {"bold": True}),
        ("dbye", None),
        (" World!", {"href": "some-url"}),
    ]

    del text[0:3]
    assert text.diff() == [
        ("dbye", None),
        (" World!", {"href": "some-url"}),
    ]

    with pytest.raises(RuntimeError):
        del text[0:5:2]
    with pytest.raises(RuntimeError):
        del text[-1:5]
    with pytest.raises(RuntimeError):
        del text[1:-1]
    with pytest.raises(TypeError):
        del text["invalid"]

    doc["test2"] = XmlFragment([XmlText()])


def test_element_with_any_attribute():
    doc = Doc()

    doc["test"] = frag = XmlFragment()
    el = XmlElement("div")
    frag.children.append(el)
    el.attributes["class"] = {"a": True}
    assert el.attributes["class"] == {"a": True}
    assert list(el.attributes) == [("class", {"a": True})]
    assert len(el.attributes) == 1


def test_element():
    doc = Doc()

    with pytest.raises(ValueError):
        doc["test"] = XmlElement("test")

    with pytest.raises(ValueError):
        XmlElement()

    doc["test"] = frag = XmlFragment()

    el = XmlElement("div", {"class": "test"})
    frag.children.append(el)
    assert str(el) == '<div class="test"></div>'

    el = XmlElement("div", [("class", "test")])
    frag.children.append(el)
    assert str(el) == '<div class="test"></div>'

    el = XmlElement("div", None, [XmlText("Test")])
    frag.children.append(el)
    assert str(el) == "<div>Test</div>"

    el = XmlElement("div")
    frag.children.append(el)
    assert str(el) == "<div></div>"

    with pytest.raises(ValueError):
        el.to_py()

    el.attributes["class"] = "test"
    assert str(el) == '<div class="test"></div>'
    assert "class" in el.attributes
    assert el.attributes["class"] == "test"
    assert el.attributes.get("class") == "test"
    assert len(el.attributes) == 1
    assert list(el.attributes) == [("class", "test")]

    del el.attributes["class"]
    assert str(el) == "<div></div>"
    assert "class" not in el.attributes
    assert el.attributes.get("class") is None
    assert len(el.attributes) == 0
    assert list(el.attributes) == []

    node = XmlText("Hello")
    el.children.append(node)
    assert str(el) == "<div>Hello</div>"
    assert len(el.children) == 1
    assert str(el.children[0]) == "Hello"
    assert list(el.children) == [node]

    el.children[0] = XmlText("Goodbye")
    assert str(el) == "<div>Goodbye</div>"

    del el.children[0]
    assert str(el) == "<div></div>"

    el.children.append(XmlElement("foo"))
    el.children.append(XmlElement("bar"))
    el.children.append(XmlElement("baz"))
    assert str(el) == "<div><foo></foo><bar></bar><baz></baz></div>"

    del el.children[0:2]
    assert str(el) == "<div><baz></baz></div>"

    with pytest.raises(TypeError):
        del el.children["invalid"]
    with pytest.raises(IndexError):
        el.children[1]

    text = XmlText("foo")
    el.children.insert(0, text)
    assert str(el) == "<div>foo<baz></baz></div>"

    el2 = XmlElement("bar")
    el.children.insert(1, el2)
    assert str(el) == "<div>foo<bar></bar><baz></baz></div>"

    with pytest.raises(IndexError):
        el.children.insert(10, "test")
    with pytest.raises(ValueError):
        el.children.append(text)
    with pytest.raises(ValueError):
        el.children.append(el2)
    with pytest.raises(TypeError):
        el.children.append(object())


def test_observe():
    doc = Doc()
    doc["test"] = fragment = XmlFragment(["Hello world!"])
    events = []

    def callback(event):
        nonlocal fragment
        with pytest.raises(RuntimeError) as excinfo:
            fragment.children.append("text")
        assert (
            str(excinfo.value)
            == "Read-only transaction cannot be used to modify document structure"
        )
        events.append(event)

    sub = fragment.observe_deep(callback)  # noqa: F841

    fragment.children.append(XmlElement("em", None, ["This is a test"]))
    assert len(events) == 1
    assert len(events[0]) == 1
    assert events[0][0].children_changed is True
    assert str(events[0][0].target) == "Hello world!<em>This is a test</em>"
    assert events[0][0].path == []
    assert len(events[0][0].delta) == 2
    assert events[0][0].delta[0]["retain"] == 1
    assert str(events[0][0].delta[1]["insert"][0]) == "<em>This is a test</em>"

    events.clear()
    fragment.children[0].format(1, 3, {"bold": True})

    assert len(events) == 1
    assert len(events[0]) == 1
    assert str(events[0][0].target) == "H<bold>el</bold>lo world!"
    assert events[0][0].delta[0] == {"retain": 1}
    assert events[0][0].delta[1] == {"retain": 2, "attributes": {"bold": True}}


def test_xml_in_array():
    doc = Doc()
    array = doc.get("testmap", type=Array)
    frag = XmlFragment()
    array.append(frag)
    frag.children.append("Test XML!")

    assert len(array) == 1
    assert str(array[0]) == "Test XML!"

    with pytest.raises(TypeError):
        array.append(XmlText())
    with pytest.raises(TypeError):
        array.append(XmlElement("a"))
    assert len(array) == 1


def test_xml_in_map():
    doc = Doc()
    map = doc.get("testmap", type=Map)
    frag = map["testxml"] = XmlFragment()
    frag.children.append("Test XML!")

    assert len(map) == 1
    assert "testxml" in map
    assert str(map["testxml"]) == "Test XML!"

    with pytest.raises(TypeError):
        map["testtext"] = XmlText()
    with pytest.raises(TypeError):
        map["testel"] = XmlElement("a")
    assert len(map) == 1
