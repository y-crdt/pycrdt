use pyo3::prelude::*;
use pyo3::IntoPyObjectExt;
use pyo3::types::{PyAny, PyBool, PyByteArray, PyBytes, PyDict, PyFloat, PyIterator, PyList, PyInt, PyString};
use yrs::types::{Attrs, Change, EntryChange, Delta, Events, Path, PathSegment};
use yrs::{Any, Out, TransactionMut, XmlOut};
use std::collections::{VecDeque, HashMap};
use std::sync::Arc;
use crate::text::{Text, TextEvent};
use crate::array::{Array, ArrayEvent};
use crate::map::{Map, MapEvent};
use crate::doc::Doc;
use crate::xml::{XmlElement, XmlEvent, XmlFragment, XmlText};

pub trait ToPython {
    fn into_py<'py>(self, py: Python<'py>) -> Bound<'py, PyAny>;
}

impl<T: ToPython> ToPython for Vec<T> {
    fn into_py<'py>(self, py: Python<'py>) -> Bound<'py, PyAny> {
        let elements = self.into_iter().map(|v| v.into_py(py));
        PyList::new(py, elements).unwrap().into_bound_py_any(py).unwrap()
    }
}

impl<T: ToPython> ToPython for VecDeque<T> {
    fn into_py<'py>(self, py: Python<'py>) -> Bound<'py, PyAny> {
        let elements = self.into_iter().map(|v| v.into_py(py));
        PyList::new(py, elements).unwrap().into_bound_py_any(py).unwrap()
    }
}

impl ToPython for Path {
    fn into_py<'py>(self, py: Python<'py>) -> Bound<'py, PyAny> {
        let result = PyList::empty(py);
        for segment in self {
            match segment {
                PathSegment::Key(key) => {
                    result.append(key.as_ref()).unwrap();
                }
                PathSegment::Index(idx) => {
                    result.append(idx).unwrap();
                }
            }
        }
        result.into_bound_py_any(py).unwrap()
    }
}

impl ToPython for Delta {
    fn into_py<'py>(self, py: Python<'py>) -> Bound<'py, PyAny> {
        let result = PyDict::new(py);
        match self {
            Delta::Inserted(value, attrs) => {
                let value = value.clone().into_py(py);
                result.set_item("insert", value).unwrap();

                if let Some(attrs) = attrs {
                    let attrs = (&*attrs).into_py(py);
                    result.set_item("attributes", attrs).unwrap();
                }
            }
            Delta::Retain(len, attrs) => {
                result.set_item("retain", len).unwrap();

                if let Some(attrs) = attrs {
                    let attrs = (&*attrs).into_py(py);
                    result.set_item("attributes", attrs).unwrap();
                }
            }
            Delta::Deleted(len) => {
                result.set_item("delete", len).unwrap();
            }
        }
        result.into_bound_py_any(py).unwrap()
    }
}

impl ToPython for Out {
    fn into_py<'py>(self, py: Python<'py>) -> Bound<'py, PyAny> {
        match self {
            Out::Any(v) => v.into_py(py),
            Out::YXmlText(v) => Py::new(py, XmlText::from(v)).unwrap().into_any().into_bound(py),
            Out::YText(v) => Py::new(py, Text::from(v)).unwrap().into_any().into_bound(py),
            Out::YArray(v) => Py::new(py, Array::from(v)).unwrap().into_any().into_bound(py),
            Out::YMap(v) => Py::new(py, Map::from(v)).unwrap().into_any().into_bound(py),
            Out::YDoc(v) => Py::new(py, Doc::from(v)).unwrap().into_any().into_bound(py),
            Out::YXmlElement(v) => Py::new(py, XmlElement::from(v)).unwrap().into_any().into_bound(py),
            Out::YXmlFragment(v) => Py::new(py, XmlFragment::from(v)).unwrap().into_any().into_bound(py),
            Out::UndefinedRef(_) => py.None().into_bound(py),
        }
    }
}

impl ToPython for XmlOut {
    fn into_py<'py>(self, py: Python<'py>) -> Bound<'py, PyAny> {
        match self {
            XmlOut::Element(xml_element_ref) => Py::new(py, XmlElement::from(xml_element_ref))
                .unwrap()
                .into_any()
                .into_bound(py),
            XmlOut::Fragment(xml_fragment_ref) => Py::new(py, XmlFragment::from(xml_fragment_ref))
                .unwrap()
                .into_any()
                .into_bound(py),
            XmlOut::Text(xml_text_ref) => {
                Py::new(py, XmlText::from(xml_text_ref)).unwrap().into_any().into_bound(py)
            }
        }
    }
}

impl<T> ToPython for Option<T>
where
    T: ToPython,
{
    fn into_py<'py>(self, py: Python<'py>) -> Bound<'py, PyAny> {
        self.map(|v| v.into_py(py)).unwrap_or_else(|| py.None().into_bound(py))
    }
}

impl ToPython for &'_ Attrs {
    fn into_py<'py>(self, py: Python<'py>) -> Bound<'py, PyAny> {
        let result = PyDict::new(py);
        for (key, value) in self.iter() {
            let key = key.as_ref();
            let value = Out::Any(value.clone()).into_py(py);
            result.set_item(key, value).unwrap();
        }
        result.into_bound_py_any(py).unwrap()
    }
}

impl ToPython for &Change {
    fn into_py<'py>(self, py: Python<'py>) -> Bound<'py, PyAny> {
        let result = PyDict::new(py);
        match self {
            Change::Added(values) => {
                let values: Vec<Bound<'py, PyAny>> =
                    values.into_iter().map(|v| v.clone().into_py(py)).collect();
                result.set_item("insert", values).unwrap();
            }
            Change::Removed(len) => {
                result.set_item("delete", len).unwrap();
            }
            Change::Retain(len) => {
                result.set_item("retain", len).unwrap();
            }
        }
        result.into_bound_py_any(py).unwrap()
    }
}

#[repr(transparent)]
pub struct EntryChangeWrapper<'a>(pub &'a EntryChange);

impl<'py, 'a> IntoPyObject<'py> for EntryChangeWrapper<'a> {
    type Target = PyDict;
    type Output = Bound<'py, Self::Target>;
    type Error = std::convert::Infallible;

    fn into_pyobject(self, py: Python<'py>) -> Result<Self::Output, Self::Error> {
        let result = PyDict::new(py);
        let action = "action";
        match self.0 {
            EntryChange::Inserted(new) => {
                let new_value = new.clone().into_py(py);
                result.set_item(action, "add").unwrap();
                result.set_item("newValue", new_value).unwrap();
            }
            EntryChange::Updated(old, new) => {
                let old_value = old.clone().into_py(py);
                let new_value = new.clone().into_py(py);
                result.set_item(action, "update").unwrap();
                result.set_item("oldValue", old_value).unwrap();
                result.set_item("newValue", new_value).unwrap();
            }
            EntryChange::Removed(old) => {
                let old_value = old.clone().into_py(py);
                result.set_item(action, "delete").unwrap();
                result.set_item("oldValue", old_value).unwrap();
            }
        }
        Ok(result)
    }
}

impl ToPython for Any {
    fn into_py<'py>(self, py: Python<'py>) -> Bound<'py, PyAny> {
        match self {
            Any::Null | Any::Undefined => py.None().into_bound(py),
            Any::Bool(v) => PyBool::new(py, v).into_bound_py_any(py).unwrap(),
            Any::Number(v) => PyFloat::new(py, v).into_bound_py_any(py).unwrap(),
            Any::BigInt(v) => v.into_pyobject(py).unwrap().into_bound_py_any(py).unwrap(),
            Any::String(v) => v.into_pyobject(py).unwrap().into_bound_py_any(py).unwrap(),
            Any::Buffer(v) => PyByteArray::new(py, v.as_ref()).into_bound_py_any(py).unwrap(),
            Any::Array(v) => {
                let mut a = Vec::new();
                for value in v.iter() {
                    let value = value.to_owned();
                    a.push(value);
                }
                a.into_py(py).into_bound_py_any(py).unwrap()
            }
            Any::Map(v) => {
                let val = PyDict::new(py);
                for (k, v) in v.iter() {
                    let value = v.to_owned();
                    val.set_item(k, value.into_py(py)).unwrap();
                }
                val.into_bound_py_any(py).unwrap()
            }
        }
    }
}

pub fn py_to_any<'py>(value: &Bound<'py, PyAny>) -> Any {
    if value.is_none() {
        Any::Null
    } else if value.is_instance_of::<PyBytes>() {
        let v: &[u8] = value.extract().unwrap();
        Any::Buffer(v.into())
    } else if value.is_instance_of::<PyString>() {
        let v: &str = value.extract().unwrap();
        Any::String(v.into())
    } else if value.is_instance_of::<PyBool>() {
        let v: bool = value.extract().unwrap();
        Any::Bool(v)
    } else if value.is_instance_of::<PyInt>() {
        const MAX_JS_NUMBER: i64 = 2_i64.pow(53) - 1;
        let v: i64 = value.extract().unwrap();
        if v > MAX_JS_NUMBER {
            Any::BigInt(v)
        } else {
            Any::Number(v as f64)
        }
    } else if value.is_instance_of::<PyFloat>() {
        let v: f64 = value.extract().unwrap();
        Any::Number(v)
    } else if let Ok(v) = value.cast::<PyList>() {
        let mut items = Vec::new();
        for i in v.iter() {
            let a = py_to_any(&i);
            items.push(a);
        }
        Any::Array(items.into())
    } else if let Ok(val) = value.cast::<PyDict>() {
        let mut items: HashMap<String, Any> = HashMap::new();
        for (k, v) in val.iter() {
            let k = k.cast::<PyString>().unwrap().to_str().unwrap().to_string();
            let v = py_to_any(&v);
            items.insert(k, v);
        }
        Any::Map(items.into())
    } else {
        Any::Undefined
    }
}

pub(crate) fn events_into_py<'py>(py: Python<'py>, txn: &TransactionMut, events: &Events) -> Bound<'py, PyList> {
    let py_events = events.iter().map(|event| match event {
        yrs::types::Event::Text(e_txt) => Py::new(py, TextEvent::new(e_txt, txn)).unwrap().into_bound_py_any(py).unwrap(),
        yrs::types::Event::Array(e_arr) => Py::new(py, ArrayEvent::new(e_arr, txn)).unwrap().into_bound_py_any(py).unwrap(),
        yrs::types::Event::Map(e_map) => Py::new(py, MapEvent::new(e_map, txn)).unwrap().into_bound_py_any(py).unwrap(),
        yrs::types::Event::XmlFragment(e_xml) => unsafe {
            Py::new(py, XmlEvent::from_xml_event(e_xml, txn, py)).unwrap().into_bound_py_any(py).unwrap()
        },
        yrs::types::Event::XmlText(e_xml) => unsafe {
            Py::new(py, XmlEvent::from_xml_text_event(e_xml, txn, py)).unwrap().into_bound_py_any(py).unwrap()
        },
    });
    PyList::new(py, py_events).unwrap()
}

/// Converts an iterator of k,v tuples to an [`Attrs`] map
pub(crate) fn py_to_attrs<'py>(
    pyobj: Bound<'py, PyIterator>,
) -> PyResult<Attrs> {
    pyobj.map(|res| res.and_then(|item| {
        let key = item.get_item(0)?.extract::<Bound<PyString>>()?;
        let value = item.get_item(1).map(|v| py_to_any(&v))?;
        Ok((Arc::from(key.to_str()?), value))
    })).collect::<PyResult<Attrs>>()
}
