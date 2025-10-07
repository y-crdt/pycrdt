from datetime import datetime, timezone
from typing import Tuple

import pytest
from pycrdt import Array, Doc, Text
from pydantic import BaseModel, ValidationError


def test_model():
    remote_doc = Doc(
        {
            "timestamp": Text("2020-01-02T03:04:05Z"),
            "dimensions": Array(["10", "20"]),
        }
    )
    update = remote_doc.get_update()

    class Delivery(BaseModel):
        timestamp: datetime
        dimensions: Tuple[int, int]

    local_doc = Doc(
        {
            "timestamp": Text(),
            "dimensions": Array(),
        },
        Model=Delivery,
    )
    local_doc.apply_update(update)

    remote_doc["dimensions"][1] = "a"  # "a" is not an int
    update = remote_doc.get_update()
    with pytest.raises(ValidationError) as exc_info:
        local_doc.apply_update(update)
    assert str(exc_info.value).startswith("1 validation error for Delivery\ndimensions.1\n")

    remote_doc["timestamp"][6] = "0"  # invalid "00" month
    update = remote_doc.get_update()
    with pytest.raises(ValidationError) as exc_info:
        local_doc.apply_update(update)
    assert str(exc_info.value).startswith("2 validation errors for Delivery\n")

    remote_doc["dimensions"][1] = "30"  # revert invalid change, and make a change
    update = remote_doc.get_update()
    with pytest.raises(ValidationError) as exc_info:
        local_doc.apply_update(update)
    assert str(exc_info.value).startswith("1 validation error for Delivery\ntimestamp\n")

    remote_doc["timestamp"][6] = "2"  # revert invalid change, and make a change
    update = remote_doc.get_update()
    local_doc.apply_update(update)

    assert str(local_doc["timestamp"]) == "2020-02-02T03:04:05Z"
    assert list(local_doc["dimensions"]) == ["10", "30"]

    decoded = local_doc.get_model_state()
    assert decoded.timestamp == datetime(2020, 2, 2, 3, 4, 5, tzinfo=timezone.utc)
    assert decoded.dimensions == (
        10,
        30,
    )
