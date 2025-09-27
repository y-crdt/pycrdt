use pyo3::prelude::*;
use pyo3::IntoPyObjectExt;
use pyo3::exceptions::{PyRuntimeError, PyValueError};
use pyo3::types::{PyBool, PyBytes, PyDict, PyInt, PyList};
use yrs::{
    Doc as _Doc, Options, ReadTxn, StateVector, SubdocsEvent as _SubdocsEvent, Transact, TransactionCleanupEvent, TransactionMut, Update, WriteTxn
};
use yrs::updates::encoder::{Encode, Encoder};
use yrs::updates::decoder::Decode;
use crate::text::Text;
use crate::array::Array;
use crate::map::Map;
use crate::transaction::Transaction;
use crate::subscription::Subscription;
use crate::type_conversions::ToPython;
use crate::xml::XmlFragment;


#[pyclass]
#[derive(Clone)]
pub struct Doc {
    pub doc: _Doc,
}

impl Doc {
    pub fn from(doc: _Doc) -> Self {
        Doc { doc }
    }
    /// Internal: create a new Doc from a Snapshot and an original Doc
    pub fn _from_snapshot_impl(original: &Self, snapshot: &crate::snapshot::Snapshot) -> Self {
        // Create a new Doc with the same options as the original
        let mut options = yrs::Options::default();
        options.client_id = original.doc.client_id();
        options.skip_gc = original.doc.skip_gc();
        if let Some(collection_id) = original.doc.collection_id() {
            options.collection_id = Some(collection_id);
        }
        options.guid = original.doc.guid();
        let new_doc = yrs::Doc::with_options(options);
        // Encode the update from the snapshot
        let mut encoder = yrs::updates::encoder::EncoderV1::new();
        {
            let txn = original.doc.transact();
            txn.encode_state_from_snapshot(&snapshot.snapshot, &mut encoder).unwrap();
        }
        let update = yrs::Update::decode_v1(&encoder.to_vec()).unwrap();
        {
            let mut txn = new_doc.transact_mut();
            txn.apply_update(update).unwrap();
        }
        // Ensure root types are present in the restored doc (recreate them if needed)
        // Copy root type names and types from the original doc
        let txn_orig = original.doc.transact();
        for (name, root) in txn_orig.root_refs() {
            match root {
                yrs::Out::YText(_) => { let _ = new_doc.get_or_insert_text(name); },
                yrs::Out::YArray(_) => { let _ = new_doc.get_or_insert_array(name); },
                yrs::Out::YMap(_) => { let _ = new_doc.get_or_insert_map(name); },
                yrs::Out::YXmlFragment(_) => { let _ = new_doc.get_or_insert_xml_fragment(name); },
                _ => {}, // ignore unknown types
            }
        }
        drop(txn_orig);
        Doc { doc: new_doc }
    }
}

#[pymethods]
impl Doc {
    #[new]
    fn new(client_id: &Bound<'_, PyAny>, skip_gc: &Bound<'_, PyAny>) -> Self {
        let mut options = Options::default();
        if !client_id.is_none() {
            let _client_id: u64 = client_id.downcast::<PyInt>().unwrap().extract().unwrap();
            options.client_id = _client_id;
        }
        if !skip_gc.is_none() {
            let _skip_gc: bool = skip_gc.downcast::<PyBool>().unwrap().extract().unwrap();
            options.skip_gc = _skip_gc;
        }
        let doc = _Doc::with_options(options);
        Doc { doc }
    }

    #[staticmethod]
    #[pyo3(name = "from_snapshot")]
    pub fn from_snapshot(py: Python<'_>, snapshot: PyRef<'_, crate::snapshot::Snapshot>, doc: PyRef<'_, Doc>) -> PyResult<Py<Doc>> {
        let restored = Doc::_from_snapshot_impl(&doc, &snapshot);
        Py::new(py, restored)
    }

    fn guid(&mut self) -> String {
        self.doc.guid().to_string()
    }

    fn client_id(&mut self) -> u64 {
        self.doc.client_id()
    }

    fn get_or_insert_text(&mut self, py: Python<'_>, txn: &mut Transaction, name: &str) -> PyResult<Py<Text>> {
        let mut _t = txn.transaction();
        let t = _t.as_mut().unwrap().as_mut();
        let text = t.get_or_insert_text(name);
        let pytext: Py<Text> = Py::new(py, Text::from(text))?;
        Ok(pytext)
    }

    fn get_or_insert_array(&mut self, py: Python<'_>, txn: &mut Transaction, name: &str) -> PyResult<Py<Array>> {
        let mut _t = txn.transaction();
        let t = _t.as_mut().unwrap().as_mut();
        let shared = t.get_or_insert_array(name);
        let pyshared: Py<Array > = Py::new(py, Array::from(shared))?;
        Ok(pyshared)
    }

    fn get_or_insert_map(&mut self, py: Python<'_>, txn: &mut Transaction, name: &str) -> PyResult<Py<Map>> {
        let mut _t = txn.transaction();
        let t = _t.as_mut().unwrap().as_mut();
        let shared = t.get_or_insert_map(name);
        let pyshared: Py<Map> = Py::new(py, Map::from(shared))?;
        Ok(pyshared)
    }

    fn get_or_insert_xml_fragment(&mut self, txn: &mut Transaction, name: &str) -> XmlFragment {
        let mut _t = txn.transaction();
        let t = _t.as_mut().unwrap().as_mut();
        t.get_or_insert_xml_fragment(name).into()
    }

    fn create_transaction(&self, py: Python<'_>) -> PyResult<Py<Transaction>> {
        if let Ok(txn) = self.doc.try_transact_mut() {
            let t: Py<Transaction> = Py::new(py, Transaction::from(txn))?;
            return Ok(t);
        }
        Err(PyRuntimeError::new_err("Already in a transaction"))
    }

    fn create_transaction_with_origin(&self, py: Python<'_>, origin: i128) -> PyResult<Py<Transaction>> {
        if let Ok(txn) = self.doc.try_transact_mut_with(origin) {
            let t: Py<Transaction> = Py::new(py, Transaction::from(txn))?;
            return Ok(t);
        }
        Err(PyRuntimeError::new_err("Already in a transaction"))
    }

    fn get_state(&self, txn: &Transaction) -> Py<PyAny> {
        let mut _t = txn.transaction();
        let t = _t.as_mut().unwrap().as_mut();
        let state = t.state_vector().encode_v1();
        Python::attach(|py| PyBytes::new(py, &state).into())
    }

    fn get_update(&self, txn: &Transaction, state: &Bound<'_, PyBytes>) -> PyResult<Py<PyAny>> {
        let mut _t = txn.transaction();
        let t = _t.as_mut().unwrap().as_mut();
        let state: &[u8] = state.extract()?;
        let Ok(state_vector) = StateVector::decode_v1(&state) else { return Err(PyValueError::new_err("Cannot decode state")) };
        let update = t.encode_diff_v1(&state_vector);
        let bytes: Py<PyAny> = Python::attach(|py| PyBytes::new(py, &update).into());
        Ok(bytes)
    }

    fn apply_update(&mut self, txn: &mut Transaction, update: &Bound<'_, PyBytes>) -> PyResult<()> {
        let u = Update::decode_v1(update.as_bytes()).unwrap();
        let mut _t = txn.transaction();
        let t = _t.as_mut().unwrap().as_mut();
        t.apply_update(u)
            .map_err(|e| PyRuntimeError::new_err(format!("Cannot apply update: {}", e)))
    }

    fn roots(&self, py: Python<'_>, txn: &mut Transaction) -> Py<PyAny> {
        let mut t0 = txn.transaction();
        let t1 = t0.as_mut().unwrap();
        let t = t1.as_ref();
        let result = PyDict::new(py);
        for (k, v) in t.root_refs() {
            result.set_item(k, v.into_py(py)).unwrap();
        }
        result.into()
    }

    pub fn observe(&mut self, py: Python<'_>, f: Py<PyAny>) -> PyResult<Py<Subscription>> {
        let sub = self.doc
            .observe_transaction_cleanup(move |txn, event| {
                if !event.delete_set.is_empty() || event.before_state != event.after_state {
                    Python::attach(|py| {
                        let event = TransactionEvent::new(py, event, txn);
                        if let Err(err) = f.call1(py, (event,)) {
                            err.restore(py)
                        }
                    })
                }
            })
            .unwrap();
        let s: Py<Subscription> = Py::new(py, Subscription::from(sub))?;
        Ok(s)
    }

    pub fn observe_subdocs(&mut self, py: Python<'_>, f: Py<PyAny>) -> PyResult<Py<Subscription>> {
        let sub = self.doc
            .observe_subdocs(move |_, event| {
                Python::attach(|py| {
                    let event = SubdocsEvent::new(py, event);
                    if let Err(err) = f.call1(py, (event,)) {
                        err.restore(py)
                    }
                })
            })
            .unwrap();
        let s: Py<Subscription> = Py::new(py, Subscription::from(sub))?;
        Ok(s)
    }
}

#[pyclass(unsendable)]
pub struct TransactionEvent {
    event: *const TransactionCleanupEvent,
    txn: *const TransactionMut<'static>,
    before_state: Option<Py<PyBytes>>,
    after_state: Option<Py<PyBytes>>,
    delete_set: Option<Py<PyBytes>>,
    update: Option<Py<PyBytes>>,
    transaction: Option<Py<PyAny>>,
}

impl TransactionEvent {
    fn new(py: Python<'_>, event: &TransactionCleanupEvent, txn: &TransactionMut) -> Self {
        let event = event as *const TransactionCleanupEvent;
        let txn = unsafe { std::mem::transmute::<&TransactionMut, &TransactionMut<'static>>(txn) };
        let mut transaction_event = TransactionEvent {
            event,
            txn,
            before_state: None,
            after_state: None,
            delete_set: None,
            update: None,
            transaction: None,
        };
        transaction_event.update(py);
        transaction_event
    }

    fn event(&self) -> &TransactionCleanupEvent {
        unsafe { self.event.as_ref().unwrap() }
    }
    fn txn(&self) -> &TransactionMut<'_> {
        unsafe { self.txn.as_ref().unwrap() }
    }
}

#[pymethods]
impl TransactionEvent {
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
    pub fn before_state<'py>(&mut self, py: Python<'py>) -> Bound<'py, PyBytes> {
        if let Some(before_state) = &self.before_state {
            before_state.clone_ref(py).into_bound(py)
        } else {
            let before_state = self.event().before_state.encode_v1();
            let before_state = PyBytes::new(py, &before_state);
            self.before_state = Some(before_state.clone().unbind());
            before_state
        }
    }

    #[getter]
    pub fn after_state<'py>(&mut self, py: Python<'py>) -> Bound<'py, PyBytes> {
        if let Some(after_state) = &self.after_state {
            after_state.clone_ref(py).into_bound(py)
        } else {
            let after_state = self.event().after_state.encode_v1();
            let after_state = PyBytes::new(py, &after_state);
            self.after_state = Some(after_state.clone().unbind());
            after_state
        }
    }

    #[getter]
    pub fn delete_set<'py>(&mut self, py: Python<'py>) -> Bound<'py, PyBytes> {
        if let Some(delete_set) = &self.delete_set {
            delete_set.clone_ref(py).into_bound(py)
        } else {
            let delete_set = self.event().delete_set.encode_v1();
            let delete_set = PyBytes::new(py, &delete_set);
            self.delete_set = Some(delete_set.clone().unbind());
            delete_set
        }
    }

    #[getter]
    pub fn update<'py>(&mut self, py: Python<'py>) -> Bound<'py, PyBytes> {
        if let Some(update) = &self.update {
            update.clone_ref(py).into_bound(py)
        } else {
            let update = self.txn().encode_update_v1();
            let update = PyBytes::new(py, &update);
            self.update = Some(update.clone().unbind());
            update
        }
    }
}

#[pyclass(unsendable)]
pub struct SubdocsEvent {
    added: Py<PyAny>,
    removed: Py<PyAny>,
    loaded: Py<PyAny>,
}

impl SubdocsEvent {
    fn new<'py>(py: Python<'py>, event: &_SubdocsEvent) -> Self {
        let added: Vec<String> = event.added().map(|d| d.guid().clone().to_string()).collect();
        let added = PyList::new(py, added).unwrap().into_py_any(py).unwrap();
        let removed: Vec<String> = event.removed().map(|d| d.guid().clone().to_string()).collect();
        let removed = PyList::new(py, removed).unwrap().into_py_any(py).unwrap();
        let loaded: Vec<String> = event.loaded().map(|d| d.guid().clone().to_string()).collect();
        let loaded = PyList::new(py, loaded).unwrap().into_py_any(py).unwrap();
        SubdocsEvent {
            added,
            removed,
            loaded,
        }
    }
}

#[pymethods]
impl SubdocsEvent {
    #[getter]
    pub fn added(&mut self, py: Python<'_>) -> Py<PyAny> {
        self.added.clone_ref(py)
    }

    #[getter]
    pub fn removed(&mut self, py: Python<'_>) -> Py<PyAny> {
        self.removed.clone_ref(py)
    }

    #[getter]
    pub fn loaded(&mut self, py: Python<'_>) -> Py<PyAny> {
        self.loaded.clone_ref(py)
    }
}
