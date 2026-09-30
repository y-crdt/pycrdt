import gc
import weakref

import pytest
from pycrdt import Doc, Map


@pytest.mark.parametrize("method", ["observe", "observe_deep"])
def test_observe_bound_method_gc(method):
    """Bound method callbacks should be garbage collected after unobserve()."""

    class Observer:
        def on_change(self, event):
            pass

    doc = Doc()
    map_ = doc.get("map", type=Map)
    observer = Observer()
    freed = []
    weakref.finalize(observer, freed.append, True)
    sub = getattr(map_, method)(observer.on_change)
    map_["key"] = "value"
    map_.unobserve(sub)
    del observer
    gc.collect()
    assert freed, "Observer was not garbage collected after unobserve()"
