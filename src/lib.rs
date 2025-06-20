use pyo3::prelude::*;
use xml::XmlElement;
use xml::XmlEvent;
use xml::XmlFragment;
use xml::XmlText;
mod doc;
mod text;
mod array;
mod map;
mod transaction;
mod sticky_index;
mod subscription;
mod type_conversions;
mod undo;
mod update;
mod xml;
use crate::doc::Doc;
use crate::doc::TransactionEvent;
use crate::doc::SubdocsEvent;
use crate::text::{Text, TextEvent};
use crate::array::{Array, ArrayEvent};
use crate::map::{Map, MapEvent};
use crate::transaction::Transaction;
use crate::sticky_index::{StickyIndex, decode_sticky_index, get_sticky_index_from_json_string};
use crate::subscription::Subscription;
use crate::undo::{StackItem, UndoManager};
use crate::update::{get_state, get_update, merge_updates};

#[pymodule]
fn _pycrdt(_py: Python, m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_class::<Doc>()?;
    m.add_class::<TransactionEvent>()?;
    m.add_class::<SubdocsEvent>()?;
    m.add_class::<Text>()?;
    m.add_class::<TextEvent>()?;
    m.add_class::<Array>()?;
    m.add_class::<ArrayEvent>()?;
    m.add_class::<Map>()?;
    m.add_class::<MapEvent>()?;
    m.add_class::<Transaction>()?;
    m.add_class::<StackItem>()?;
    m.add_class::<StickyIndex>()?;
    m.add_class::<Subscription>()?;
    m.add_class::<UndoManager>()?;
    m.add_class::<XmlElement>()?;
    m.add_class::<XmlFragment>()?;
    m.add_class::<XmlText>()?;
    m.add_class::<XmlEvent>()?;
    m.add_function(wrap_pyfunction!(get_state, m)?)?;
    m.add_function(wrap_pyfunction!(get_update, m)?)?;
    m.add_function(wrap_pyfunction!(merge_updates, m)?)?;
    m.add_function(wrap_pyfunction!(decode_sticky_index, m)?)?;
    m.add_function(wrap_pyfunction!(get_sticky_index_from_json_string, m)?)?;
    Ok(())
}
