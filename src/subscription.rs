use pyo3::prelude::*;
use std::cell::RefCell;
use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::{Arc, Mutex};

static NEXT_KEY: AtomicU64 = AtomicU64::new(0);

/// The observer owns this state, so a subscription can detect when its target was destroyed.
pub struct Callback {
    pub key: u64,
    callback: Arc<Mutex<Option<Py<PyAny>>>>,
}

impl Callback {
    pub fn get(&self, py: Python<'_>) -> Option<Py<PyAny>> {
        // Release the lock before calling Python: a callback may unsubscribe itself.
        self.callback
            .lock()
            .unwrap()
            .as_ref()
            .map(|f| f.clone_ref(py))
    }
}

#[pyclass(unsendable)]
pub struct Subscription(RefCell<Option<Box<dyn FnOnce()>>>);

impl Subscription {
    pub fn new(f: Py<PyAny>, unobserve: impl FnOnce(u64) + 'static) -> (Self, Callback) {
        let key = NEXT_KEY.fetch_add(1, Ordering::Relaxed);
        let callback = Arc::new(Mutex::new(Some(f)));
        let weak = Arc::downgrade(&callback);
        let sub = Self(RefCell::new(Some(Box::new(move || {
            if let Some(callback) = weak.upgrade() {
                let f = callback.lock().unwrap().take();
                // The target may contain non-owning Yrs references. Only use them while
                // its observer still exists (and therefore still owns the callback state).
                unobserve(key);
                drop(f);
            }
        }))));
        (sub, Callback { key, callback })
    }
}

impl Drop for Subscription {
    fn drop(&mut self) {
        Subscription::drop(self);
    }
}

#[pymethods]
impl Subscription {
    pub fn drop(&self) {
        let unobserve = self.0.borrow_mut().take();
        if let Some(unobserve) = unobserve {
            unobserve();
        }
    }
}
