use pyo3::prelude::*;
use pyo3::exceptions::PyValueError;
use pyo3::types::{PyBytes, PyTuple};
use yrs::{diff_updates_v1, encode_state_vector_from_update_v1, merge_updates_v1};

#[pyfunction]
pub fn merge_updates<'py>(py: Python<'py>, updates: &Bound<'_, PyTuple>) -> PyResult<Bound<'py, PyBytes>> {
    let updates: Vec<Vec<u8>> = updates.extract().unwrap();
    // Pure byte-to-byte work over owned/immutable buffers: release the GIL.
    let Ok(update) = py.detach(|| merge_updates_v1(&updates)) else {
        return Err(PyValueError::new_err("Cannot merge updates"));
    };
    Ok(PyBytes::new(py, &update))
}

#[pyfunction]
pub fn get_state<'py>(py: Python<'py>, update: &Bound<'_, PyBytes>) -> PyResult<Bound<'py, PyBytes>> {
    let update: &[u8] = update.extract()?;
    let Ok(u) = py.detach(|| encode_state_vector_from_update_v1(update)) else {
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
    let Ok(u) = py.detach(|| diff_updates_v1(update, state)) else {
        return Err(PyValueError::new_err("Cannot diff updates"));
    };
    Ok(PyBytes::new(py, &u))
}
