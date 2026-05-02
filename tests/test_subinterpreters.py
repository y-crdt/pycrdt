import pytest

from anyio import to_interpreter

from pycrdt import import_pycrdt

pytestmark = pytest.mark.anyio


async def test_subinterpreter():
    await to_interpreter.run_sync(import_pycrdt)
