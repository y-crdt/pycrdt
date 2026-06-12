use std::cell::RefCell;
use std::collections::hash_map::DefaultHasher;
use std::hash::{Hash, Hasher};

use pyo3::exceptions::{PyTypeError, PyValueError};
use pyo3::prelude::*;
use pyo3::types::{PyBool, PyBytes, PyDict, PyFloat, PyInt, PyList, PyString, PyTuple};
use pyo3::IntoPyObjectExt;
use serde::{Deserialize, Deserializer, Serialize, Serializer};
use serde_json::Value;

use yrs::block::BlockRange;
use yrs::updates::decoder::Decode;
use yrs::updates::encoder::Encode;
use yrs::{
    AttrRange as _AttrRange, ClientID, ContentAttribute as _ContentAttribute, Diff, IdMap as _IdMap,
    ID,
};

use crate::undo::IdSet;

/// A JSON-compatible attribute value, used as the value type of [`yrs::IdMap`].
///
/// `yrs::IdMap<A>` requires `A: Serialize + DeserializeOwned + PartialEq + Eq + Hash + Clone`.
/// `serde_json::Value` provides everything except `Eq` and `Hash` (it holds `f64`), which we
/// implement here on top of the canonical (sorted-key) JSON serialization so that equality and
/// hashing stay consistent.
#[derive(Clone, Debug)]
pub(crate) struct AttrValue(Value);

impl PartialEq for AttrValue {
    fn eq(&self, other: &Self) -> bool {
        self.0.to_string() == other.0.to_string()
    }
}

impl Eq for AttrValue {}

impl Hash for AttrValue {
    fn hash<H: Hasher>(&self, state: &mut H) {
        self.0.to_string().hash(state);
    }
}

// `yrs::IdMap` encodes attribute values through its `Any`-based wire format, which coerces all
// JSON integers (including those nested in arrays/objects) to floats. To round-trip arbitrary JSON
// losslessly, we encode the value as its JSON *string* representation (which the wire format
// preserves verbatim) and parse it back on decode.
impl Serialize for AttrValue {
    fn serialize<S: Serializer>(&self, serializer: S) -> Result<S::Ok, S::Error> {
        serializer.serialize_str(&self.0.to_string())
    }
}

impl<'de> Deserialize<'de> for AttrValue {
    fn deserialize<D: Deserializer<'de>>(deserializer: D) -> Result<Self, D::Error> {
        let json = String::deserialize(deserializer)?;
        let value = serde_json::from_str(&json).map_err(serde::de::Error::custom)?;
        Ok(AttrValue(value))
    }
}

/// Convert a Python object into a `serde_json::Value`.
fn py_to_json(value: &Bound<'_, PyAny>) -> PyResult<Value> {
    if value.is_none() {
        Ok(Value::Null)
    } else if value.is_instance_of::<PyBool>() {
        // `bool` must be checked before `int` (in Python `bool` is a subclass of `int`).
        Ok(Value::Bool(value.extract()?))
    } else if value.is_instance_of::<PyInt>() {
        if let Ok(i) = value.extract::<i64>() {
            Ok(Value::Number(i.into()))
        } else if let Ok(u) = value.extract::<u64>() {
            Ok(Value::Number(u.into()))
        } else {
            Err(PyValueError::new_err(
                "Integer attribute value is out of the supported 64-bit range",
            ))
        }
    } else if value.is_instance_of::<PyFloat>() {
        let f: f64 = value.extract()?;
        serde_json::Number::from_f64(f)
            .map(Value::Number)
            .ok_or_else(|| PyValueError::new_err("NaN and infinity cannot be used as attribute values"))
    } else if value.is_instance_of::<PyString>() {
        Ok(Value::String(value.extract()?))
    } else if let Ok(list) = value.cast::<PyList>() {
        let mut items = Vec::with_capacity(list.len());
        for item in list.iter() {
            items.push(py_to_json(&item)?);
        }
        Ok(Value::Array(items))
    } else if let Ok(tuple) = value.cast::<PyTuple>() {
        let mut items = Vec::with_capacity(tuple.len());
        for item in tuple.iter() {
            items.push(py_to_json(&item)?);
        }
        Ok(Value::Array(items))
    } else if let Ok(dict) = value.cast::<PyDict>() {
        let mut map = serde_json::Map::new();
        for (k, v) in dict.iter() {
            let key: String = k
                .extract()
                .map_err(|_| PyTypeError::new_err("JSON object keys must be strings"))?;
            map.insert(key, py_to_json(&v)?);
        }
        Ok(Value::Object(map))
    } else {
        Err(PyTypeError::new_err(
            "Attribute value must be JSON-serializable (None, bool, int, float, str, list, tuple, or dict)",
        ))
    }
}

/// Convert a `serde_json::Value` into a Python object.
fn json_to_py<'py>(py: Python<'py>, value: &Value) -> Bound<'py, PyAny> {
    match value {
        Value::Null => py.None().into_bound(py),
        Value::Bool(b) => PyBool::new(py, *b).into_bound_py_any(py).unwrap(),
        Value::Number(n) => {
            if let Some(i) = n.as_i64() {
                i.into_pyobject(py).unwrap().into_bound_py_any(py).unwrap()
            } else if let Some(u) = n.as_u64() {
                u.into_pyobject(py).unwrap().into_bound_py_any(py).unwrap()
            } else {
                PyFloat::new(py, n.as_f64().unwrap())
                    .into_bound_py_any(py)
                    .unwrap()
            }
        }
        Value::String(s) => s.into_pyobject(py).unwrap().into_bound_py_any(py).unwrap(),
        Value::Array(arr) => {
            let items: Vec<Bound<PyAny>> = arr.iter().map(|v| json_to_py(py, v)).collect();
            PyList::new(py, items)
                .unwrap()
                .into_bound_py_any(py)
                .unwrap()
        }
        Value::Object(obj) => {
            let dict = PyDict::new(py);
            for (k, v) in obj {
                dict.set_item(k, json_to_py(py, v)).unwrap();
            }
            dict.into_bound_py_any(py).unwrap()
        }
    }
}

/// A named attribute attached to a range of block IDs.
#[pyclass(from_py_object)]
#[derive(Clone)]
pub struct ContentAttribute {
    pub(crate) inner: _ContentAttribute<AttrValue>,
}

#[pymethods]
impl ContentAttribute {
    /// Create a new attribute with the given `name` and JSON-compatible `value`.
    #[new]
    pub fn new(name: String, value: &Bound<'_, PyAny>) -> PyResult<Self> {
        let json = py_to_json(value)?;
        Ok(ContentAttribute {
            inner: _ContentAttribute::new(name, AttrValue(json)),
        })
    }

    /// The attribute name.
    #[getter]
    pub fn name(&self) -> String {
        self.inner.name().to_string()
    }

    /// The attribute value, as a JSON-compatible Python object.
    #[getter]
    pub fn value<'py>(&self, py: Python<'py>) -> Bound<'py, PyAny> {
        json_to_py(py, &self.inner.value().0)
    }

    fn __eq__(&self, other: &ContentAttribute) -> bool {
        self.inner == other.inner
    }

    fn __hash__(&self) -> u64 {
        let mut hasher = DefaultHasher::new();
        self.inner.hash(&mut hasher);
        hasher.finish()
    }

    fn __repr__(&self, py: Python<'_>) -> String {
        let value = self.value(py);
        format!("ContentAttribute(name={:?}, value={})", self.inner.name(), value)
    }
}

/// A contiguous clock range together with the attributes attached to it.
///
/// Returned by [`IdMap.attributions`][crate::id_map::IdMap::attributions] and
/// [`IdMap.entries`][crate::id_map::IdMap::entries]. Ranges produced by `attributions` that fall
/// outside any attributed region carry an empty `attributes` list.
#[pyclass(skip_from_py_object)]
#[derive(Clone)]
pub struct AttrRange {
    /// Inclusive start clock of the range.
    #[pyo3(get)]
    start: u32,
    /// Exclusive end clock of the range.
    #[pyo3(get)]
    end: u32,
    attributes: Vec<ContentAttribute>,
}

impl AttrRange {
    fn from_inner(range: _AttrRange<AttrValue>) -> Self {
        AttrRange {
            start: range.range.start,
            end: range.range.end,
            attributes: range
                .attrs
                .0
                .into_iter()
                .map(|inner| ContentAttribute { inner })
                .collect(),
        }
    }
}

#[pymethods]
impl AttrRange {
    /// The attributes attached to this range (may be empty).
    #[getter]
    fn attributes(&self) -> Vec<ContentAttribute> {
        self.attributes.clone()
    }

    fn __repr__(&self, py: Python<'_>) -> String {
        let attrs: Vec<String> = self
            .attributes
            .iter()
            .map(|a| a.__repr__(py))
            .collect();
        format!("AttrRange(start={}, end={}, attributes=[{}])", self.start, self.end, attrs.join(", "))
    }
}

/// A set of block ID ranges, each associated with attribute metadata.
///
/// This is the Python binding for `yrs::IdMap`. It is similar to [`IdSet`][crate::undo.IdSet],
/// but it additionally attaches [`ContentAttribute`] metadata to individual block ranges.
#[pyclass(from_py_object)]
#[derive(Clone)]
pub struct IdMap {
    inner: _IdMap<AttrValue>,
}

impl IdMap {
    fn extract_attrs(attributes: Vec<ContentAttribute>) -> Vec<_ContentAttribute<AttrValue>> {
        attributes.into_iter().map(|a| a.inner).collect()
    }
}

#[pymethods]
impl IdMap {
    /// Create a new, empty IdMap.
    #[new]
    pub fn new() -> Self {
        IdMap {
            inner: _IdMap::new(),
        }
    }

    /// Attach `attributes` to the range `[clock, clock + length)` of the given `client`.
    ///
    /// Inserting an empty attribute list or a zero-length range is a no-op.
    pub fn insert(&mut self, client: u64, clock: u32, length: u32, attributes: Vec<ContentAttribute>) {
        let range = BlockRange::new(ID::new(ClientID::new(client), clock), length);
        self.inner.insert(range, IdMap::extract_attrs(attributes));
    }

    /// Remove the range `[clock, clock + length)` of the given `client` from the map.
    pub fn remove(&mut self, client: u64, clock: u32, length: u32) {
        let range = BlockRange::new(ID::new(ClientID::new(client), clock), length);
        self.inner.remove(&range);
    }

    /// Return whether the `(client, clock)` ID is contained in the map.
    pub fn contains(&self, client: u64, clock: u32) -> bool {
        self.inner.contains(&ID::new(ClientID::new(client), clock))
    }

    /// Return whether the map is empty.
    pub fn is_empty(&self) -> bool {
        self.inner.is_empty()
    }

    /// Return the attributions covering `[clock, clock + length)` of the given `client`.
    ///
    /// The result is a list of [`AttrRange`] objects spanning the whole queried range; gaps with no
    /// attributes are returned as ranges with an empty `attributes` list.
    pub fn attributions(&self, client: u64, clock: u32, length: u32) -> Vec<AttrRange> {
        let range = BlockRange::new(ID::new(ClientID::new(client), clock), length);
        self.inner
            .attributions(&range)
            .into_iter()
            .map(AttrRange::from_inner)
            .collect()
    }

    /// Return every `(client, AttrRange)` entry stored in the map.
    pub fn entries(&self) -> Vec<(u64, AttrRange)> {
        self.inner
            .iter()
            .map(|(client, range)| (client.get(), AttrRange::from_inner(range)))
            .collect()
    }

    /// Merge `other` into this map in place (union of ranges and attributes).
    pub fn merge_with(&mut self, other: &IdMap) {
        self.inner.merge_with(other.inner.clone());
    }

    /// Return the union of several maps.
    #[staticmethod]
    pub fn merge_many(maps: Vec<IdMap>) -> IdMap {
        let inners: Vec<_IdMap<AttrValue>> = maps.into_iter().map(|m| m.inner).collect();
        IdMap {
            inner: _IdMap::merge_many(&inners),
        }
    }

    /// Intersect this map with `other` in place.
    pub fn intersect_with(&mut self, other: &IdMap) {
        self.inner.intersect_with(&other.inner);
    }

    /// Remove from this map every range that is present in `other`, which may be an `IdMap` or an
    /// `IdSet`.
    pub fn diff_with(&mut self, other: &Bound<'_, PyAny>) -> PyResult<()> {
        if let Ok(map) = other.cast::<IdMap>() {
            self.inner.diff_with(&map.borrow().inner);
            Ok(())
        } else if let Ok(set) = other.cast::<IdSet>() {
            self.inner.diff_with(set.borrow().inner());
            Ok(())
        } else {
            Err(PyTypeError::new_err("diff_with() expects an IdMap or IdSet"))
        }
    }

    /// Return a new map keeping only the ranges whose attributes satisfy `predicate`.
    ///
    /// `predicate` is called with the list of [`ContentAttribute`] of each range and must return a
    /// boolean.
    pub fn filter(&self, predicate: Py<PyAny>) -> PyResult<IdMap> {
        let error: RefCell<Option<PyErr>> = RefCell::new(None);
        let filtered = self.inner.filter(|attrs: &[_ContentAttribute<AttrValue>]| {
            if error.borrow().is_some() {
                return false;
            }
            Python::attach(|py| {
                let items: Vec<ContentAttribute> = attrs
                    .iter()
                    .map(|inner| ContentAttribute { inner: inner.clone() })
                    .collect();
                match PyList::new(py, items) {
                    Ok(list) => match predicate.call1(py, (list,)) {
                        Ok(result) => result.extract::<bool>(py).unwrap_or(false),
                        Err(e) => {
                            *error.borrow_mut() = Some(e);
                            false
                        }
                    },
                    Err(e) => {
                        *error.borrow_mut() = Some(e.into());
                        false
                    }
                }
            })
        });
        if let Some(e) = error.into_inner() {
            return Err(e);
        }
        Ok(IdMap { inner: filtered })
    }

    /// Return an [`IdSet`] with the same ranges as this map, stripped of attributes.
    pub fn as_id_set(&self) -> IdSet {
        IdSet::from(self.inner.as_id_set())
    }

    /// Build an `IdMap` from an `IdSet`, attaching `attributes` to every range.
    #[staticmethod]
    pub fn from_set(id_set: &IdSet, attributes: Vec<ContentAttribute>) -> IdMap {
        IdMap {
            inner: _IdMap::from_set(id_set.inner().clone(), IdMap::extract_attrs(attributes)),
        }
    }

    /// Encode the map to bytes.
    pub fn encode(&self) -> Py<PyAny> {
        let encoded = self.inner.encode_v1();
        Python::attach(|py: Python<'_>| PyBytes::new(py, &encoded).into())
    }

    /// Decode a map from bytes.
    #[staticmethod]
    pub fn decode(data: &Bound<'_, PyBytes>) -> PyResult<Self> {
        let bytes: &[u8] = data.as_bytes();
        match _IdMap::<AttrValue>::decode_v1(bytes) {
            Ok(inner) => Ok(IdMap { inner }),
            Err(e) => Err(PyValueError::new_err(format!("Failed to decode IdMap: {}", e))),
        }
    }

    fn __eq__(&self, other: &IdMap) -> bool {
        self.inner == other.inner
    }

    fn __repr__(&self) -> String {
        format!("{:?}", self.inner)
    }
}
