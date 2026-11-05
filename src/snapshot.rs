use pyo3::prelude::*;
use pyo3::types::PyBytes;
use yrs::{Snapshot as _Snapshot, ReadTxn};
use crate::transaction::Transaction;
use pyo3::types::PyType;
use yrs::updates::encoder::Encode;
use yrs::updates::decoder::Decode;

#[pyclass]
pub struct Snapshot {
    pub snapshot: _Snapshot,
}

impl Snapshot {
    pub fn from(snapshot: _Snapshot) -> Self {
        Snapshot { snapshot }
    }
}

#[pymethods]
impl Snapshot {
    /// Construct a snapshot from a Doc, using its given transaction
    #[classmethod]
    pub fn from_doc(_cls: &Bound<'_, PyType>, txn: &Transaction) -> PyResult<Self> {
        let mut t0 = txn.transaction()?;
        let t1 = t0.as_mut().unwrap();
        let t = t1.as_ref();
        let snapshot = t.snapshot();
        Ok(Snapshot { snapshot })
    }

    /// Encode the snapshot to bytes
    pub fn encode(&self) -> Py<PyAny> {
        let encoded = self.snapshot.encode_v1();
        Python::attach(|py: Python<'_>| PyBytes::new(py, &encoded).into())
    }

    /// Decode a snapshot from bytes
    #[classmethod]
    pub fn decode(_cls: &Bound<'_, PyType>, data: &Bound<'_, PyBytes>) -> PyResult<Self> {
        let bytes: &[u8] = data.as_bytes();
        match _Snapshot::decode_v1(bytes) {
            Ok(snapshot) => Ok(Snapshot { snapshot }),
            Err(e) => Err(pyo3::exceptions::PyValueError::new_err(format!("Failed to decode snapshot: {}", e)))
        }
    }
}
