use std::collections::HashSet;
use std::sync::Arc;
use pyo3::prelude::*;
use pyo3::types::PyList;
use pyo3::exceptions::PyRuntimeError;
use yrs::{
    UndoManager as _UndoManager,
};
use yrs::undo::{
    Options,
    StackItem as _StackItem,
};
use yrs::sync::{Clock, Timestamp};
use crate::doc::Doc;
use crate::text::Text;
use crate::array::Array;
use crate::map::Map;
use crate::xml::XmlFragment;

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
    fn new(doc: &Doc, capture_timeout_millis: u64, timestamp: Py<PyAny>) -> Self {
        let mut options = Options {
            capture_timeout_millis: 500,
            tracked_origins: HashSet::new(),
            capture_transaction: None,
            timestamp: Arc::new(PythonClock {timestamp}),
        };
        options.capture_timeout_millis = capture_timeout_millis;
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
    fn __repr__(&self) -> String {
        format!("{0}", self.stack_item)
    }
}
