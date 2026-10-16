use crate::thread_affinity::{CallbackPtr, CallbackRef, CallbackScope, CallbackLifetime, ThreadAffinity};
use pyo3::prelude::*;
use pyo3::IntoPyObjectExt;
use pyo3::exceptions::{PyValueError, PyTypeError};
use pyo3::types::{PyString, PyDict, PyList};
use yrs::{
    Any, DeepObservable, Doc as _Doc, Map as _Map, MapRef, Observable, TransactionMut, XmlFragmentPrelim
};
use yrs::types::ToJson;
use yrs::types::text::TextPrelim;
use yrs::types::array::ArrayPrelim;
use yrs::types::map::{MapPrelim, MapEvent as _MapEvent};
use crate::transaction::Transaction;
use crate::subscription::Subscription;
use crate::type_conversions::{EntryChangeWrapper, events_into_py, py_to_any, ToPython};
use crate::text::Text;
use crate::array::Array;
use crate::doc::Doc;
use crate::xml::XmlFragment;


#[pyclass]
pub struct Map {
    pub map: MapRef,
}

impl Map {
    pub fn from(map: MapRef) -> Self {
        Map { map }
    }
}

#[pymethods]
impl Map {
    fn len(&self, txn: &mut Transaction) -> PyResult<u32> {
        let mut t0 = txn.transaction()?;
        let t1 = t0.as_mut().unwrap();
        let t = t1.as_ref();
        let len = self.map.len(t);
        Ok(len)
    }

    fn insert(&self, txn: &mut Transaction, key: &str, value: &Bound<'_, PyAny>) -> PyResult<()> {
        let mut _t = txn.transaction()?;
        let mut t = _t.as_mut().unwrap().as_mut();
        match py_to_any(value) {
            Any::Undefined => Err(PyTypeError::new_err("Type not supported")),
            v => {
                self.map.insert(&mut t, key, v);
                Ok(())
            }
        }
    }

    fn insert_text_prelim(&self, txn: &mut Transaction, key: &str) -> PyResult<Text> {
        let mut _t = txn.transaction()?;
        let mut t = _t.as_mut().unwrap().as_mut();
        let integrated = self.map.insert(&mut t, key, TextPrelim::new(""));
        let shared = Text::from(integrated);
        Ok(shared)
    }

    fn insert_array_prelim(&self, txn: &mut Transaction, key: &str) -> PyResult<Array> {
        let mut _t = txn.transaction()?;
        let mut t = _t.as_mut().unwrap().as_mut();
        let integrated = self.map.insert(&mut t, key, ArrayPrelim::default());
        let shared = Array::from(integrated);
        Ok(shared)
    }

    fn insert_map_prelim(&self, txn: &mut Transaction, key: &str) -> PyResult<Map> {
        let mut _t = txn.transaction()?;
        let mut t = _t.as_mut().unwrap().as_mut();
        let integrated = self.map.insert(&mut t, key, MapPrelim::default());
        let shared = Map::from(integrated);
        Ok(shared)
    }

    fn insert_xmlfragment_prelim(&self, txn: &mut Transaction, key: &str) -> PyResult<XmlFragment> {
        let mut _t = txn.transaction()?;
        let mut t = _t.as_mut().unwrap().as_mut();
        let integrated = self.map.insert(&mut t, key, XmlFragmentPrelim::default());
        let shared = XmlFragment::from(integrated);
        Ok(shared)
    }

    fn insert_xmlelement_prelim(&self, _txn: &mut Transaction, _key: &str) -> PyResult<Py<PyAny>> {
        Err(PyTypeError::new_err("Cannot insert an XmlElement into a map - insert it into an XmlFragment and insert that into the map"))
    }

    fn insert_xmltext_prelim(&self, _txn: &mut Transaction, _key: &str) -> PyResult<Py<PyAny>> {
        Err(PyTypeError::new_err("Cannot insert an XmlText into a map - insert it into an XmlFragment and insert that into the map"))
    }

    fn insert_doc(&self, txn: &mut Transaction, key: &str, doc: &Bound<'_, PyAny>) -> PyResult<()> {
        let mut _t = txn.transaction()?;
        let mut t = _t.as_mut().unwrap().as_mut();
        let d1: Doc = doc
            .extract()
            .map_err(|_| PyTypeError::new_err("Expected Doc object"))?;
        let d2: _Doc = d1.doc;
        let doc_ref = self.map.insert(&mut t, key, d2);
        doc_ref.load(t);
        Ok(())
    }

    fn remove(&self, txn: &mut Transaction, key: &str) -> PyResult<()> {
        let mut _t = txn.transaction()?;
        let mut t = _t.as_mut().unwrap().as_mut();
        self.map.remove(&mut t, key);
        Ok(())
    }

    fn get<'py>(
        &self,
        py: Python<'py>,
        txn: &mut Transaction,
        key: &str,
    ) -> PyResult<Bound<'py, PyAny>> {
        let mut t0 = txn.transaction()?;
        let t1 = t0.as_mut().unwrap();
        let t = t1.as_ref();
        let v = self.map.get(t, key);
        if v == None {
            Err(PyValueError::new_err("Key error"))
        } else {
            Ok(v.unwrap().into_py(py))
        }
    }

    fn keys<'py>(&self, py: Python<'py>, txn: &mut Transaction) -> PyResult<Bound<'py, PyList>> {
        let mut t0 = txn.transaction()?;
        let t1 = t0.as_mut().unwrap();
        let t = t1.as_ref();
        let it = self.map.keys(t);
        let mut v: Vec<String> = Vec::new();
        for k in it {
            v.push(k.into());
        }
        Ok(PyList::new(py, v).unwrap())
    }

    fn to_json(&mut self, txn: &mut Transaction) -> PyResult<Py<PyAny>> {
        let mut t0 = txn.transaction()?;
        let t1 = t0.as_mut().unwrap();
        let t = t1.as_ref();
        let mut s = String::new();
        self.map.to_json(t).to_json(&mut s);
        Ok(Python::attach(|py| PyString::new(py, s.as_str()).into()))
    }

    /// Returns true if the given key exists in the map.
    fn has(&self, txn: &mut Transaction, key: &str) -> PyResult<bool> {
        let mut t0 = txn.transaction()?;
        let t1 = t0.as_mut().unwrap();
        let t = t1.as_ref();
        Ok(self.map.get(t, key).is_some())
    }

    pub fn observe(&mut self, py: Python<'_>, f: Py<PyAny>) -> PyResult<Py<Subscription>> {
        let target = self.map.clone();
        let (sub, callback) = Subscription::new(f, move |key| {
            let _ = target.unobserve(key);
        });
        self.map.observe(callback.key, move |txn, e| {
            Python::attach(|py| {
                let Some(f) = callback.get(py) else {
                    return;
                };
                let scope = CallbackScope::new();
                let e = MapEvent::new(e, txn, scope.lifetime());
                if let Err(err) = f.call1(py, (e,)) {
                    err.restore(py)
                }
            })
        });
        let s: Py<Subscription> = Py::new(py, sub)?;
        Ok(s)
    }

    pub fn observe_deep<'py>(
        &mut self,
        py: Python<'py>,
        f: Py<PyAny>,
    ) -> PyResult<Py<Subscription>> {
        let target = self.map.clone();
        let (sub, callback) = Subscription::new(f, move |key| {
            let _ = target.unobserve_deep(key);
        });
        self.map.observe_deep(callback.key, move |txn, events| {
            Python::attach(|py| {
                let Some(f) = callback.get(py) else {
                    return;
                };
                let scope = CallbackScope::new();
                let events = events_into_py(py, txn, events, scope.lifetime());
                if let Err(err) = f.call1(py, (events,)) {
                    err.restore(py)
                }
            })
        });
        let s: Py<Subscription> = Py::new(py, sub)?;
        Ok(s)
    }
}

#[pyclass]
pub struct MapEvent {
    event: CallbackPtr<_MapEvent>,
    txn: CallbackPtr<TransactionMut<'static>>,
    thread: ThreadAffinity,
    target: Option<Py<PyAny>>,
    keys: Option<Py<PyAny>>,
    path: Option<Py<PyAny>>,
    transaction: Option<Py<PyAny>>,
}

impl MapEvent {
    pub fn new(event: &_MapEvent, txn: &TransactionMut, lifetime: CallbackLifetime) -> Self {
        let event = event as *const _MapEvent;
        let txn = unsafe { std::mem::transmute::<&TransactionMut, &TransactionMut<'static>>(txn) };
        let map_event = MapEvent {
            event: unsafe { CallbackPtr::new(event, lifetime.clone()) },
            txn: unsafe { CallbackPtr::new(txn, lifetime) },
            thread: ThreadAffinity::new(),
            target: None,
            keys: None,
            path: None,
            transaction: None,
        };
        map_event
    }

    fn event(&self) -> PyResult<CallbackRef<'_, _MapEvent>> {
        self.event.borrow()
    }

    fn txn(&self) -> PyResult<CallbackRef<'_, TransactionMut<'static>>> {
        self.txn.borrow()
    }
}

#[pymethods]
impl MapEvent {
    #[getter]
    pub fn transaction<'py>(&mut self, py: Python<'py>) -> PyResult<Bound<'py, PyAny>> {
        self.thread.check();
        let _lease = self.txn.borrow()?;
        if let Some(transaction) = &self.transaction {
            Ok(transaction.clone_ref(py).into_bound(py))
        } else {
            let transaction = Transaction::borrowed(self.txn.clone()).into_bound_py_any(py)?;
            self.transaction = Some(transaction.clone().unbind());
            Ok(transaction)
        }
    }

    #[getter]
    pub fn target<'py>(&mut self, py: Python<'py>) -> PyResult<Bound<'py, PyAny>> {
        self.thread.check();
        if let Some(target) = &self.target {
            Ok(target.clone_ref(py).into_bound(py))
        } else {
            let target = Map::from(self.event()?.target().clone()).into_bound_py_any(py)?;
            self.target = Some(target.clone().unbind());
            Ok(target)
        }
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
    pub fn keys<'py>(&mut self, py: Python<'py>) -> PyResult<Bound<'py, PyAny>> {
        self.thread.check();
        if let Some(keys) = &self.keys {
            Ok(keys.clone_ref(py).into_bound(py))
        } else {
            let keys = {
                let event = self.event()?;
                let txn = self.txn()?;
                let keys = event.keys(&*txn);
                let result = PyDict::new(py);
                for (key, value) in keys.iter() {
                    let key = &**key;
                    let value = EntryChangeWrapper(value);
                    result.set_item(key, value.into_pyobject(py)?)?;
                }
                result
            };
            let keys = keys.into_bound_py_any(py)?;
            self.keys = Some(keys.clone().unbind());
            Ok(keys)
        }
    }

    fn __repr__(&mut self, py: Python<'_>) -> PyResult<String> {
        self.thread.check();
        let target = self.target(py)?;
        let keys = self.keys(py)?;
        let path = self.path(py)?;
        Ok(format!("MapEvent(target={target}, keys={keys}, path={path})"))
    }
}
