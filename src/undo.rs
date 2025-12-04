use std::collections::HashSet;
use std::sync::Arc;
use pyo3::prelude::*;
use pyo3::types::{PyList, PyBytes};
use pyo3::exceptions::PyRuntimeError;
use yrs::DeleteSet as _DeleteSet;
use yrs::undo::{
    Options,
    StackItem as _StackItem,
    UndoManager as _UndoManager,
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
    undo_manager: _UndoManager<PyMeta>,
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
        let options = Options::<PyMeta> {
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
    stack_item: _StackItem<PyMeta>
}

impl StackItem {
    pub(crate) fn from(stack_item: _StackItem<PyMeta>) -> Self {
        StackItem { stack_item }
    }
}

#[pymethods]
impl StackItem {
    /// Create a new StackItem with deletions, insertions, and optional metadata
    /// Metadata can be any Python object (dict, string, int, etc.)
    #[new]
    #[pyo3(signature = (deletions, insertions, meta=None))]
    pub fn new(deletions: &DeleteSet, insertions: &DeleteSet, meta: Option<Py<PyAny>>) -> Self {
        let stack_item = _StackItem::with_meta(
            deletions.delete_set.clone(),
            insertions.delete_set.clone(),
            PyMeta(meta),
        );
        StackItem { stack_item }
    }

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

    /// Get the metadata as a Python property
    #[getter]
    pub fn meta(&self) -> Option<Py<PyAny>> {
        self.stack_item.meta().0.as_ref().map(|py_obj| {
            Python::attach(|py| py_obj.clone_ref(py))
        })
    }

    /// Merge two StackItems into one containing union of deletions and insertions
    /// merge_meta is a function that takes (meta_a, meta_b) and returns the merged metadata
    #[staticmethod]
    #[pyo3(signature = (a, b, merge_meta=None))]
    pub fn merge(a: &StackItem, b: &StackItem, merge_meta: Option<Py<PyAny>>) -> PyResult<StackItem> {
        let mut stack_item = a.stack_item.clone();
        let mut error: Option<PyErr> = None;

        stack_item.merge(b.stack_item.clone(), |meta_a, meta_b| {
            if let Some(ref handler) = merge_meta {
                Python::attach(|py| {
                    let args = (
                        meta_a.0.as_ref().map(|m| m.clone_ref(py)),
                        meta_b.0.as_ref().map(|m| m.clone_ref(py))
                    );
                    match handler.call1(py, args) {
                        Ok(result) => {
                            meta_a.0 = Some(result);
                        }
                        Err(e) => {
                            error = Some(e);
                        }
                    }
                })
            }
            // If no handler, keep first metadata (do nothing)
        });

        // Check if an error occurred during the merge callback
        if let Some(err) = error {
            return Err(err);
        }

        Ok(StackItem { stack_item })
    }

    /// Support for generic type hints like StackItem[dict]
    #[classmethod]
    fn __class_getitem__(cls: &Bound<'_, pyo3::types::PyType>, _item: &Bound<'_, PyAny>) -> Py<pyo3::types::PyType> {
        // Return the class itself - this is just for type hinting support
        cls.clone().unbind()
    }

    fn __repr__(&self) -> String {
        format!("{0}", self.stack_item)
    }
}


/// Wrapper for Python objects to use as yrs StackItem metadata.
#[derive(Default)]
pub(crate) struct PyMeta(Option<Py<PyAny>>);

unsafe impl Send for PyMeta {}
unsafe impl Sync for PyMeta {}

impl Clone for PyMeta {
    fn clone(&self) -> Self {
        PyMeta(self.0.as_ref().map(|py_obj| {
            Python::attach(|py| py_obj.clone_ref(py))
        }))
    }
}
