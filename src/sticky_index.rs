use pyo3::prelude::*;
use pyo3::types::{PyBytes, PyString};
use yrs::{StickyIndex as _StickyIndex, Assoc};
use yrs::updates::decoder::Decode;
use yrs::updates::encoder::Encode;
use crate::Transaction;

#[pyclass]
pub struct StickyIndex {
    sticky_index: _StickyIndex,
    assoc: Assoc,
}

impl From<Option<_StickyIndex>> for StickyIndex {
    fn from(sticky_index: Option<_StickyIndex>) -> Self {
        let sticky_index = sticky_index.unwrap();
        StickyIndex { assoc: sticky_index.assoc, sticky_index }
    }
}

impl From<&[u8]> for StickyIndex {
    fn from(data: &[u8]) -> Self {
        let sticky_index = _StickyIndex::decode_v1(data).unwrap();
        StickyIndex { assoc: sticky_index.assoc, sticky_index }
    }
}

impl From<&str> for StickyIndex {
    fn from(data: &str) -> Self {
        let sticky_index = serde_json::from_str::<_StickyIndex>(data).unwrap();
        StickyIndex { assoc: sticky_index.assoc, sticky_index }
    }
}

#[pymethods]
impl StickyIndex {
    pub fn get_offset(&self, txn: &mut Transaction) -> PyResult<u32> {
        let mut t0 = txn.transaction()?;
        let t1 = t0.as_mut().unwrap();
        let t = t1.as_ref();
        Ok(self.sticky_index.get_offset(t).unwrap().index)
    }

    pub fn encode(&self) -> Py<PyAny> {
        let encoded = self.sticky_index.encode_v1();
        Python::attach(|py| PyBytes::new(py, &encoded).into())
    }

    pub fn to_json_string(&self) -> Py<PyAny> {
        let encoded = serde_json::to_string(&self.sticky_index).unwrap();
        Python::attach(|py| PyString::new(py, &encoded).into())
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
