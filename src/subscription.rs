use pyo3::prelude::*;
use pyo3::{PyTraverseError, PyVisit};
use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::{Arc, Mutex, Weak};

// Keys wrap after 2^64 registrations, potentially colliding with a still-active
// subscription on the same observer. Reaching that limit is impractical.
pub(crate) static NEXT_KEY: AtomicU64 = AtomicU64::new(0);

/// The observer owns only a lifetime token, not the Python callback.
pub struct Callback {
    pub key: u64,
    callback: Weak<Mutex<Option<Py<PyAny>>>>,
    alive: Option<Arc<()>>,
}

impl Callback {
    pub fn get(&self, py: Python<'_>) -> Option<Py<PyAny>> {
        // Release the lock before calling Python: a callback may unsubscribe itself.
        self.callback
            .upgrade()?
            .lock()
            .unwrap()
            .as_ref()
            .map(|f| f.clone_ref(py))
    }
}

impl Drop for Callback {
    fn drop(&mut self) {
        // Invalidate before releasing Python references: their destructors may
        // dispose of this subscription while the target is being destroyed.
        self.alive.take();
        // Destroying the target must release its callback even if Python retains
        // the subscription. Drop Python references after releasing the mutex.
        if let Some(callback) = self.callback.upgrade() {
            let f = callback.lock().unwrap().take();
            drop(f);
        }
    }
}

#[pyclass]
pub struct Subscription {
    // This is the sole strong owner of the callback state. Expose its Python
    // reference to GC so callbacks that retain their document can be collected.
    callback: Arc<Mutex<Option<Py<PyAny>>>>,
    unobserve: Mutex<Option<Box<dyn FnOnce() + Send>>>,
}

impl Subscription {
    pub fn new(f: Py<PyAny>, unobserve: impl FnOnce(u64) + Send + 'static) -> (Self, Callback) {
        let key = NEXT_KEY.fetch_add(1, Ordering::Relaxed);
        let callback = Arc::new(Mutex::new(Some(f)));
        let weak = Arc::downgrade(&callback);
        let alive = Arc::new(());
        let target_alive = Arc::downgrade(&alive);
        let sub = Self {
            callback,
            unobserve: Mutex::new(Some(Box::new(move || {
                if let Some(_alive) = target_alive.upgrade() {
                    // The target may contain non-owning Yrs references. Only use them while
                    // its observer still exists.
                    unobserve(key);
                }
            }))),
        };
        (
            sub,
            Callback {
                key,
                callback: weak,
                alive: Some(alive),
            },
        )
    }

    fn unsubscribe(&self) {
        let f = self.callback.lock().unwrap().take();
        let unobserve = self.unobserve.lock().unwrap().take();
        if let Some(unobserve) = unobserve {
            unobserve();
        }
        drop(f);
    }
}

impl Drop for Subscription {
    fn drop(&mut self) {
        self.unsubscribe();
    }
}

#[pymethods]
impl Subscription {
    fn __traverse__(&self, visit: PyVisit<'_>) -> Result<(), PyTraverseError> {
        if let Some(f) = self.callback.lock().unwrap().as_ref() {
            visit.call(f)?;
        }
        Ok(())
    }

    fn __clear__(&self) {
        self.unsubscribe();
    }

    pub fn drop(&self) {
        self.unsubscribe();
    }
}
