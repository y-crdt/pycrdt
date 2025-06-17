use pyo3::prelude::*;
use pyo3::IntoPyObjectExt;
use pyo3::exceptions::{PyValueError, PyTypeError};
use pyo3::types::{PyList, PyString};
use yrs::{
    Any,
    Array as _Array,
    ArrayRef,
    Assoc,
    DeepObservable,
    Doc as _Doc,
    IndexedSequence,
    Observable,
    TransactionMut,
    XmlFragmentPrelim,
};
use yrs::types::ToJson;
use yrs::types::text::TextPrelim;
use yrs::types::array::{ArrayPrelim, ArrayEvent as _ArrayEvent};
use yrs::types::map::MapPrelim;
use crate::transaction::Transaction;
use crate::subscription::Subscription;
use crate::type_conversions::{events_into_py, py_to_any, ToPython};
use crate::text::Text;
use crate::map::Map;
use crate::doc::Doc;
use crate::xml::XmlFragment;
use crate::sticky_index::StickyIndex;


#[pyclass]
pub struct Array {
    pub array: ArrayRef,
}

impl Array {
    pub fn from(array: ArrayRef) -> Self {
        Array { array }
    }
}

#[pymethods]
impl Array {
    fn len(&self, txn: &mut Transaction)  -> PyResult<u32> {
        let mut t0 = txn.transaction();
        let t1 = t0.as_mut().unwrap();
        let t = t1.as_ref();
        let len = self.array.len(t);
        Ok(len)
    }

    fn insert(&self, txn: &mut Transaction, index: u32, value: &Bound<'_, PyAny>) -> PyResult<()> {
        let mut _t = txn.transaction();
        let mut t = _t.as_mut().unwrap().as_mut();
        match py_to_any(value) {
            Any::Undefined => Err(PyTypeError::new_err("Type not supported")),
            v => {
                self.array.insert(&mut t, index, v);
                Ok(())
            },
        }
    }

    fn insert_text_prelim(&self, txn: &mut Transaction, index: u32) -> PyResult<Text> {
        let mut _t = txn.transaction();
        let mut t = _t.as_mut().unwrap().as_mut();
        let integrated = self.array.insert(&mut t, index, TextPrelim::new(""));
        let shared = Text::from(integrated);
        Ok(shared)
    }

    fn insert_array_prelim(&self, txn: &mut Transaction, index: u32) -> PyResult<Array> {
        let mut _t = txn.transaction();
        let mut t = _t.as_mut().unwrap().as_mut();
        let integrated = self.array.insert(&mut t, index, ArrayPrelim::default());
        let shared = Array::from(integrated);
        Ok(shared)
    }

    fn insert_map_prelim(&self, txn: &mut Transaction, index: u32) -> PyResult<Map> {
        let mut _t = txn.transaction();
        let mut t = _t.as_mut().unwrap().as_mut();
        let integrated = self.array.insert(&mut t, index, MapPrelim::default());
        let shared = Map::from(integrated);
        Ok(shared)
    }

    fn insert_xmlfragment_prelim(&self, txn: &mut Transaction, index: u32) -> PyResult<XmlFragment> {
        let mut _t = txn.transaction();
        let mut t = _t.as_mut().unwrap().as_mut();
        let integrated = self.array.insert(&mut t, index, XmlFragmentPrelim::default());
        let shared = XmlFragment::from(integrated);
        Ok(shared)
    }

    fn insert_xmlelement_prelim(&self, _txn: &mut Transaction, _index: u32) -> PyResult<PyObject> {
        Err(PyTypeError::new_err("Cannot insert an XmlElement into an array - insert it into an XmlFragment and insert that into the array"))
    }

    fn insert_xmltext_prelim(&self, _txn: &mut Transaction, _index: u32) -> PyResult<PyObject> {
        Err(PyTypeError::new_err("Cannot insert an XmlText into an array - insert it into an XmlFragment and insert that into the array"))
    }

    fn insert_doc(&self, txn: &mut Transaction, index: u32, doc: &Bound<'_, PyAny>) -> PyResult<()> {
        let mut _t = txn.transaction();
        let mut t = _t.as_mut().unwrap().as_mut();
        let d1: Doc = doc.extract().unwrap();
        let d2: _Doc = d1.doc;
        let doc_ref = self.array.insert(&mut t, index, d2);
        doc_ref.load(t);
        Ok(())
    }

    fn move_to(&self, txn: &mut Transaction, source: u32, target: u32) -> PyResult<()> {
        let mut _t = txn.transaction();
        let mut t = _t.as_mut().unwrap().as_mut();
        self.array.move_to(&mut t, source, target);
        Ok(())
    }

    fn remove_range(&self, txn: &mut Transaction, index: u32, len: u32) -> PyResult<()> {
        let mut _t = txn.transaction();
        let mut t = _t.as_mut().unwrap().as_mut();
        self.array.remove_range(&mut t, index, len);
        Ok(())
    }

    fn get<'py>(&self, py: Python<'py>, txn: &mut Transaction, index: u32) -> PyResult<Bound<'py, PyAny>> {
        let mut t0 = txn.transaction();
        let t1 = t0.as_mut().unwrap();
        let t = t1.as_ref();
        let v = self.array.get(t, index);
        if v == None {
            Err(PyValueError::new_err("Index error"))
        } else {
            Ok(v.unwrap().into_py(py))
        }
    }

    fn to_json<'py>(&mut self, py: Python<'py>, txn: &mut Transaction) -> Bound<'py, PyString> {
        let mut t0 = txn.transaction();
        let t1 = t0.as_mut().unwrap();
        let t = t1.as_ref();
        let mut s = String::new();
        self.array.to_json(t).to_json(&mut s);
        PyString::new(py, s.as_str())
    }

    fn sticky_index<'py>(&self, py: Python<'py>, txn: &mut Transaction, index: u32, assoc: i8) -> PyResult<Py<StickyIndex>> {
        let mut _t = txn.transaction();
        let t = _t.as_mut().unwrap().as_mut();
        let _assoc: Assoc;
        match assoc {
            0 => _assoc = Assoc::After,
            _ => _assoc = Assoc::Before,
        }
        let sticky_index = self.array.sticky_index(t, index, _assoc);
        let s: Py<StickyIndex> = Py::new(py, StickyIndex::from(sticky_index))?;
        Ok(s)
    }

    pub fn observe(&mut self, py: Python<'_>, f: PyObject) -> PyResult<Py<Subscription>> {
        let sub = self.array
            .observe(move |txn, e| {
                Python::with_gil(|py| {
                    let event = ArrayEvent::new(e, txn);
                    if let Err(err) = f.call1(py, (event,)) {
                        err.restore(py)
                    }
                })
            });
        let s: Py<Subscription> = Py::new(py, Subscription::from(sub))?;
        Ok(s)
    }

    pub fn observe_deep(&mut self, py: Python<'_>, f: PyObject) -> PyResult<Py<Subscription>> {
        let sub = self.array
            .observe_deep(move |txn, events| {
                Python::with_gil(|py| {
                    let events = events_into_py(py, txn, events);
                    if let Err(err) = f.call1(py, (events,)) {
                        err.restore(py)
                    }
                })
            });
        let s: Py<Subscription> = Py::new(py, Subscription::from(sub))?;
        Ok(s)
    }
}

#[pyclass(unsendable)]
pub struct ArrayEvent {
    event: *const _ArrayEvent,
    txn: *const TransactionMut<'static>,
    target: Option<PyObject>,
    delta: Option<PyObject>,
    path: Option<PyObject>,
    transaction: Option<PyObject>,
}

impl ArrayEvent {
    pub fn new(event: &_ArrayEvent, txn: &TransactionMut) -> Self {
        let event = event as *const _ArrayEvent;
        let txn = unsafe { std::mem::transmute::<&TransactionMut, &TransactionMut<'static>>(txn) };
        let array_event = ArrayEvent {
            event,
            txn,
            target: None,
            delta: None,
            path: None,
            transaction: None,
        };
        array_event
    }

    fn event(&self) -> &_ArrayEvent {
        unsafe { self.event.as_ref().unwrap() }
    }

    fn txn(&self) -> &TransactionMut {
        unsafe { self.txn.as_ref().unwrap() }
    }
}

#[pymethods]
impl ArrayEvent {
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
            let target = Array::from(self.event().target().clone()).into_bound_py_any(py).unwrap();
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
        format!("ArrayEvent(target={target}, delta={delta}, path={path})")
    }
}
