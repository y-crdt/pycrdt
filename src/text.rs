use pyo3::prelude::*;
use pyo3::IntoPyObjectExt;
use pyo3::types::{PyDict, PyIterator, PyList, PyString, PyTuple};
use yrs::{
    Assoc,
    GetString,
    IndexedSequence,
    Observable,
    TextRef,
    Text as _Text,
    TransactionMut,
};
use yrs::types::text::{TextEvent as _TextEvent, YChange};
use crate::transaction::Transaction;
use crate::subscription::Subscription;
use crate::type_conversions::{py_to_any, py_to_attrs, ToPython};
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
    fn len(&self, txn: &mut Transaction)  -> PyResult<u32> {
        let mut t0 = txn.transaction();
        let t1 = t0.as_mut().unwrap();
        let t = t1.as_ref();
        let len = self.text.len(t);
        Ok(len)
    }

    #[pyo3(signature = (txn, index, chunk, attrs=None))]
    fn insert(&self, txn: &mut Transaction, index: u32, chunk: &str, attrs: Option<Bound<'_, PyIterator>>) -> PyResult<()> {
        let mut _t = txn.transaction();
        let mut t = _t.as_mut().unwrap().as_mut();
        if let Some(attrs) = attrs {
            let attrs = py_to_attrs(attrs)?;
            self.text.insert_with_attributes(&mut t, index, chunk, attrs);
        } else {
            self.text.insert(&mut t, index, chunk);
        }
        Ok(())
    }

    #[pyo3(signature = (txn, index, embed, attrs=None))]
    fn insert_embed(&self, txn: &mut Transaction, index: u32, embed: Bound<'_, PyAny>, attrs: Option<Bound<'_, PyIterator>>) -> PyResult<()> {
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

    fn format(&self, txn: &mut Transaction, index: u32, len: u32, attrs: Bound<'_, PyIterator>) -> PyResult<()> {
        let mut _t = txn.transaction();
        let mut t = _t.as_mut().unwrap().as_mut();
        let attrs = py_to_attrs(attrs)?;
        self.text.format(&mut t, index, len, attrs);
        Ok(())
    }

    fn remove_range(&self, txn: &mut Transaction, index: u32, len: u32) -> PyResult<()> {
        let mut _t = txn.transaction();
        let mut t = _t.as_mut().unwrap().as_mut();
        self.text.remove_range(&mut t, index, len);
        Ok(())
    }

    fn get_string<'py>(&mut self, py: Python<'py>, txn: &mut Transaction) -> Bound<'py, PyString> {
        let mut t0 = txn.transaction();
        let t1 = t0.as_mut().unwrap();
        let t = t1.as_ref();
        let s = self.text.get_string(t);
        PyString::new(py, &s)
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

        PyList::new(py, iter).unwrap()
    }

    fn sticky_index<'py>(&self, py: Python<'py>, txn: &mut Transaction, index: u32, assoc: i8) -> PyResult<Py<StickyIndex>> {
        let mut _t = txn.transaction();
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

    fn observe(&mut self, py: Python<'_>, f: PyObject) -> PyResult<Py<Subscription>> {
        let sub = self.text.observe(move |txn, e| {
            Python::with_gil(|py| {
                let e = TextEvent::new(e, txn);
                if let Err(err) = f.call1(py, (e,)) {
                    err.restore(py)
                }
            });
        });
        let s: Py<Subscription> = Py::new(py, Subscription::from(sub))?;
        Ok(s)
    }

    pub fn observe_deep(&mut self, py: Python<'_>, f: PyObject) -> PyResult<Py<Subscription>> {
        self.observe(py, f)
    }
}

#[pyclass(unsendable)]
pub struct TextEvent {
    event: *const _TextEvent,
    txn: *const TransactionMut<'static>,
    target: Option<PyObject>,
    delta: Option<PyObject>,
    path: Option<PyObject>,
    transaction: Option<PyObject>,
}

impl TextEvent {
    pub fn new(event: &_TextEvent, txn: &TransactionMut) -> Self {
        let event = event as *const _TextEvent;
        let txn = unsafe { std::mem::transmute::<&TransactionMut, &TransactionMut<'static>>(txn) };
        let text_event = TextEvent {
            event,
            txn,
            target: None,
            delta: None,
            path: None,
            transaction: None,
        };
        text_event
    }

    fn event(&self) -> &_TextEvent {
        unsafe { self.event.as_ref().unwrap() }
    }

    fn txn(&self) -> &TransactionMut {
        unsafe { self.txn.as_ref().unwrap() }
    }
}

#[pymethods]
impl TextEvent {
    #[getter]
    pub fn transaction<'py>(&mut self, py: Python<'py>) -> Bound<'py, PyAny> {
        if let Some(transaction) = &self.transaction {
            transaction.clone_ref(py).into_bound(py)
        } else {
            let transaction = Transaction::from(self.txn()).into_bound_py_any(py).unwrap();
            self.transaction = Some(transaction.clone().unbind());
            transaction
        }
    }

    #[getter]
    pub fn target<'py>(&mut self, py: Python<'py>) -> Bound<'py, PyAny> {
        if let Some(target) = &self.target {
            target.clone_ref(py).into_bound(py)
        } else {
            let target = Text::from(self.event().target().clone()).into_bound_py_any(py).unwrap();
            self.target = Some(target.clone().unbind());
            target
        }
    }

    #[getter]
    pub fn path<'py>(&mut self, py: Python<'py>) -> Bound<'py, PyAny> {
        if let Some(path) = &self.path {
            path.clone_ref(py).into_bound(py)
        } else {
            let path = self.event().path().into_py(py);
            self.path = Some(path.clone().unbind());
            path
        }
    }

    #[getter]
    pub fn delta<'py>(&mut self, py: Python<'py>) -> Bound<'py, PyAny> {
        if let Some(delta) = &self.delta {
            delta.clone_ref(py).into_bound(py)
        } else {
            let delta = {
                let delta =
                    self.event()
                        .delta(self.txn())
                        .into_iter()
                        .map(|d| d.clone().into_py(py));
                delta
            };
            let delta = PyList::new(py, delta).unwrap().into_bound_py_any(py).unwrap();
            self.delta = Some(delta.clone().unbind());
            delta
        }
    }

    fn __repr__(&mut self, py: Python<'_>) -> String {
        let target = self.target(py);
        let delta = self.delta(py);
        let path = self.path(py);
        format!("TextEvent(target={target}, delta={delta}, path={path})")
    }
}
