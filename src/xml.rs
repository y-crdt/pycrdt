use pyo3::prelude::*;
use pyo3::IntoPyObjectExt;
use pyo3::types::{PyBool, PyDict, PyIterator, PyList, PyString, PyTuple};
use pyo3::{pyclass, pymethods, Bound, PyAny, PyObject, PyResult, Python};
use yrs::types::text::YChange;
use yrs::types::xml::{XmlEvent as _XmlEvent, XmlTextEvent as _XmlTextEvent};
use yrs::{
    DeepObservable, GetString as _, Observable as _, Text as _, TransactionMut, Xml as _, XmlElementPrelim, XmlElementRef, XmlFragment as _, XmlFragmentRef, XmlOut, XmlTextPrelim, XmlTextRef
};

use crate::subscription::Subscription;
use crate::type_conversions::{events_into_py, py_to_any, py_to_attrs, EntryChangeWrapper, ToPython};
use crate::transaction::Transaction;

/// Implements methods common to `XmlFragment`, `XmlElement`, and `XmlText`.
macro_rules! impl_xml_methods {
    (
        $typ:ident[
            $inner:ident
            // For `XmlFragment` and `XmlElement`, implements methods from `yrs::types::xml::XmlFragment`
            $(, fragment: $finner:ident)?
            // For `XmlElement` and `XmlText`, implements methods from `yrs::types::xml::Xml`
            $(, xml: $xinner:ident)?
        ] {
            // Methods specific to the type
            $($extra:tt)*
        }
    ) => {
        #[pymethods]
        impl $typ {
            fn parent<'py>(&self, py: Python<'py>) -> Bound<'py, PyAny> {
                let parent = self.$inner.parent();
                if parent.is_some() {
                    parent.unwrap().into_py(py)
                } else {
                    py.None().into_bound(py)
                }
            }

            fn get_string(&self, txn: &mut Transaction) -> String {
                let mut t0 = txn.transaction();
                let t1 = t0.as_mut().unwrap();
                let t = t1.as_ref();
                self.$inner.get_string(t)
            }

            fn len(&self, txn: &mut Transaction)  -> u32 {
                let mut t0 = txn.transaction();
                let t1 = t0.as_mut().unwrap();
                let t = t1.as_ref();
                self.$inner.len(t)
            }

            $(
                fn get<'py>(&self, py: Python<'py>, txn: &mut Transaction, index: u32) -> Bound<'py, PyAny> {
                    let mut t0 = txn.transaction();
                    let t1 = t0.as_mut().unwrap();
                    let t = t1.as_ref();
                    self.$finner.get(t, index).unwrap().into_py(py)
                }

                fn remove_range(&self, txn: &mut Transaction, index: u32, len: u32) {
                    let mut _t = txn.transaction();
                    let mut t = _t.as_mut().unwrap().as_mut();
                    self.$finner.remove_range(&mut t, index, len);
                }

                fn insert_str(&self, txn: &mut Transaction, index: u32, text: &str) -> XmlText {
                    let mut _t = txn.transaction();
                    let mut t = _t.as_mut().unwrap().as_mut();
                    self.$finner.insert(&mut t, index, XmlTextPrelim::new(text)).into()
                }

                fn insert_element_prelim(&self, txn: &mut Transaction, index: u32, tag: &str) -> XmlElement {
                    let mut _t = txn.transaction();
                    let mut t = _t.as_mut().unwrap().as_mut();
                    self.$finner.insert(&mut t, index, XmlElementPrelim::empty(tag)).into()
                }
            )?

            $(
                fn attributes<'py>(&self, py: Python<'py>, txn: &mut Transaction) -> Vec<(String, Bound<'py, PyAny>)> {
                    let mut t0 = txn.transaction();
                    let t1 = t0.as_mut().unwrap();
                    let t = t1.as_ref();
                    self.$xinner
                        .attributes(t)
                        .map(|(k, v)| (String::from(k), v.into_py(py)))
                        .collect()
                }

                fn attribute<'py>(&self, py: Python<'py>, txn: &mut Transaction, name: &str) -> Option<Bound<'py, PyAny>> {
                    let mut t0 = txn.transaction();
                    let t1 = t0.as_mut().unwrap();
                    let t = t1.as_ref();
                    Some(self.$xinner.get_attribute(t, name)?.into_py(py))
                }

                fn insert_attribute(&self, txn: &mut Transaction, name: &str, value: Bound<'_, PyAny>) {
                    let mut _t = txn.transaction();
                    let mut t = _t.as_mut().unwrap().as_mut();
                    self.$xinner.insert_attribute(&mut t, name, py_to_any(&value));
                }

                fn remove_attribute(&self, txn: &mut Transaction, name: &str) {
                    let mut _t = txn.transaction();
                    let mut t = _t.as_mut().unwrap().as_mut();
                    self.$xinner.remove_attribute(&mut t, &name);
                }

                fn siblings<'py>(&self, py: Python<'py>, txn: &mut Transaction) -> Vec<Bound<'py, PyAny>> {
                    let mut t0 = txn.transaction();
                    let t1 = t0.as_mut().unwrap();
                    let t = t1.as_ref();
                    self.$xinner.siblings(t).map(|node| node.into_py(py)).collect()
                }
            )?

            $($extra)*
        }

        impl std::hash::Hash for $typ {
            fn hash<H: std::hash::Hasher>(&self, state: &mut H) {
                let branch: &yrs::branch::Branch = self.$inner.as_ref();
                branch.id().hash(state)
            }
        }
    };
}

#[pyclass(eq, frozen, hash)]
#[derive(PartialEq, Eq)]
pub struct XmlFragment {
    pub fragment: XmlFragmentRef,
}

impl From<XmlFragmentRef> for XmlFragment {
    fn from(value: XmlFragmentRef) -> Self {
        XmlFragment { fragment: value }
    }
}

impl_xml_methods!(XmlFragment[fragment, fragment: fragment] {
    fn observe(&self, f: PyObject) -> Subscription {
        self.fragment.observe(move |txn, e| {
            Python::with_gil(|py| {
                let e = unsafe { XmlEvent::from_xml_event(e, txn, py) };
                if let Err(err) = f.call1(py, (e,)) {
                    err.restore(py)
                }
            });
        }).into()
    }

    fn observe_deep(&self, f: PyObject) -> Subscription {
        self.fragment.observe_deep(move |txn, events| {
            Python::with_gil(|py| {
                let events = events_into_py(py, txn, events);
                if let Err(err) = f.call1(py, (events,)) {
                    err.restore(py);
                }
            })
        }).into()
    }
});

#[pyclass(eq, frozen, hash)]
#[derive(PartialEq, Eq)]
pub struct XmlElement {
    pub element: XmlElementRef,
}

impl From<XmlElementRef> for XmlElement {
    fn from(value: XmlElementRef) -> Self {
        XmlElement { element: value }
    }
}

impl_xml_methods!(XmlElement[element, fragment: element, xml: element] {
    fn tag(&self) -> Option<String> {
        self.element.try_tag().map(|s| String::from(&**s))
    }

    fn observe(&self, f: PyObject) -> Subscription {
        self.element.observe(move |txn, e| {
            Python::with_gil(|py| {
                let e = unsafe { XmlEvent::from_xml_event(e, txn, py) };
                if let Err(err) = f.call1(py, (e,)) {
                    err.restore(py)
                }
            });
        }).into()
    }

    fn observe_deep(&self, f: PyObject) -> Subscription {
        self.element.observe_deep(move |txn, events| {
            Python::with_gil(|py| {
                let events = events_into_py(py, txn, events);
                if let Err(err) = f.call1(py, (events,)) {
                    err.restore(py);
                }
            })
        }).into()
    }
});

#[pyclass(eq, frozen, hash)]
#[derive(PartialEq, Eq)]
pub struct XmlText {
    pub text: XmlTextRef,
}

impl From<XmlTextRef> for XmlText {
    fn from(value: XmlTextRef) -> Self {
        XmlText { text: value }
    }
}

impl_xml_methods!(XmlText[text, xml: text] {
    #[pyo3(signature = (txn, index, text, attrs=None))]
    fn insert(&self, txn: &mut Transaction, index: u32, text: &str, attrs: Option<Bound<'_, PyIterator>>) -> PyResult<()> {
        let mut _t = txn.transaction();
        let mut t = _t.as_mut().unwrap().as_mut();
        if let Some(attrs) = attrs {
            let attrs = py_to_attrs(attrs)?;
            self.text.insert_with_attributes(&mut t, index, text, attrs);
        } else {
            self.text.insert(&mut t, index, text);
        }
        Ok(())
    }

    #[pyo3(signature = (txn, index, embed, attrs=None))]
    fn insert_embed<'py>(&self, txn: &mut Transaction, index: u32, embed: Bound<'py, PyAny>, attrs: Option<Bound<'_, PyIterator>>) -> PyResult<()> {
        let embed = py_to_any(&embed);
        let mut _t = txn.transaction();
        let mut t = _t.as_mut().unwrap().as_mut();
        if let Some(attrs) = attrs {
            let attrs = py_to_attrs(attrs)?;
            self.text.insert_embed_with_attributes(&mut t, index, embed, attrs);
        } else {
            self.text.insert_embed(&mut t, index, embed);
        }
        Ok(())
    }

    fn remove_range(&self, txn: &mut Transaction, index: u32, len: u32) {
        let mut _t = txn.transaction();
        let mut t = _t.as_mut().unwrap().as_mut();
        self.text.remove_range(&mut t, index, len);
    }

    fn format(&self, txn: &mut Transaction, index: u32, len: u32, attrs: Bound<'_, PyIterator>) -> PyResult<()> {
        let attrs = py_to_attrs(attrs)?;
        let mut _t = txn.transaction();
        let mut t = _t.as_mut().unwrap().as_mut();
        self.text.format(&mut t, index, len, attrs);
        Ok(())
    }

    fn diff<'py>(&self, py: Python<'py>, txn: &mut Transaction) -> Bound<'py, PyList> {
        let mut t0 = txn.transaction();
        let t1 = t0.as_mut().unwrap();
        let t = t1.as_ref();

        let iter = self.text.diff(t, YChange::identity)
            .into_iter()
            .map(|diff| {
                let attrs = diff.attributes.map(|attrs| {
                    let pyattrs = PyDict::new(py);
                    for (name, value) in attrs.into_iter() {
                        pyattrs.set_item(
                            PyString::intern(py, &*name),
                            value.into_py(py),
                        ).unwrap();
                    }
                    pyattrs.into_any()
                }).unwrap_or_else(|| py.None().into_bound(py));

                PyTuple::new(py, [
                    diff.insert.into_py(py),
                    attrs,
                ]).unwrap()
            });

        PyList::new(
            py,
            iter
        ).unwrap()
    }

    fn observe(&self, f: PyObject) -> Subscription {
        self.text.observe(move |txn, e| {
            Python::with_gil(|py| {
                let e = unsafe { XmlEvent::from_xml_text_event(e, txn, py) };
                if let Err(err) = f.call1(py, (e,)) {
                    err.restore(py)
                }
            });
        }).into()
    }

    fn observe_deep(&self, f: PyObject) -> Subscription {
        self.observe(f)
    }
});



#[pyclass(unsendable)]
pub struct XmlEvent {
    txn: *const TransactionMut<'static>,
    transaction: Option<Py<Transaction>>,
    #[pyo3(get)]
    children_changed: PyObject,
    #[pyo3(get)]
    target: PyObject,
    #[pyo3(get)]
    path: PyObject,
    #[pyo3(get)]
    delta: PyObject,
    #[pyo3(get)]
    keys: PyObject,
}

impl XmlEvent {
    pub unsafe fn from_xml_event<'py>(event: &_XmlEvent, txn: &TransactionMut, py: Python<'py>) -> Self {
        Self {
            txn: unsafe { std::mem::transmute::<&TransactionMut, &TransactionMut<'static>>(txn) },
            transaction: None,
            children_changed: PyBool::new(py, event.children_changed()).into_py_any(py).unwrap(),
            target: event.target().clone().into_py(py).unbind(),
            path: event.path().clone().into_py(py).unbind(),
            delta: PyList::new(
                py,
                event.delta(txn).into_iter().map(|d| d.into_py(py)),
            )
            .unwrap().into(),
            keys: {
                let dict = PyDict::new(py);
                for (key, value) in event.keys(txn).iter() {
                    dict.set_item(&**key, EntryChangeWrapper(value))
                        .unwrap();
                }
                dict.into()
            },
        }
    }

    pub unsafe fn from_xml_text_event(event: &_XmlTextEvent, txn: &TransactionMut, py: Python<'_>) -> Self {
        Self {
            txn: unsafe { std::mem::transmute::<&TransactionMut, &TransactionMut<'static>>(txn) },
            transaction: None,
            target: XmlOut::Text(event.target().clone()).into_py(py).unbind(),
            path: event.path().clone().into_py(py).unbind(),
            delta: PyList::new(
                py,
                event.delta(txn).into_iter().map(|d| d.clone().into_py(py)),
            ).unwrap().into(),
            keys: {
                let dict = PyDict::new(py);
                for (key, value) in event.keys(txn).iter() {
                    dict.set_item(&**key, EntryChangeWrapper(value))
                        .unwrap();
                }
                dict.into()
            },
            children_changed: py.None(),
        }
    }
}

#[pymethods]
impl XmlEvent {
    #[getter]
    fn transaction(&mut self, py: Python<'_>) -> Py<Transaction> {
        self.transaction
            .get_or_insert_with(|| Transaction::from(unsafe { &*self.txn }).into_pyobject(py).unwrap().unbind())
            .clone_ref(py)
    }

    fn __repr__(&mut self) -> String {
        format!(
            "XmlEvent(children_changed={}, target={}, path={}, delta={}, keys={})",
            self.children_changed, self.target, self.path, self.delta, self.keys,
        )
    }
}
