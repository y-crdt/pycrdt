import pytest
from anyio import TASK_STATUS_IGNORED, create_memory_object_stream, create_task_group, sleep
from anyio.abc import TaskStatus
from pycrdt import (
    Array,
    Doc,
    create_sync_message,
    create_update_message,
    handle_sync_message,
)
from pycrdt._sync import Decoder, Encoder, write_var_uint

pytestmark = pytest.mark.anyio


class ConnectedDoc:
    def __init__(self):
        self.doc = Doc()
        self.doc.observe(lambda event: self.send(event.update))
        self.connected_docs = []
        self.send_stream, self.receive_stream = create_memory_object_stream[bytes](
            max_buffer_size=1024
        )

    async def start(self, *, task_status: TaskStatus[None] = TASK_STATUS_IGNORED):
        async with create_task_group() as tg:
            task_status.started()
            tg.start_soon(self.process_received_messages)

    def connect(self, *connected_docs):
        self.connected_docs += connected_docs
        sync_message = create_sync_message(self.doc)
        for connected_doc in connected_docs:
            connected_doc.receive(sync_message, self)

    def receive(self, message: bytes, sender=None):
        self.send_stream.send_nowait((message, sender))

    async def process_received_messages(self):
        async for message, sender in self.receive_stream:
            reply = handle_sync_message(message[1:], self.doc)
            if reply is not None:
                sender.receive(reply, self)

    def send(self, message: bytes):
        for doc in self.connected_docs:
            doc.receive(create_update_message(message))


async def test_sync():
    async with create_task_group() as tg:
        doc0 = ConnectedDoc()
        doc1 = ConnectedDoc()

        await tg.start(doc0.start)
        await tg.start(doc1.start)

        doc0.connect(doc1)
        doc1.connect(doc0)

        array0 = doc0.doc.get("array", type=Array)
        array0.append(0)
        await sleep(0.1)

        array1 = doc1.doc.get("array", type=Array)
        assert array1[0] == 0

        # doc2 only connects to doc0
        # but since doc0 and doc1 are connected,
        # doc2 is indirectly connected to doc1
        doc2 = ConnectedDoc()
        await tg.start(doc2.start)
        doc2.connect(doc0)
        doc0.connect(doc2)
        await sleep(0.1)
        array2 = doc2.doc.get("array", type=Array)
        assert array2[0] == 0
        array2.append(1)
        await sleep(0.1)
        assert array0[1] == 1
        assert array1[1] == 1

        tg.cancel_scope.cancel()


def test_write_var_uint():
    assert write_var_uint(128) == b"\x80\x01"


def test_decoder():
    with pytest.raises(RuntimeError) as exc_info:
        Decoder(b"").read_var_uint()
    assert str(exc_info.value) == "Y protocol error"

    assert list(Decoder(b"").read_messages()) == []
    assert list(Decoder(b"\x00").read_messages()) == [b""]
    assert Decoder(b"").read_var_string() == ""
    assert Decoder(b"\x05Hello").read_var_string() == "Hello"


def test_encoder_var_string_non_ascii():
    text = "héllo 🎉"
    encoder = Encoder()
    encoder.write_var_string(text)
    encoded = encoder.to_bytes()
    # the length prefix is the number of UTF-8 bytes, like lib0's writeVarString
    assert encoded == write_var_uint(len(text.encode())) + text.encode()
    assert Decoder(encoded).read_var_string() == text
