use crate::thread_affinity::{CallbackLifetime, CallbackPtr, ThreadAffinity};
use pyo3::prelude::*;
use std::sync::{Mutex, MutexGuard, TryLockError};
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
}

impl<'doc> From<TransactionMut<'doc>> for Transaction {
    fn from(txn: TransactionMut<'doc>) -> Self {
        let t: TransactionMut<'static> = unsafe { std::mem::transmute(txn) };
        Transaction {
            inner: Mutex::new(Some(Cell::Owned(t))),
            thread: None,
            lifetime: None,
        }
    }
}

pub struct TransactionGuard<'a> {
    inner: MutexGuard<'a, Option<Cell<TransactionMut<'static>>>>,
    _lease: Option<std::sync::RwLockReadGuard<'a, bool>>,
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

impl Transaction {
    pub fn borrowed(ptr: CallbackPtr<TransactionMut<'static>>) -> Self {
        Self {
            lifetime: Some(ptr.lifetime()),
            inner: Mutex::new(Some(Cell::Borrowed(ptr))),
            thread: Some(ThreadAffinity::new()),
        }
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
        let inner = match self.inner.try_lock() {
            Ok(transaction) => transaction,
            // PyO3 catches Rust panics. Like the previous RefCell, allow cleanup
            // after a panic rather than leaving the document locked forever.
            Err(TryLockError::Poisoned(err)) => err.into_inner(),
            Err(TryLockError::WouldBlock) => {
                return Err(pyo3::exceptions::PyRuntimeError::new_err(
                    "Transaction already borrowed",
                ));
            }
        };
        if inner.is_none() {
            return Err(pyo3::exceptions::PyRuntimeError::new_err(
                "Transaction is no longer valid",
            ));
        }
        Ok(TransactionGuard {
            inner,
            _lease: lease,
        })
    }
}

#[pymethods]
impl Transaction {
    pub fn commit(&mut self, py: Python<'_>) -> PyResult<()> {
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
        let transaction = {
            let mut inner = match self.inner.try_lock() {
                Ok(inner) => inner,
                Err(TryLockError::Poisoned(err)) => err.into_inner(),
                Err(TryLockError::WouldBlock) => {
                    return Err(pyo3::exceptions::PyRuntimeError::new_err(
                        "Transaction already borrowed",
                    ));
                }
            };
            inner.take()
        };
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
