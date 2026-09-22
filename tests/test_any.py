import math

import pytest
from pycrdt import Decoder, Encoder, decode_any, encode_any

# (value, decoded value), see the note on `decode_any` about the asymmetries.
ROUND_TRIPS = [
    (None, None),
    (True, True),
    (False, False),
    # JavaScript number semantics: an int up to 2**53 - 1 decodes back as a float.
    (0, 0.0),
    (42, 42.0),
    (-7, -7.0),
    (2**53 - 1, float(2**53 - 1)),
    # Bigger ints are encoded as big integers and stay ints.
    (2**53, 2**53),
    (-(2**53), -(2**53)),
    (2**62, 2**62),
    (2**63 - 1, 2**63 - 1),  # the largest encodable int
    (-(2**63), -(2**63)),  # the smallest encodable int
    (0.5, 0.5),  # exactly representable as a float32
    (3.14, 3.14),  # needs a float64
    ("", ""),
    ("alice", "alice"),
    ("héllo", "héllo"),
    (b"", bytearray(b"")),
    (b"\x00\xff", bytearray(b"\x00\xff")),
    ([], []),
    ([1, "a", None], [1.0, "a", None]),
    ((1, "a"), [1.0, "a"]),  # a tuple decodes back as a list
    ({}, {}),
    ({"a": 1, "b": "c"}, {"a": 1.0, "b": "c"}),
    ({"a": [1, {"b": (True, None)}]}, {"a": [1.0, {"b": [True, None]}]}),
]


@pytest.mark.parametrize("value, decoded", ROUND_TRIPS)
def test_round_trip(value, decoded):
    result = decode_any(encode_any(value))
    assert result == decoded
    assert type(result) is type(decoded)


def test_round_trip_nan():
    assert math.isnan(decode_any(encode_any(float("nan"))))


@pytest.mark.parametrize("value", [float("inf"), float("-inf")])
def test_round_trip_infinity(value):
    assert decode_any(encode_any(value)) == value


@pytest.mark.parametrize(
    "value, data",
    [
        (None, b"\x7e"),
        (True, b"\x78"),
        (False, b"\x79"),
        ("", b"\x77\x00"),
        ("ab", b"\x77\x02ab"),
        (0, b"\x7d\x00"),
        (1, b"\x7d\x01"),
        (b"ab", b"\x74\x02ab"),
        ([], b"\x75\x00"),
        ([None], b"\x75\x01\x7e"),
        ({}, b"\x76\x00"),
        ({"a": True}, b"\x76\x01\x01a\x78"),
    ],
)
def test_lib0_encoding(value, data):
    """The bytes must match what lib0 `encodeAny` produces, or interoperability is broken."""
    assert encode_any(value) == data
    assert decode_any(data) == decode_any(encode_any(value))


def test_negative_zero_loses_its_sign():
    """Negative zero is encoded as an integer, so the sign is not preserved."""
    assert math.copysign(1, decode_any(encode_any(-0.0))) == 1


# Encoded by lib0 `encodeAny`, to check that genuine lib0 payloads can be read. Note that lib0
# writes an integral number above 2**31 - 1 as a float64, where pycrdt writes it as an integer:
# the bytes differ, but each side decodes the other's.
LIB0_ENCODED = [
    (b"\x7e", None),
    (b"\x7f", None),  # `undefined`, which has no Python counterpart
    (b"\x78", True),
    (b"\x79", False),
    (b"\x7d\x2a", 42.0),
    (b"\x7d\x47", -7.0),
    (b"\x7d\x40", 0.0),  # `-0`
    (b"\x7b\x43\x3f\xff\xff\xff\xff\xff\xff", float(2**53 - 1)),
    (b"\x7c\x3f\x00\x00\x00", 0.5),
    (b"\x7b\x40\x09\x1e\xb8\x51\xeb\x85\x1f", 3.14),
    (b"\x77\x06\x68\xc3\xa9\x6c\x6c\x6f", "héllo"),
    (b"\x74\x02\x00\xff", bytearray(b"\x00\xff")),
    (b"\x75\x03\x7d\x01\x77\x01\x61\x7e", [1.0, "a", None]),
    (b"\x76\x02\x01\x61\x7d\x01\x01\x62\x77\x01\x63", {"a": 1.0, "b": "c"}),
    (
        b"\x76\x01\x01\x61\x75\x02\x7d\x01\x76\x01\x01\x62\x75\x02\x78\x7e",
        {"a": [1.0, {"b": [True, None]}]},
    ),
]


@pytest.mark.parametrize("data, value", LIB0_ENCODED)
def test_decode_lib0_encoded(data, value):
    assert decode_any(data) == value


def test_decode_undefined():
    """lib0 has no `undefined` counterpart in Python, so it decodes as `None`, like `null`."""
    assert decode_any(b"\x7f") is None


@pytest.mark.parametrize("value", [object(), b"ab".decode, bytearray(b"ab"), {1, 2}])
def test_encode_unsupported_type(value):
    with pytest.raises(TypeError) as excinfo:
        encode_any(value)
    assert "is not any-serializable" in str(excinfo.value)


def test_encode_unsupported_nested_type():
    with pytest.raises(TypeError) as excinfo:
        encode_any({"a": [1, {"b": object()}]})
    assert "Object of type object is not any-serializable" in str(excinfo.value)


@pytest.mark.parametrize("key", [1, None, (1, 2)])
def test_encode_non_string_key(key):
    with pytest.raises(TypeError) as excinfo:
        encode_any({key: "a"})
    assert "keys must be str, not " in str(excinfo.value)


@pytest.mark.parametrize("value", [2**63, -(2**63) - 1, 2**64, -(2**200)])
def test_encode_int_too_large(value):
    with pytest.raises(OverflowError) as excinfo:
        encode_any(value)
    assert "int is too large to be converted" in str(excinfo.value)


def test_encode_nested_int_too_large():
    with pytest.raises(OverflowError):
        encode_any({"a": [2**64]})


@pytest.mark.parametrize(
    "data",
    [
        b"",  # nothing to read
        b"\x00",  # not an "any" type tag
        b"\x77\x02a",  # truncated string
        b"\x75\x01",  # truncated array
    ],
)
def test_decode_invalid_data(data):
    with pytest.raises(ValueError) as excinfo:
        decode_any(data)
    assert "Cannot decode any value" in str(excinfo.value)


def test_decode_extra_data():
    with pytest.raises(ValueError) as excinfo:
        decode_any(encode_any(None) + b"\x7e")
    assert str(excinfo.value) == "Extra data: 1 bytes read, 2 bytes given"


def test_encoder_decoder():
    encoder = Encoder()
    encoder.write_var_uint(3)
    encoder.write_any({"a": [1, None]})
    encoder.write_var_string("hello")
    encoder.write_any(b"xyz")
    data = encoder.to_bytes()

    decoder = Decoder(data)
    assert decoder.read_var_uint() == 3
    assert decoder.read_any() == {"a": [1.0, None]}
    assert decoder.read_var_string() == "hello"
    assert decoder.read_any() == bytearray(b"xyz")
    assert decoder.length == 0
    assert decoder.read_message() is None


def test_encoder_any_is_not_length_prefixed():
    """lib0 "any" values are self-delimiting, unlike var strings."""
    encoder = Encoder()
    encoder.write_any("ab")
    assert encoder.to_bytes() == encode_any("ab")
