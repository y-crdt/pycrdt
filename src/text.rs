use crate::thread_affinity::{CallbackPtr, CallbackRef, CallbackScope, CallbackLifetime, ThreadAffinity};
use pyo3::prelude::*;
use pyo3::IntoPyObjectExt;
use pyo3::types::{PyDict, PyIterator, PyList, PyString, PyTuple};
use yrs::{
    Assoc,
    GetString,
    DeepObservable,
    IndexedSequence,
    Observable,
    TextRef,
    Text as _Text,
    TransactionMut,
};
use yrs::types::array::ArrayPrelim;
use yrs::types::map::MapPrelim;
use yrs::types::text::{TextEvent as _TextEvent, TextPrelim, YChange};
use crate::transaction::Transaction;
use crate::subscription::Subscription;
use crate::type_conversions::{events_into_py, py_to_any, py_to_attrs, ToPython};
use crate::array::Array;
use crate::map::Map;
use crate::sticky_index::StickyIndex;


#[pyclass]
pub struct Text {
    pub text: TextRef,
}

impl Text {
    pub fn from(text: TextRef) -> Self {
        Text {
            text,
        }
    }
}

#[pymethods]
impl Text {
    fn len(&self, txn: &mut Transaction) -> PyResult<u32> {
        let mut t0 = txn.transaction()?;
        let t1 = t0.as_mut().unwrap();
        let t = t1.as_ref();
        let len = self.text.len(t);
        Ok(len)
    }

    #[pyo3(signature = (txn, index, chunk, attrs=None))]
    fn insert(
        &self,
        txn: &mut Transaction,
        index: u32,
        chunk: &str,
        attrs: Option<Bound<'_, PyIterator>>,
    ) -> PyResult<()> {
        let mut _t = txn.transaction()?;
        let mut t = _t.as_mut().unwrap().as_mut();
        if let Some(attrs) = attrs {
            let attrs = py_to_attrs(attrs)?;
            self.text
                .insert_with_attributes(&mut t, index, chunk, attrs);
        } else {
            self.text.insert(&mut t, index, chunk);
        }
        Ok(())
    }

    #[pyo3(signature = (txn, index, embed, attrs=None))]
    fn insert_embed(
        &self,
        txn: &mut Transaction,
        index: u32,
        embed: Bound<'_, PyAny>,
        attrs: Option<Bound<'_, PyIterator>>,
    ) -> PyResult<()> {
        let embed = py_to_any(&embed);
        let mut _t = txn.transaction()?;
        let mut t = _t.as_mut().unwrap().as_mut();
        if let Some(attrs) = attrs {
            let attrs = py_to_attrs(attrs)?;
            self.text
                .insert_embed_with_attributes(&mut t, index, embed, attrs);
        } else {
            self.text.insert_embed(&mut t, index, embed);
        }
        Ok(())
    }

    #[pyo3(signature = (txn, index, attrs=None))]
    fn insert_array_prelim<'py>(
        &self,
        txn: &mut Transaction,
        index: u32,
        attrs: Option<Bound<'_, PyIterator>>,
    ) -> PyResult<Array> {
        let mut _t = txn.transaction()?;
        let mut t = _t.as_mut().unwrap().as_mut();
        let integrated;
        if let Some(attrs) = attrs {
            let attrs = py_to_attrs(attrs)?;
            integrated = self.text.insert_embed_with_attributes(
                &mut t,
                index,
                ArrayPrelim::default(),
                attrs,
            );
        } else {
            integrated = self
                .text
                .insert_embed(&mut t, index, ArrayPrelim::default());
        }
        let shared = Array::from(integrated);
        Ok(shared)
    }

    #[pyo3(signature = (txn, index, attrs=None))]
    fn insert_map_prelim<'py>(
        &self,
        txn: &mut Transaction,
        index: u32,
        attrs: Option<Bound<'_, PyIterator>>,
    ) -> PyResult<Map> {
        let mut _t = txn.transaction()?;
        let mut t = _t.as_mut().unwrap().as_mut();
        let integrated;
        if let Some(attrs) = attrs {
            let attrs = py_to_attrs(attrs)?;
            integrated =
                self.text
                    .insert_embed_with_attributes(&mut t, index, MapPrelim::default(), attrs);
        } else {
            integrated = self.text.insert_embed(&mut t, index, MapPrelim::default());
        }
        let shared = Map::from(integrated);
        Ok(shared)
    }

    #[pyo3(signature = (txn, index, attrs=None))]
    fn insert_text_prelim<'py>(
        &self,
        txn: &mut Transaction,
        index: u32,
        attrs: Option<Bound<'_, PyIterator>>,
    ) -> PyResult<Text> {
        let mut _t = txn.transaction()?;
        let mut t = _t.as_mut().unwrap().as_mut();
        let integrated;
        if let Some(attrs) = attrs {
            let attrs = py_to_attrs(attrs)?;
            integrated =
                self.text
                    .insert_embed_with_attributes(&mut t, index, TextPrelim::default(), attrs);
        } else {
            integrated = self.text.insert_embed(&mut t, index, TextPrelim::default());
        }
        let shared = Text::from(integrated);
        Ok(shared)
    }

    fn format(
        &self,
        txn: &mut Transaction,
        index: u32,
        len: u32,
        attrs: Bound<'_, PyIterator>,
    ) -> PyResult<()> {
        let mut _t = txn.transaction()?;
        let mut t = _t.as_mut().unwrap().as_mut();
        let attrs = py_to_attrs(attrs)?;
        self.text.format(&mut t, index, len, attrs);
        Ok(())
    }

    fn remove_range(&self, txn: &mut Transaction, index: u32, len: u32) -> PyResult<()> {
        let mut _t = txn.transaction()?;
        let mut t = _t.as_mut().unwrap().as_mut();
        self.text.remove_range(&mut t, index, len);
        Ok(())
    }

    fn get_string<'py>(
        &mut self,
        py: Python<'py>,
        txn: &mut Transaction,
    ) -> PyResult<Bound<'py, PyString>> {
        let mut t0 = txn.transaction()?;
        let t1 = t0.as_mut().unwrap();
        let t = t1.as_ref();
        let s = self.text.get_string(t);
        Ok(PyString::new(py, &s))
    }

    fn diff<'py>(&self, py: Python<'py>, txn: &mut Transaction) -> PyResult<Bound<'py, PyList>> {
        let mut t0 = txn.transaction()?;
        let t1 = t0.as_mut().unwrap();
        let t = t1.as_ref();

        let iter = self
            .text
            .diff(t, YChange::identity)
            .into_iter()
            .map(|diff| {
                let attrs = diff
                    .attributes
                    .map(|attrs| {
                        let pyattrs = PyDict::new(py);
                        for (name, value) in attrs.into_iter() {
                            pyattrs
                                .set_item(PyString::intern(py, &*name), value.into_py(py))
                                .unwrap();
                        }
                        pyattrs.into_any()
                    })
                    .unwrap_or_else(|| py.None().into_bound(py));

                PyTuple::new(py, [diff.insert.into_py(py), attrs]).unwrap()
            });
        Ok(PyList::new(py, iter).unwrap())
    }

    fn sticky_index<'py>(
        &self,
        py: Python<'py>,
        txn: &mut Transaction,
        index: u32,
        assoc: i8,
    ) -> PyResult<Py<StickyIndex>> {
        let mut _t = txn.transaction()?;
        let t = _t.as_mut().unwrap().as_mut();
        let _assoc: Assoc;
        match assoc {
            0 => _assoc = Assoc::After,
            _ => _assoc = Assoc::Before,
        }
        let sticky_index = self.text.sticky_index(t, index, _assoc);
        let s: Py<StickyIndex> = Py::new(py, StickyIndex::from(sticky_index))?;
        Ok(s)
    }

    fn observe(&mut self, py: Python<'_>, f: Py<PyAny>) -> PyResult<Py<Subscription>> {
        let target = self.text.clone();
        let (sub, callback) = Subscription::new(f, move |key| {
            let _ = target.unobserve(key);
        });
        self.text.observe(callback.key, move |txn, e| {
            Python::attach(|py| {
                let Some(f) = callback.get(py) else {
                    return;
                };
                let scope = CallbackScope::new();
                let e = TextEvent::new(e, txn, scope.lifetime());
                if let Err(err) = f.call1(py, (e,)) {
                    err.restore(py)
                }
            });
        });
        let s: Py<Subscription> = Py::new(py, sub)?;
        Ok(s)
    }

    pub fn observe_deep(&mut self, py: Python<'_>, f: Py<PyAny>) -> PyResult<Py<Subscription>> {
        let target = self.text.clone();
        let (sub, callback) = Subscription::new(f, move |key| {
            let _ = target.unobserve_deep(key);
        });
        self.text.observe_deep(callback.key, move |txn, events| {
            Python::attach(|py| {
                let Some(f) = callback.get(py) else {
                    return;
                };
                let scope = CallbackScope::new();
                let events = events_into_py(py, txn, events, scope.lifetime());
                if let Err(err) = f.call1(py, (events,)) {
                    err.restore(py)
                }
            });
        });
        Py::new(py, sub)
    }
}

#[pyclass]
pub struct TextEvent {
    event: CallbackPtr<_TextEvent>,
    txn: CallbackPtr<TransactionMut<'static>>,
    thread: ThreadAffinity,
    target: Option<Py<PyAny>>,
    delta: Option<Py<PyAny>>,
    path: Option<Py<PyAny>>,
    transaction: Option<Py<PyAny>>,
}

impl TextEvent {
    pub fn new(event: &_TextEvent, txn: &TransactionMut, lifetime: CallbackLifetime) -> Self {
        let event = event as *const _TextEvent;
        let txn = unsafe { std::mem::transmute::<&TransactionMut, &TransactionMut<'static>>(txn) };
        let text_event = TextEvent {
            event: unsafe { CallbackPtr::new(event, lifetime.clone()) },
            txn: unsafe { CallbackPtr::new(txn, lifetime) },
            thread: ThreadAffinity::new(),
            target: None,
            delta: None,
            path: None,
            transaction: None,
        };
        text_event
    }

    fn event(&self) -> PyResult<CallbackRef<'_, _TextEvent>> {
        self.event.borrow()
    }

    fn txn(&self) -> PyResult<CallbackRef<'_, TransactionMut<'static>>> {
        self.txn.borrow()
    }
}

#[pymethods]
impl TextEvent {
    #[getter]
    pub fn transaction<'py>(&mut self, py: Python<'py>) -> PyResult<Bound<'py, PyAny>> {
        self.thread.check();
        let _lease = self.txn.borrow()?;
        Ok(if let Some(transaction) = &self.transaction {
            transaction.clone_ref(py).into_bound(py)
        } else {
            let transaction = Transaction::borrowed(self.txn.clone())
                .into_bound_py_any(py)
                .unwrap();
            self.transaction = Some(transaction.clone().unbind());
            transaction
        })
    }

    #[getter]
    pub fn target<'py>(&mut self, py: Python<'py>) -> PyResult<Bound<'py, PyAny>> {
        self.thread.check();
        Ok(if let Some(target) = &self.target {
            target.clone_ref(py).into_bound(py)
        } else {
            let target = Text::from(self.event()?.target().clone())
                .into_bound_py_any(py)
                .unwrap();
            self.target = Some(target.clone().unbind());
            target
        })
    }

    #[getter]
    pub fn path<'py>(&mut self, py: Python<'py>) -> PyResult<Bound<'py, PyAny>> {
        self.thread.check();
        Ok(if let Some(path) = &self.path {
            path.clone_ref(py).into_bound(py)
        } else {
            let path = self.event()?.path().into_py(py);
            self.path = Some(path.clone().unbind());
            path
        })
    }

    #[getter]
    pub fn delta<'py>(&mut self, py: Python<'py>) -> PyResult<Bound<'py, PyAny>> {
        self.thread.check();
        Ok(if let Some(delta) = &self.delta {
            delta.clone_ref(py).into_bound(py)
        } else {
            let delta = {
                let event = self.event()?;
                let txn = self.txn()?;
                let values = event.delta(&*txn).iter().map(|d| d.clone().into_py(py));
                PyList::new(py, values)
                    .unwrap()
                    .into_bound_py_any(py)
                    .unwrap()
            };
            self.delta = Some(delta.clone().unbind());
            delta
        })
    }

    fn __repr__(&mut self, py: Python<'_>) -> PyResult<String> {
        self.thread.check();
        let target = self.target(py)?;
        let delta = self.delta(py)?;
        let path = self.path(py)?;
        Ok(format!("TextEvent(target={target}, delta={delta}, path={path})"))
    }
}
