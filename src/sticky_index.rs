use pyo3::prelude::*;
use std::cell::RefCell;
use yrs::StickyIndex as _StickyIndex;
use crate::Transaction;

#[pyclass(unsendable)]
pub struct StickyIndex(RefCell<Option<_StickyIndex>>);

impl From<Option<_StickyIndex>> for StickyIndex {
    fn from(sticky_index: Option<_StickyIndex>) -> Self {
        let s: _StickyIndex = unsafe { std::mem::transmute(sticky_index)};
        StickyIndex(RefCell::from(Some(s)))
    }
}

#[pymethods]
impl StickyIndex {
    pub fn get_index(&self, txn: &mut Transaction) -> u32 {
        let mut t0 = txn.transaction();
        let t1 = t0.as_mut().unwrap();
        let t = t1.as_ref();
        self.0.borrow_mut().as_mut().unwrap().get_offset(t).unwrap().index
    }
}
