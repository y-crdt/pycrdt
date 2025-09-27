from __future__ import annotations

from functools import partial
from types import TracebackType
from typing import TYPE_CHECKING, Any

from anyio import create_task_group, to_thread

from ._pycrdt import Transaction as _Transaction

if TYPE_CHECKING:
    from ._doc import Doc


class Transaction:
    """
    A read-write transaction that can be used to mutate a document.
    It must be used with a context manager (see [Doc.transaction()][pycrdt.Doc.transaction]):
    ```py
    with doc.transaction():
        ...
    ```
    """

    _doc: Doc
    _txn: _Transaction | None
    _leases: int
    _origin_hash: int | None
    _timeout: float

    def __init__(
        self,
        doc: Doc,
        _txn: _Transaction | None = None,
        *,
        origin: Any = None,
        timeout: float | None = None,
    ) -> None:
        self._doc = doc
        self._txn = _txn
        self._leases = 0
        if origin is None:
            self._origin_hash = None
        else:
            self._origin_hash = hash_origin(origin)
            doc._origins[self._origin_hash] = origin
        self._timeout = -1 if timeout is None else timeout

    def __enter__(self, _acquire_transaction: bool = True) -> Transaction:
        self._leases += 1
        if self._txn is None:
            if (
                self._doc._allow_multithreading
                and _acquire_transaction
                and not self._doc._txn_lock.acquire(timeout=self._timeout)
            ):
                raise TimeoutError("Could not acquire transaction")
            if self._origin_hash is not None:
                self._txn = self._doc._doc.create_transaction_with_origin(self._origin_hash)
            else:
                self._txn = self._doc._doc.create_transaction()
        self._doc._txn = self
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        self._leases -= 1
        # only drop the transaction when exiting root context manager
        # since nested transactions reuse the root transaction
        if self._leases == 0:
            assert self._txn is not None
            if not isinstance(self, ReadTransaction):
                self._txn.commit()
                origin_hash = self._txn.origin()
                if origin_hash is not None:
                    del self._doc._origins[origin_hash]
                if self._doc._allow_multithreading:
                    self._doc._txn_lock.release()
            self._txn.drop()
            self._txn = None
            self._doc._txn = None

    async def __aenter__(self, _acquire_transaction: bool = True) -> Transaction:
        if self._leases > 0 and self._doc._task_group is None:
            raise RuntimeError("Already in a non-async transaction")
        self._doc._task_group = await create_task_group().__aenter__()
        return self.__enter__(_acquire_transaction)

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> bool | None:
        self.__exit__(exc_type, exc_val, exc_tb)
        if self._leases == 0:
            assert self._doc._task_group is not None
            res = await self._doc._task_group.__aexit__(exc_type, exc_val, exc_tb)
            self._doc._task_group = None
            return res
        return None

    @property
    def origin(self) -> Any:
        """
        The origin of the transaction.

        Raises:
            RuntimeError: No current transaction.
        """
        if self._txn is None:
            raise RuntimeError("No current transaction")

        origin_hash = self._txn.origin()
        if origin_hash is None:
            return None

        return self._doc._origins[origin_hash]


class NewTransaction(Transaction):
    """
    A read-write transaction that can be used to mutate a document.
    It can be used with a context manager or an async context manager
    (see [Doc.new_transaction()][pycrdt.Doc.new_transaction]):
    ```py
    with doc.new_transaction():
        ...

    async with doc.new_transaction():
        ...
    ```
    """

    async def __aenter__(self) -> Transaction:  # type: ignore[override]
        if self._doc._allow_multithreading:
            if not await to_thread.run_sync(
                partial(self._doc._txn_lock.acquire, timeout=self._timeout), abandon_on_cancel=True
            ):
                raise TimeoutError("Could not acquire transaction")
        else:
            await self._doc._txn_async_lock.acquire()
        return await super().__aenter__(_acquire_transaction=False)

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> bool | None:
        res = await super().__aexit__(exc_type, exc_val, exc_tb)
        if not self._doc._allow_multithreading:
            self._doc._txn_async_lock.release()
        return res


class ReadTransaction(Transaction):
    """
    A read-only transaction that cannot be used to mutate a document.
    """


def hash_origin(origin: Any) -> int:
    try:
        return hash(origin)
    except Exception:
        raise TypeError("Origin must be hashable")
