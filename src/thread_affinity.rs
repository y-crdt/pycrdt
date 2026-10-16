use std::thread::{self, ThreadId};

/// Restrict use to the creating thread without restricting destruction.
/// Unlike PyO3's `unsendable`, this does not suppress Rust destructors.
pub struct ThreadAffinity(ThreadId);

impl ThreadAffinity {
    pub fn new() -> Self {
        Self(thread::current().id())
    }

    pub fn check(&self) {
        assert_eq!(
            self.0,
            thread::current().id(),
            "Object accessed from a different thread"
        );
    }
}

/// The lifetime of one observer invocation, shared by all its borrowed views.
#[derive(Clone)]
pub struct CallbackLifetime(std::sync::Arc<std::sync::RwLock<bool>>);

impl CallbackLifetime {
    pub fn borrow(&self) -> pyo3::PyResult<std::sync::RwLockReadGuard<'_, bool>> {
        let valid = self.0.read().unwrap_or_else(|err| err.into_inner());
        if !*valid {
            return Err(pyo3::exceptions::PyRuntimeError::new_err(
                "Observer callback has finished; borrowed event or transaction is no longer valid",
            ));
        }
        Ok(valid)
    }
}

/// Stack-owned guard: invalidate even if Python raises or Rust unwinds.
/// It cannot move to another thread: pointer access remains on the callback's
/// thread, so invalidation cannot interrupt a reentrant read on that thread.
pub struct CallbackScope {
    lifetime: CallbackLifetime,
    _not_send: std::marker::PhantomData<std::rc::Rc<()>>,
}

impl CallbackScope {
    pub fn new() -> Self {
        Self {
            lifetime: CallbackLifetime(std::sync::Arc::new(std::sync::RwLock::new(true))),
            _not_send: std::marker::PhantomData,
        }
    }

    pub fn lifetime(&self) -> CallbackLifetime {
        self.lifetime.clone()
    }
}

impl Drop for CallbackScope {
    fn drop(&mut self) {
        *self
            .lifetime
            .0
            .write()
            .unwrap_or_else(|err| err.into_inner()) = false;
    }
}

/// Non-owning pointer into a callback. Every dereference holds a read lease;
/// callback exit takes the write lock before invalidating the entire scope.
pub struct CallbackPtr<T> {
    ptr: *const T,
    thread: ThreadAffinity,
    lifetime: CallbackLifetime,
}

// SAFETY: destruction never accesses T. Access checks the creating thread and
// holds a validity lease until the returned reference is released. There is no
// safe way to access T from another thread or after the callback has returned.
unsafe impl<T> Send for CallbackPtr<T> {}
unsafe impl<T> Sync for CallbackPtr<T> {}

impl<T> Clone for CallbackPtr<T> {
    fn clone(&self) -> Self {
        Self {
            ptr: self.ptr,
            thread: ThreadAffinity(self.thread.0),
            lifetime: self.lifetime.clone(),
        }
    }
}

impl<T> CallbackPtr<T> {
    /// # Safety
    /// The pointee must remain valid for the whole CallbackScope and permit
    /// shared access during the callback.
    pub unsafe fn new(ptr: *const T, lifetime: CallbackLifetime) -> Self {
        Self {
            ptr,
            thread: ThreadAffinity::new(),
            lifetime,
        }
    }

    pub fn lifetime(&self) -> CallbackLifetime {
        self.lifetime.clone()
    }

    pub fn borrow(&self) -> pyo3::PyResult<CallbackRef<'_, T>> {
        let lease = self.lifetime.borrow()?;
        self.thread.check();
        Ok(CallbackRef {
            ptr: self.ptr,
            _lease: lease,
        })
    }

    /// # Safety
    /// The caller must hold a validity lease for this pointer's lifetime.
    pub unsafe fn as_ref(&self) -> &T {
        self.thread.check();
        unsafe { &*self.ptr }
    }
}

pub struct CallbackRef<'a, T> {
    ptr: *const T,
    _lease: std::sync::RwLockReadGuard<'a, bool>,
}

impl<T> std::ops::Deref for CallbackRef<'_, T> {
    type Target = T;

    fn deref(&self) -> &T {
        // SAFETY: construction checked affinity and validity, and _lease
        // prevents invalidation until this reference is released.
        unsafe { &*self.ptr }
    }
}

#[cfg(test)]
mod tests {
    use super::CallbackScope;
    use std::sync::mpsc;
    use std::time::Duration;

    #[test]
    fn unwind_invalidates_all_views() {
        let scope = CallbackScope::new();
        let lifetime = scope.lifetime();
        let sibling = lifetime.clone();
        assert!(*lifetime.0.read().unwrap());
        let result = std::panic::catch_unwind(move || {
            let _scope = scope;
            panic!("observer unwound");
        });
        assert!(result.is_err());
        assert!(!*lifetime.0.read().unwrap());
        assert!(!*sibling.0.read().unwrap());
    }

    #[test]
    fn invalidation_waits_for_active_access() {
        let (lifetime_tx, lifetime_rx) = mpsc::channel();
        let (exit_tx, exit_rx) = mpsc::channel();
        let (done_tx, done_rx) = mpsc::channel();
        let worker = std::thread::spawn(move || {
            let scope = CallbackScope::new();
            lifetime_tx.send(scope.lifetime()).unwrap();
            exit_rx.recv().unwrap();
            drop(scope);
            done_tx.send(()).unwrap();
        });
        let lifetime = lifetime_rx.recv().unwrap();
        let lease = lifetime.borrow().unwrap();
        exit_tx.send(()).unwrap();
        assert!(matches!(
            done_rx.recv_timeout(Duration::from_millis(50)),
            Err(mpsc::RecvTimeoutError::Timeout)
        ));
        drop(lease);
        done_rx.recv_timeout(Duration::from_secs(5)).unwrap();
        worker.join().unwrap();
        assert!(!*lifetime.0.read().unwrap());
    }
}
