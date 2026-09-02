use crate::Transaction;
use crate::array::Array;
use crate::text::Text;
use pyo3::exceptions::{PyRuntimeError, PyTypeError, PyValueError};
use pyo3::prelude::*;
use pyo3::types::{PyBytes, PyString};
use yrs::updates::decoder::Decode;
use yrs::updates::encoder::Encode;
use yrs::{
    ArrayRef, Assoc, IndexedSequence, Offset, ReadTxn, StickyIndex as _StickyIndex, TextRef,
};

trait SequenceOwner {
    fn owns(&self, offset: &Offset) -> bool;
}

impl SequenceOwner for TextRef {
    fn owns(&self, offset: &Offset) -> bool {
        std::ptr::eq(offset.branch.as_ref(), self.as_ref())
    }
}

impl SequenceOwner for ArrayRef {
    fn owns(&self, offset: &Offset) -> bool {
        std::ptr::eq(offset.branch.as_ref(), self.as_ref())
    }
}

fn resolve_offset<T, S>(sticky_index: &_StickyIndex, txn: &T, sequence: &S) -> Option<u32>
where
    T: ReadTxn,
    S: SequenceOwner,
{
    let offset = sticky_index.get_offset(txn)?;
    if offset.branch.is_deleted() || !sequence.owns(&offset) {
        None
    } else {
        Some(offset.index)
    }
}

#[pyclass(unsendable)]
pub struct StickyIndex {
    sticky_index: _StickyIndex,
}

impl From<_StickyIndex> for StickyIndex {
    fn from(sticky_index: _StickyIndex) -> Self {
        StickyIndex { sticky_index }
    }
}

impl StickyIndex {
    pub(crate) fn from_sequence<T, S>(
        txn: &T,
        sequence: &S,
        index: u32,
        len: u32,
        assoc: Assoc,
    ) -> Option<Self>
    where
        T: ReadTxn,
        S: IndexedSequence,
    {
        if index > len {
            return None;
        }
        sequence
            .sticky_index(txn, index, assoc)
            .or_else(|| {
                (index == len && assoc == Assoc::After)
                    .then(|| _StickyIndex::from_type(txn, sequence, assoc))
            })
            .map(StickyIndex::from)
    }

    fn decode(data: &[u8]) -> Result<Self, String> {
        _StickyIndex::decode_v1(data)
            .map(StickyIndex::from)
            .map_err(|error| format!("Cannot decode sticky index: {error}"))
    }

    fn from_json_string(data: &str) -> Result<Self, String> {
        serde_json::from_str::<_StickyIndex>(data)
            .map(StickyIndex::from)
            .map_err(|error| format!("Cannot decode sticky index JSON: {error}"))
    }
}

#[pymethods]
impl StickyIndex {
    pub fn get_offset(&self, txn: &mut Transaction) -> PyResult<Option<u32>> {
        let mut transaction = txn.transaction();
        let transaction = transaction
            .as_mut()
            .ok_or_else(|| PyRuntimeError::new_err("No current transaction"))?;
        Ok(self
            .sticky_index
            .get_offset(transaction.as_ref())
            .map(|offset| offset.index))
    }

    pub fn resolve(
        &self,
        txn: &mut Transaction,
        sequence: &Bound<'_, PyAny>,
    ) -> PyResult<Option<u32>> {
        let mut transaction = txn.transaction();
        let transaction = transaction
            .as_mut()
            .ok_or_else(|| PyRuntimeError::new_err("No current transaction"))?;
        let transaction = transaction.as_ref();

        if let Ok(text) = sequence.cast::<Text>() {
            let text = text.try_borrow()?;
            Ok(resolve_offset(&self.sticky_index, transaction, &text.text))
        } else if let Ok(array) = sequence.cast::<Array>() {
            let array = array.try_borrow()?;
            Ok(resolve_offset(
                &self.sticky_index,
                transaction,
                &array.array,
            ))
        } else {
            Err(PyTypeError::new_err("sequence must be an Array or Text"))
        }
    }

    pub fn encode(&self) -> Py<PyAny> {
        let encoded = self.sticky_index.encode_v1();
        Python::attach(|py| PyBytes::new(py, &encoded).into())
    }

    pub fn to_json_string(&self) -> PyResult<Py<PyAny>> {
        let encoded = serde_json::to_string(&self.sticky_index).map_err(|error| {
            PyValueError::new_err(format!("Cannot encode sticky index JSON: {error}"))
        })?;
        Ok(Python::attach(|py| PyString::new(py, &encoded).into()))
    }

    pub fn get_assoc(&self) -> i8 {
        match self.sticky_index.assoc {
            Assoc::After => 0,
            Assoc::Before => -1,
        }
    }
}

#[pyfunction]
pub fn decode_sticky_index(data: &Bound<'_, PyBytes>) -> PyResult<StickyIndex> {
    StickyIndex::decode(data.as_bytes()).map_err(PyValueError::new_err)
}

#[pyfunction]
pub fn get_sticky_index_from_json_string(data: &Bound<'_, PyString>) -> PyResult<StickyIndex> {
    let data = data.to_str()?;
    StickyIndex::from_json_string(data).map_err(PyValueError::new_err)
}

#[cfg(test)]
mod tests {
    use super::{StickyIndex, resolve_offset};
    use yrs::types::text::TextPrelim;
    use yrs::updates::encoder::Encode;
    use yrs::{
        Array, Assoc, ClientID, Doc, ID, IndexedSequence, Map, ReadTxn,
        StickyIndex as _StickyIndex, Text, Transact,
    };

    fn check_positions<T, S>(txn: &T, sequence: &S, len: u32)
    where
        T: ReadTxn,
        S: yrs::IndexedSequence + super::SequenceOwner,
    {
        let indexes = if len == 0 { vec![0] } else { vec![0, 1, len] };
        for assoc in [Assoc::After, Assoc::Before] {
            for index in indexes.iter().copied() {
                let sticky_index = StickyIndex::from_sequence(txn, sequence, index, len, assoc)
                    .expect("position should be valid");
                assert_eq!(
                    resolve_offset(&sticky_index.sticky_index, txn, sequence),
                    Some(index)
                );
            }
        }
    }

    #[test]
    fn resolves_text_owner_and_rejects_sibling() {
        let doc = Doc::with_client_id(1);
        let owner = doc.get_or_insert_text("owner");
        let sibling = doc.get_or_insert_text("sibling");
        let mut txn = doc.transact_mut();
        owner.insert(&mut txn, 0, "abc");
        sibling.insert(&mut txn, 0, "abc");

        for assoc in [Assoc::After, Assoc::Before] {
            let sticky_index = owner.sticky_index(&txn, 1, assoc).unwrap();
            assert_eq!(resolve_offset(&sticky_index, &txn, &owner), Some(1));
            assert_eq!(resolve_offset(&sticky_index, &txn, &sibling), None);
        }
    }

    #[test]
    fn resolves_array_owner_and_rejects_sibling() {
        let doc = Doc::with_client_id(1);
        let owner = doc.get_or_insert_array("owner");
        let sibling = doc.get_or_insert_array("sibling");
        let mut txn = doc.transact_mut();
        owner.insert_range(&mut txn, 0, [1, 2, 3]);
        sibling.insert_range(&mut txn, 0, [1, 2, 3]);

        for assoc in [Assoc::After, Assoc::Before] {
            let sticky_index = owner.sticky_index(&txn, 1, assoc).unwrap();
            assert_eq!(resolve_offset(&sticky_index, &txn, &owner), Some(1));
            assert_eq!(resolve_offset(&sticky_index, &txn, &sibling), None);
        }
    }

    #[test]
    fn resolves_empty_start_interior_and_end_positions() {
        let doc = Doc::with_client_id(1);
        let empty_text = doc.get_or_insert_text("empty_text");
        let empty_array = doc.get_or_insert_array("empty_array");
        let text = doc.get_or_insert_text("text");
        let array = doc.get_or_insert_array("array");
        let mut txn = doc.transact_mut();
        text.insert(&mut txn, 0, "abc");
        array.insert_range(&mut txn, 0, [1, 2, 3]);

        check_positions(&txn, &empty_text, 0);
        check_positions(&txn, &empty_array, 0);
        check_positions(&txn, &text, 3);
        check_positions(&txn, &array, 3);
        for assoc in [Assoc::After, Assoc::Before] {
            assert!(StickyIndex::from_sequence(&txn, &text, 4, 3, assoc).is_none());
            assert!(StickyIndex::from_sequence(&txn, &array, 4, 3, assoc).is_none());
        }
    }

    #[test]
    fn rejects_deleted_and_unresolvable_positions() {
        let doc = Doc::with_client_id(1);
        let root = doc.get_or_insert_map("root");
        let mut txn = doc.transact_mut();
        let text = root.insert(&mut txn, "text", TextPrelim::new("abc"));
        let sticky_index = text.sticky_index(&txn, 1, Assoc::After).unwrap();
        root.remove(&mut txn, "text");

        assert_eq!(resolve_offset(&sticky_index, &txn, &text), None);

        let unknown = _StickyIndex::from_id(ID::new(ClientID::new(999), 0), Assoc::After);
        assert_eq!(unknown.get_offset(&txn), None);
        assert_eq!(resolve_offset(&unknown, &txn, &text), None);
    }

    #[test]
    fn malformed_encodings_return_errors() {
        assert!(StickyIndex::decode(&[]).is_err());
        assert!(StickyIndex::decode(&[u8::MAX]).is_err());
        assert!(StickyIndex::from_json_string("{}").is_err());
    }

    #[test]
    fn serialization_and_raw_offset_behavior_remain_compatible() {
        let doc = Doc::with_client_id(1);
        let text = doc.get_or_insert_text("text");
        let mut txn = doc.transact_mut();
        text.insert(&mut txn, 0, "abc");
        let sticky_index = text.sticky_index(&txn, 1, Assoc::Before).unwrap();

        let binary = sticky_index.encode_v1();
        let decoded = StickyIndex::decode(&binary).expect("binary should decode");
        assert_eq!(decoded.sticky_index.get_offset(&txn).unwrap().index, 1);
        assert_eq!(decoded.sticky_index.assoc, Assoc::Before);

        let json = serde_json::to_string(&sticky_index).unwrap();
        let decoded = StickyIndex::from_json_string(&json).expect("JSON should decode");
        assert_eq!(decoded.sticky_index.get_offset(&txn).unwrap().index, 1);
        assert_eq!(decoded.sticky_index.assoc, Assoc::Before);
    }
}
