import gc

import pytest


def finalize():
    gc.collect()
    # looks like PyPy needs a second one:
    gc.collect()


@pytest.fixture(scope="function", autouse=True)
def collect_gc(request):
    request.addfinalizer(finalize)


@pytest.fixture(params=("context_manager", "start_stop"))
def service_api(request):
    return request.param
