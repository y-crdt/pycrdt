use std::collections::HashSet;
use std::sync::Arc;
use pyo3::prelude::*;
use pyo3::types::{PyList, PyBytes, PyString};
use pyo3::exceptions::PyRuntimeError;
use yrs::{
    UndoManager as _UndoManager,
    DeleteSet as _DeleteSet,
};
use yrs::undo::{
    Options,
    StackItem as _StackItem,
};
use yrs::sync::{Clock, Timestamp};
use yrs::updates::encoder::Encode;
use yrs::updates::decoder::Decode;
use crate::doc::Doc;
use crate::text::Text;
use crate::array::Array;
use crate::map::Map;
use crate::xml::XmlFragment;

#[pyclass]
#[derive(Clone)]
pub struct DeleteSet {
    delete_set: _DeleteSet,
}

#[pymethods]
impl DeleteSet {
    /// Create a new empty DeleteSet
    #[new]
    pub fn new() -> Self {
        DeleteSet {
            delete_set: _DeleteSet::new(),
        }
    }

    /// Encode the DeleteSet to bytes
    pub fn encode(&self) -> Py<PyAny> {
        let encoded = self.delete_set.encode_v1();
        Python::attach(|py: Python<'_>| PyBytes::new(py, &encoded).into())
    }

    /// Serialize the DeleteSet to a JSON string
    pub fn to_json_string(&self) -> Py<PyAny> {
        use std::collections::HashMap;
        let mut mapping: HashMap<u64, Vec<(u32, u32)>> = HashMap::new();
        for (client, ranges) in self.delete_set.iter() {
            let mut vec_ranges = Vec::new();
            for range in ranges.iter() {
                vec_ranges.push((range.start, range.end));
            }
            mapping.insert(*client, vec_ranges);
        }
        let encoded = serde_json::to_string(&mapping).unwrap();
        Python::attach(|py| PyString::new(py, &encoded).into())
    }

    /// Decode a DeleteSet from bytes
    #[staticmethod]
    pub fn decode(data: &Bound<'_, PyBytes>) -> PyResult<Self> {
        let bytes: &[u8] = data.as_bytes();
        match _DeleteSet::decode_v1(bytes) {
            Ok(delete_set) => Ok(DeleteSet { delete_set }),
            Err(e) => Err(pyo3::exceptions::PyValueError::new_err(format!(
                "Failed to decode DeleteSet: {}",
                e
            ))),
        }
    }

    fn __repr__(&self) -> String {
        format!("{:?}", self.delete_set)
    }
}

impl DeleteSet {
    pub fn from(delete_set: _DeleteSet) -> Self {
        DeleteSet { delete_set }
    }
}

struct PythonClock {
    timestamp: Py<PyAny>,
}

impl Clock for PythonClock {
    fn now(&self) -> Timestamp {
        Python::attach(|py| {
            self.timestamp.call0(py).expect("Error getting timestamp").extract(py).expect("Could not convert timestamp to int")
        })
    }
}

#[pyclass(unsendable)]
pub struct UndoManager {
    undo_manager: _UndoManager,
}

#[pymethods]
impl UndoManager {
    #[new]
    fn new(
        doc: &Doc,
        capture_timeout_millis: u64,
        timestamp: Py<PyAny>,
        undo_stack: Vec<StackItem>,
        redo_stack: Vec<StackItem>,
    ) -> Self {
        let options = Options {
            capture_timeout_millis,
            tracked_origins: HashSet::new(),
            capture_transaction: None,
            timestamp: Arc::new(PythonClock {timestamp}),
            init_undo_stack: undo_stack.into_iter().map(|s| s.stack_item).collect(),
            init_redo_stack: redo_stack.into_iter().map(|s| s.stack_item).collect(),
        };
        let undo_manager = _UndoManager::with_options(&doc.doc, options);
        UndoManager { undo_manager }
    }

    pub fn expand_scope_text(&mut self, scope: &Text) {
        self.undo_manager.expand_scope(&scope.text);
    }

    pub fn expand_scope_array(&mut self, scope: &Array) {
        self.undo_manager.expand_scope(&scope.array);
    }

    pub fn expand_scope_map(&mut self, scope: &Map) {
        self.undo_manager.expand_scope(&scope.map);
    }

    pub fn expand_scope_xmlfragment(&mut self, scope: &XmlFragment) {
        self.undo_manager.expand_scope(&scope.fragment);
    }

    pub fn include_origin(&mut self, origin: i128) {
        self.undo_manager.include_origin(origin);
    }

    pub fn exclude_origin(&mut self, origin: i128) {
        self.undo_manager.exclude_origin(origin);
    }

    pub fn can_undo(&mut self)  -> bool {
        self.undo_manager.can_undo()
    }

    pub fn undo(&mut self)  -> PyResult<bool> {
        if let Ok(res) = self.undo_manager.try_undo() {
            return Ok(res);
        }
        else {
            return Err(PyRuntimeError::new_err("Cannot acquire transaction"));
        }
    }

    pub fn can_redo(&mut self)  -> bool {
        self.undo_manager.can_redo()
    }

    pub fn redo(&mut self)  -> PyResult<bool> {
        if let Ok(res) = self.undo_manager.try_redo() {
            return Ok(res);
        }
        else {
            return Err(PyRuntimeError::new_err("Cannot acquire transaction"));
        }
    }

    pub fn clear(&mut self)  -> () {
        self.undo_manager.clear();
    }

    pub fn undo_stack<'py>(&mut self, py: Python<'py>) -> Bound<'py, PyList> {
        let elements = self.undo_manager.undo_stack().into_iter().map(|v| {
            StackItem::from(v.clone())
        });
        let res = PyList::new(py, elements);
        res.unwrap()
    }

    pub fn redo_stack<'py>(&mut self, py: Python<'py>) -> Bound<'py, PyList> {
        let elements = self.undo_manager.redo_stack().into_iter().map(|v| {
            StackItem::from(v.clone())
        });
        let res = PyList::new(py, elements);
        res.unwrap()
    }
}


#[pyclass]
#[derive(Clone)]
pub struct StackItem {
    stack_item: _StackItem<()>
}

impl StackItem {
    pub fn from(stack_item: _StackItem<()>) -> Self {
        StackItem { stack_item }
    }
}

#[pymethods]
impl StackItem {
    /// Get the deletions DeleteSet as a Python property
    #[getter]
    pub fn deletions(&self) -> DeleteSet {
        DeleteSet::from(self.stack_item.deletions().clone())
    }

    /// Get the insertions DeleteSet as a Python property
    #[getter]
    pub fn insertions(&self) -> DeleteSet {
        DeleteSet::from(self.stack_item.insertions().clone())
    }

    /// Encode the StackItem to bytes
    /// Returns a tuple of (deletions_bytes, insertions_bytes)
    pub fn encode<'py>(&self, py: Python<'py>) -> Bound<'py, pyo3::types::PyTuple> {
        let deletions_encoded = self.stack_item.deletions().encode_v1();
        let insertions_encoded = self.stack_item.insertions().encode_v1();
        pyo3::types::PyTuple::new(
            py,
            vec![
                PyBytes::new(py, &deletions_encoded).into_any(),
                PyBytes::new(py, &insertions_encoded).into_any(),
            ]
        ).unwrap()
    }

    /// Serialize the StackItem to a JSON string
    pub fn to_json_string(&self) -> Py<PyAny> {
        use std::collections::HashMap;
        use serde_json::json;

        let mut deletions_mapping: HashMap<u64, Vec<(u32, u32)>> = HashMap::new();
        for (client, ranges) in self.stack_item.deletions().iter() {
            let mut vec_ranges = Vec::new();
            for range in ranges.iter() {
                vec_ranges.push((range.start, range.end));
            }
            deletions_mapping.insert(*client, vec_ranges);
        }

        let mut insertions_mapping: HashMap<u64, Vec<(u32, u32)>> = HashMap::new();
        for (client, ranges) in self.stack_item.insertions().iter() {
            let mut vec_ranges = Vec::new();
            for range in ranges.iter() {
                vec_ranges.push((range.start, range.end));
            }
            insertions_mapping.insert(*client, vec_ranges);
        }

        let result = json!({
            "deletions": deletions_mapping,
            "insertions": insertions_mapping
        });

        let encoded = serde_json::to_string(&result).unwrap();
        Python::attach(|py| PyString::new(py, &encoded).into())
    }

    /// Decode a StackItem from bytes
    /// Takes a tuple of (deletions_bytes, insertions_bytes)
    #[staticmethod]
    pub fn decode(deletions_data: &Bound<'_, PyBytes>, insertions_data: &Bound<'_, PyBytes>) -> PyResult<Self> {
        let deletions_bytes: &[u8] = deletions_data.as_bytes();
        let insertions_bytes: &[u8] = insertions_data.as_bytes();
        
        let deletions = match _DeleteSet::decode_v1(deletions_bytes) {
            Ok(ds) => ds,
            Err(e) => return Err(pyo3::exceptions::PyValueError::new_err(format!(
                "Failed to decode deletions: {}",
                e
            ))),
        };
        
        let insertions = match _DeleteSet::decode_v1(insertions_bytes) {
            Ok(ds) => ds,
            Err(e) => return Err(pyo3::exceptions::PyValueError::new_err(format!(
                "Failed to decode insertions: {}",
                e
            ))),
        };

        let stack_item = _StackItem::with_meta(deletions, insertions, ());
        
        Ok(StackItem { stack_item })
    }

    /// Merge two StackItems into one containing union of deletions and insertions
    #[staticmethod]
    pub fn merge(a: &StackItem, b: &StackItem) -> StackItem {
        let mut stack_item = a.stack_item.clone();
        stack_item.merge(b.stack_item.clone(), |_a, _b| {});
        StackItem { stack_item }
    }

    fn __repr__(&self) -> String {
        format!("{0}", self.stack_item)
    }
}
