from __future__ import annotations

from typing import Any

from ._pycrdt import decode_any as _decode_any
from ._pycrdt import encode_any as _encode_any


def encode_any(value: Any) -> bytes:
    """
    Encodes a value using the [lib0](https://github.com/dmonad/lib0) "any" binary format, the
    format used to exchange arbitrary values with other Y implementations.

    The supported types mirror JSON, plus `bytes`: `None`, `bool`, `int`, `float`, `str`, `bytes`,
    `list`, `tuple` and `dict` (with `str` keys). Containers may be nested.

    Values follow JavaScript number semantics, so an `int` whose absolute value is at most
    2**53 - 1 is encoded as a floating-point number and decodes back as a `float`. Larger
    integers are encoded as big integers and decode back as an `int`.

    Args:
        value: The value to encode.

    Returns:
        The encoded value.

    Raises:
        TypeError: If the value, or a value nested in it, cannot be encoded, or if a `dict` has
            a key that is not a `str`.
        OverflowError: If an `int` doesn't fit in 64 bits, which is the widest integer the
            format can hold.
    """
    return _encode_any(value)


def decode_any(data: bytes) -> Any:
    """
    Decodes a value from the [lib0](https://github.com/dmonad/lib0) "any" binary format, the
    format used to exchange arbitrary values with other Y implementations.

    The whole input must be a single encoded value; use [Decoder.read_any][pycrdt.Decoder.read_any]
    to read a value that is embedded in a larger byte stream.

    Note that decoding is not the exact inverse of [encode_any][pycrdt.encode_any]: a `bytes` value
    decodes back as a `bytearray`, a `tuple` decodes back as a `list`, and a small `int` decodes
    back as a `float` (see [encode_any][pycrdt.encode_any]). A JavaScript `undefined` decodes as
    `None`, like `null`.

    Args:
        data: The encoded value.

    Returns:
        The decoded value.

    Raises:
        ValueError: If the data is not a valid encoded value, or if it holds more than one value.
    """
    value, offset = _decode_any(data, 0)
    if offset != len(data):
        raise ValueError(f"Extra data: {offset} bytes read, {len(data)} bytes given")
    return value
