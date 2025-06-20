use pyo3::prelude::*;
use pyo3::types::{PyBytes, PyString};
use std::cell::RefCell;
use yrs::{StickyIndex as _StickyIndex, Assoc};
use yrs::updates::decoder::Decode;
use yrs::updates::encoder::Encode;
use crate::Transaction;

#[pyclass(unsendable)]
pub struct StickyIndex {
    sticky_index: RefCell<Option<_StickyIndex>>,
    assoc: Assoc,
}

impl From<Option<_StickyIndex>> for StickyIndex {
    fn from(sticky_index: Option<_StickyIndex>) -> Self {
        let s: _StickyIndex = unsafe {std::mem::transmute(sticky_index.clone())};
        StickyIndex { sticky_index: RefCell::from(Some(s)), assoc: sticky_index.unwrap().assoc }
    }
}

impl From<&[u8]> for StickyIndex {
    fn from(data: &[u8]) -> Self {
        let sticky_index = _StickyIndex::decode_v1(data).unwrap();
        let s: _StickyIndex = unsafe {std::mem::transmute(sticky_index.clone())};
        StickyIndex { sticky_index: RefCell::from(Some(s)), assoc: sticky_index.assoc }
    }
}

impl From<&str> for StickyIndex {
    fn from(data: &str) -> Self {
        let sticky_index = serde_json::from_str::<_StickyIndex>(data).unwrap();
        let s: _StickyIndex = unsafe {std::mem::transmute(sticky_index.clone())};
        StickyIndex { sticky_index: RefCell::from(Some(s)), assoc: sticky_index.assoc }
    }
}

#[pymethods]
impl StickyIndex {
    pub fn get_offset(&self, txn: &mut Transaction) -> u32 {
        let mut t0 = txn.transaction();
        let t1 = t0.as_mut().unwrap();
        let t = t1.as_ref();
        self.sticky_index.borrow_mut().as_mut().unwrap().get_offset(t).unwrap().index
    }

    pub fn encode(&self) -> PyObject {
        let encoded = self.sticky_index.borrow_mut().as_mut().unwrap().encode_v1();
        Python::with_gil(|py| PyBytes::new(py, &encoded).into())
    }

    pub fn to_json_string(&self) -> PyObject {
        let encoded = serde_json::to_string(self.sticky_index.borrow_mut().as_mut().unwrap()).unwrap();
        Python::with_gil(|py| PyString::new(py, &encoded).into())
    }

    pub fn get_assoc(&self) -> i8 {
        let _assoc: i8;
        match self.assoc {
            Assoc::After => _assoc = 0,
            _ => _assoc = -1,
        }
        _assoc
    }
}

#[pyfunction]
pub fn decode_sticky_index<'py>(data: &Bound<'_, PyBytes>) -> StickyIndex {
    let data: &[u8] = data.as_bytes();
    StickyIndex::from(data)
}

#[pyfunction]
pub fn get_sticky_index_from_json_string<'py>(data: &Bound<'_, PyString>) -> StickyIndex {
    let data: &str = data.to_str().unwrap();
    StickyIndex::from(data)
}
