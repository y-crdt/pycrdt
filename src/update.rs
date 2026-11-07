use pyo3::prelude::*;
use pyo3::exceptions::PyValueError;
use pyo3::marker::Ungil;
use pyo3::types::{PyBytes, PyTuple};
use yrs::{diff_updates_v1, encode_state_vector_from_update_v1, merge_updates_v1};

/// Smallest update, in bytes, for which the GIL is released while it is processed.
///
/// While another thread runs Python, a release can cost the caller one switch
/// interval (5 ms by default) before it gets the GIL back. Decoding and
/// integrating an update smaller than this takes less (about 3 ms for 64 KB of
/// small map entries), so keeping the GIL is cheaper for the caller and costs
/// other threads little. CPython's hashlib and zlib use a threshold for the same reason.
pub const DETACH_MIN_SIZE: usize = 64 * 1024;

/// Run `f` with the GIL released if `size` is at least `DETACH_MIN_SIZE`, and with
/// the GIL held otherwise.
pub fn detach_if_large<T, F>(py: Python<'_>, size: usize, f: F) -> T
where
    F: Ungil + FnOnce() -> T,
    T: Ungil,
{
    if size >= DETACH_MIN_SIZE {
        py.detach(f)
    } else {
        f()
    }
}

#[pyfunction]
pub fn merge_updates<'py>(py: Python<'py>, updates: &Bound<'_, PyTuple>) -> PyResult<Bound<'py, PyBytes>> {
    let updates: Vec<Vec<u8>> = updates.extract()?;
    // Pure byte-to-byte work over owned buffers: release the GIL for large inputs.
    let size = updates.iter().map(Vec::len).sum();
    let Ok(update) = detach_if_large(py, size, || merge_updates_v1(&updates)) else {
        return Err(PyValueError::new_err("Cannot merge updates"));
    };
    Ok(PyBytes::new(py, &update))
}

#[pyfunction]
pub fn get_state<'py>(py: Python<'py>, update: &Bound<'_, PyBytes>) -> PyResult<Bound<'py, PyBytes>> {
    let update: &[u8] = update.extract()?;
    let Ok(u) = detach_if_large(py, update.len(), || encode_state_vector_from_update_v1(update)) else {
        return Err(PyValueError::new_err(
            "Cannot encode state vector from update",
        ));
    };
    Ok(PyBytes::new(py, &u))
}

#[pyfunction]
pub fn get_update<'py>(py: Python<'py>, update: &Bound<'_, PyBytes>, state: &Bound<'_, PyBytes>) -> PyResult<Bound<'py, PyBytes>> {
    let update: &[u8] = update.extract()?;
    let state: &[u8] = state.extract()?;
    let Ok(u) = detach_if_large(py, update.len(), || diff_updates_v1(update, state)) else {
        return Err(PyValueError::new_err("Cannot diff updates"));
    };
    Ok(PyBytes::new(py, &u))
}
