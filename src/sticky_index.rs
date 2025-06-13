use pyo3::prelude::*;
use yrs::StickyIndex;

#[pyclass]
pub struct PyStickyIndex {
    pub idx: StickyIndex,
}

impl From<StickyIndex> for PyStickyIndex {
    fn from(s: StickyIndex) -> Self {
        PyStickyIndex { idx: s }
    }
}