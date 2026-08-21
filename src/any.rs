use pyo3::prelude::*;
use pyo3::exceptions::PyValueError;
use pyo3::types::{PyAny, PyBytes};
use yrs::Any;
use yrs::encoding::read::Cursor;
use crate::type_conversions::{ToPython, py_to_any_strict};

/// Encodes a Python value using the lib0 `Any` binary format.
#[pyfunction]
pub fn encode_any<'py>(py: Python<'py>, value: &Bound<'_, PyAny>) -> PyResult<Bound<'py, PyBytes>> {
    let any = py_to_any_strict(value)?;
    let mut encoder: Vec<u8> = Vec::new();
    any.encode(&mut encoder);
    Ok(PyBytes::new(py, &encoder))
}

/// Decodes the lib0 `Any` value starting at `offset`, returning it along with the offset just past
/// the bytes it consumed. The remaining bytes are left untouched, so this can be used to read an
/// `Any` value embedded in a larger message stream.
#[pyfunction]
pub fn decode_any<'py>(py: Python<'py>, data: &Bound<'_, PyBytes>, offset: usize) -> PyResult<(Bound<'py, PyAny>, usize)> {
    let data: &[u8] = data.extract()?;
    let mut decoder = Cursor { buf: data, next: offset };
    let Ok(any) = Any::decode(&mut decoder) else {
        return Err(PyValueError::new_err("Cannot decode any value"));
    };
    Ok((any.into_py(py), decoder.next))
}
