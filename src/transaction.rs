use crate::thread_affinity::{CallbackLifetime, CallbackPtr, ThreadAffinity};
use pyo3::marker::Ungil;
use pyo3::prelude::*;
use std::sync::atomic::{AtomicBool, AtomicUsize, Ordering::SeqCst};
use std::sync::{Condvar, Mutex, MutexGuard, PoisonError, TryLockError};
use yrs::{Origin, TransactionMut};

pub enum Cell<T> {
    Owned(T),
    Borrowed(CallbackPtr<T>),
}

impl<T> AsRef<T> for Cell<T> {
    fn as_ref(&self) -> &T {
        match self {
            Cell::Owned(v) => v,
            // SAFETY: callers access Cell through TransactionGuard, which holds
            // the callback validity lease until all borrowed references are released.
            Cell::Borrowed(v) => unsafe { v.as_ref() },
        }
    }
}

impl<T> AsMut<T> for Cell<T> {
    fn as_mut(&mut self) -> &mut T {
        match self {
            Cell::Owned(v) => v,
            Cell::Borrowed(_) => {
                panic!(
                    "Transactions executed in context of observer callbacks cannot be used to modify document structure"
                )
            }
        }
    }
}

#[pyclass]
pub struct Transaction {
    inner: Mutex<Option<Cell<TransactionMut<'static>>>>,
    // Owning transactions can move between threads under inner's mutex.
    // Only non-owning callback transactions retain creator-thread affinity.
    thread: Option<ThreadAffinity>,
    lifetime: Option<CallbackLifetime>,
    // True while the thread that holds `inner` runs with the GIL released.
    // A second thread that calls into the transaction then waits for the flag
    // to clear, as it waits for the GIL while a call holds the GIL.
    detached: AtomicBool,
    // The number of threads that wait for `detached` to clear, or that have
    // finished the wait and do not hold the GIL yet.
    waiters: AtomicUsize,
    // `wake` tells threads that `detached` or `waiters` changed.
    changed: Mutex<()>,
    wake: Condvar,
}

impl<'doc> From<TransactionMut<'doc>> for Transaction {
    fn from(txn: TransactionMut<'doc>) -> Self {
        let t: TransactionMut<'static> = unsafe { std::mem::transmute(txn) };
        Transaction::new(Cell::Owned(t), None, None)
    }
}

pub struct TransactionGuard<'a> {
    inner: MutexGuard<'a, Option<Cell<TransactionMut<'static>>>>,
    _lease: Option<std::sync::RwLockReadGuard<'a, bool>>,
    txn: &'a Transaction,
}

impl std::ops::Deref for TransactionGuard<'_> {
    type Target = Option<Cell<TransactionMut<'static>>>;
    fn deref(&self) -> &Self::Target {
        &self.inner
    }
}

impl std::ops::DerefMut for TransactionGuard<'_> {
    fn deref_mut(&mut self) -> &mut Self::Target {
        &mut self.inner
    }
}

impl TransactionGuard<'_> {
    /// Run `f` on the transaction, with the GIL released if `detach` is true.
    ///
    /// A thread that calls into the transaction while the GIL is released waits
    /// for `f` to end. This function then releases the GIL until every such
    /// thread has taken it. A waiting thread has entered the transaction in
    /// Python already, and the thread that leaves the transaction last commits
    /// it. Each waiting thread therefore makes its call first, so that the
    /// thread that opened the transaction still commits it.
    pub fn detach_if<T, F>(mut self, py: Python<'_>, detach: bool, f: F) -> T
    where
        F: Ungil + Send + FnOnce(&mut TransactionMut<'static>) -> T,
        T: Ungil + Send,
    {
        let t = self.inner.as_mut().unwrap().as_mut();
        if !detach {
            return f(t);
        }
        struct Attached<'a>(&'a Transaction);
        impl Drop for Attached<'_> {
            fn drop(&mut self) {
                self.0.detached.store(false, SeqCst);
                if self.0.waiters.load(SeqCst) > 0 {
                    let _changed = self.0.changed.lock().unwrap_or_else(PoisonError::into_inner);
                    self.0.wake.notify_all();
                }
            }
        }
        let txn = self.txn;
        txn.detached.store(true, SeqCst);
        // Dropped with the GIL held again, also when `f` panics.
        let attached = Attached(txn);
        let result = py.detach(move || f(t));
        // Unlock the transaction before the waiting threads wake up.
        drop(self);
        drop(attached);
        if txn.waiters.load(SeqCst) > 0 {
            py.detach(|| {
                let mut changed = txn.changed.lock().unwrap_or_else(PoisonError::into_inner);
                while txn.waiters.load(SeqCst) > 0 {
                    changed = txn.wake.wait(changed).unwrap_or_else(PoisonError::into_inner);
                }
            });
        }
        result
    }
}

impl Transaction {
    fn new(
        cell: Cell<TransactionMut<'static>>,
        thread: Option<ThreadAffinity>,
        lifetime: Option<CallbackLifetime>,
    ) -> Self {
        Self {
            inner: Mutex::new(Some(cell)),
            thread,
            lifetime,
            detached: AtomicBool::new(false),
            waiters: AtomicUsize::new(0),
            changed: Mutex::new(()),
            wake: Condvar::new(),
        }
    }

    pub fn borrowed(ptr: CallbackPtr<TransactionMut<'static>>) -> Self {
        let lifetime = ptr.lifetime();
        Self::new(Cell::Borrowed(ptr), Some(ThreadAffinity::new()), Some(lifetime))
    }

    fn lock(&self) -> PyResult<MutexGuard<'_, Option<Cell<TransactionMut<'static>>>>> {
        let mut waited = false;
        let result = loop {
            match self.inner.try_lock() {
                Ok(transaction) => break Ok(transaction),
                // PyO3 catches Rust panics. Like the previous RefCell, allow cleanup
                // after a panic rather than leaving the document locked forever.
                Err(TryLockError::Poisoned(err)) => break Ok(err.into_inner()),
                Err(TryLockError::WouldBlock) if self.detached.load(SeqCst) => {
                    // Another thread is inside a call that released the GIL.
                    // Wait for that call to end, with the GIL released here too.
                    if !waited {
                        waited = true;
                        self.waiters.fetch_add(1, SeqCst);
                    }
                    Python::attach(|py| {
                        py.detach(|| {
                            let mut changed =
                                self.changed.lock().unwrap_or_else(PoisonError::into_inner);
                            while self.detached.load(SeqCst) {
                                changed = self.wake.wait(changed).unwrap_or_else(PoisonError::into_inner);
                            }
                        })
                    });
                }
                // This thread is inside a call on the transaction already, or another
                // thread is and has called back into Python (from `commit`).
                Err(TryLockError::WouldBlock) => {
                    break Err(pyo3::exceptions::PyRuntimeError::new_err(
                        "Transaction already borrowed",
                    ));
                }
            }
        };
        if waited {
            // The thread that made the call waits for this thread to get here.
            self.waiters.fetch_sub(1, SeqCst);
            let _changed = self.changed.lock().unwrap_or_else(PoisonError::into_inner);
            self.wake.notify_all();
        }
        result
    }

    pub fn transaction(&self) -> PyResult<TransactionGuard<'_>> {
        if let Some(thread) = &self.thread {
            thread.check();
        }
        let lease = self
            .lifetime
            .as_ref()
            .map(CallbackLifetime::borrow)
            .transpose()?;
        let inner = self.lock()?;
        if inner.is_none() {
            return Err(pyo3::exceptions::PyRuntimeError::new_err(
                "Transaction is no longer valid",
            ));
        }
        Ok(TransactionGuard {
            inner,
            _lease: lease,
            txn: self,
        })
    }
}

#[pymethods]
impl Transaction {
    pub fn commit(&self, py: Python<'_>) -> PyResult<()> {
        self.transaction()?.as_mut().unwrap().as_mut().commit();
        // Check if any Python exception was raised during commit (e.g., in callbacks)
        if let Some(err) = pyo3::PyErr::take(py) {
            return Err(err);
        }
        Ok(())
    }

    pub fn drop(&self) -> PyResult<()> {
        if let Some(thread) = &self.thread {
            thread.check();
        }
        let transaction = self.lock()?.take();
        drop(transaction);
        Ok(())
    }

    pub fn origin(&self) -> PyResult<Option<i128>> {
        let transaction = self.transaction()?;
        let Some(origin): Option<&Origin> = transaction.as_ref().unwrap().as_ref().origin() else {
            return Ok(None);
        };
        let data = origin.as_ref();
        Ok(if data.len() == std::mem::size_of::<usize>() {
            let mut bytes = [0; 16];
            bytes[16 - data.len()..].copy_from_slice(data);
            Some(i128::from_be_bytes(bytes))
        } else {
            let Ok(data): Result<[u8; 16], _> = data.try_into() else {
                return Ok(None);
            };
            Some(i128::from_be_bytes(data))
        })
    }
}
