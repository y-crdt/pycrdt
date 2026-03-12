import gc
import weakref

from pycrdt import Doc, Map, Text


def test_observe_bound_method_gc():
    """Bound method callbacks should be garbage collected after unobserve()."""
    freed = []

    class Observer:
        def on_change(self, event):
            pass

    doc = Doc()
    doc["text"] = text = Text()
    observer = Observer()
    weakref.finalize(observer, freed.append, True)

    sub = text.observe(observer.on_change)

    # make an update (required for #371 to manifest in <=0.12.48)
    text += "hello"

    text.unobserve(sub)
    del observer

    gc.collect()
    assert freed, "Observer was not garbage collected after unobserve()"


def test_observe_deep_bound_method_gc():
    """Bound method callbacks should be garbage collected after unobserve() (deep)."""
    freed = []

    class Observer:
        def on_change(self, events):
            pass

    doc = Doc()
    doc["map"] = m = Map()
    observer = Observer()
    weakref.finalize(observer, freed.append, True)

    sub = m.observe_deep(observer.on_change)

    # make an update (required for #371 to manifest in <=0.12.48)
    m["key"] = "value"

    m.unobserve(sub)
    del observer

    gc.collect()
    assert freed, "Observer was not garbage collected after unobserve() (deep)"
