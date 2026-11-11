use pyo3::prelude::*;
use pyo3::exceptions::PyValueError;
use pyo3::marker::Ungil;
use pyo3::types::{PyBytes, PyTuple};
use yrs::{diff_updates_v1, encode_state_vector_from_update_v1, merge_updates_v1, StateVector};

/// Smallest update, in bytes, for which the GIL is released while it is processed.
///
/// While another thread runs Python, a release can cost the caller one switch
/// interval (5 ms by default) before it gets the GIL back. Decoding and
/// integrating an update smaller than this takes less (1 to 3 ms for 64 KB of
/// small map entries), so keeping the GIL is cheaper for the caller and costs
/// other threads little. CPython's hashlib and zlib use a threshold for the same reason.
pub const DETACH_MIN_SIZE: usize = 64 * 1024;

/// Smallest `encode_work`, in clock units, for which `Doc.get_update` releases the GIL.
///
/// Below it, encoding a map of small values or a text takes up to about 1.5 ms.
/// The work counts clock units, not bytes, so a document whose size is in long
/// strings (such as images in notebook outputs) keeps the GIL, as on main.
pub const ENCODE_DETACH_MIN_WORK: u64 = 16 * 1024;

/// Estimate the work to encode the difference from `remote` to `local`, in clock units.
///
/// yrs encodes the blocks that `remote` is missing, then walks every block of the
/// document to encode the delete set. The walk costs less per clock unit than the
/// encoding (a fifth to a tenth for map entries, less for text), so one eighth of
/// the document's clock units is added: a large document that is already up to
/// date still counts.
/// A clock unit is a map entry, an array element or a character, so a long string
/// in a map entry counts as one unit, and a long paste costs less per unit than
/// other content.
pub fn encode_work(local: &StateVector, remote: &StateVector) -> u64 {
    let mut missing: u64 = 0;
    let mut total: u64 = 0;
    for (client, &clock) in local.iter() {
        total += u64::from(clock);
        missing += u64::from(clock.saturating_sub(remote.get(client)));
    }
    missing + total / 8
}

/// Run `f` with the GIL released if `detach` is true, and with the GIL held otherwise.
pub fn detach_if<T, F>(py: Python<'_>, detach: bool, f: F) -> T
where
    F: Ungil + FnOnce() -> T,
    T: Ungil,
{
    if detach {
        py.detach(f)
    } else {
        f()
    }
}

#[pyfunction]
pub fn merge_updates<'py>(py: Python<'py>, updates: &Bound<'_, PyTuple>) -> PyResult<Bound<'py, PyBytes>> {
    let updates: Vec<Vec<u8>> = updates.extract()?;
    // Pure byte-to-byte work over owned buffers: release the GIL for large inputs.
    let size: usize = updates.iter().map(Vec::len).sum();
    let Ok(update) = detach_if(py, size >= DETACH_MIN_SIZE, || merge_updates_v1(&updates)) else {
        return Err(PyValueError::new_err("Cannot merge updates"));
    };
    Ok(PyBytes::new(py, &update))
}

#[pyfunction]
pub fn get_state<'py>(py: Python<'py>, update: &Bound<'_, PyBytes>) -> PyResult<Bound<'py, PyBytes>> {
    let update: &[u8] = update.extract()?;
    let Ok(u) = detach_if(py, update.len() >= DETACH_MIN_SIZE, || encode_state_vector_from_update_v1(update)) else {
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
    let Ok(u) = detach_if(py, update.len() >= DETACH_MIN_SIZE, || diff_updates_v1(update, state)) else {
        return Err(PyValueError::new_err("Cannot diff updates"));
    };
    Ok(PyBytes::new(py, &u))
}
