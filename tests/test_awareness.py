import json
from copy import deepcopy
from uuid import uuid4

import pytest
from anyio import create_task_group, sleep
from pycrdt import (
    Awareness,
    Doc,
    Encoder,
    YMessageType,
    create_awareness_message,
    is_awareness_disconnect_message,
    read_message,
    write_message,
)

pytestmark = pytest.mark.anyio

TEST_USER = {"username": str(uuid4()), "name": "Test user"}
REMOTE_CLIENT_ID = 853790970
REMOTE_USER = {
    "user": {
        "username": "2460ab00fd28415b87e49ec5aa2d482d",
        "name": "Anonymous Ersa",
        "display_name": "Anonymous Ersa",
        "initials": "AE",
        "avatar_url": None,
        "color": "var(--jp-collaborator-color7)",
    }
}


def create_awareness_update(client_id, user, clock=1) -> bytes:
    if isinstance(user, str):
        new_user_str = user
    else:
        new_user_str = json.dumps(user, separators=(",", ":"))
    encoder = Encoder()
    encoder.write_var_uint(1)
    encoder.write_var_uint(client_id)
    encoder.write_var_uint(clock)
    encoder.write_var_string(new_user_str)
    return encoder.to_bytes()


def test_awareness_get_local_state():
    ydoc = Doc()
    awareness = Awareness(ydoc)

    assert awareness.get_local_state() == {}


def test_awareness_set_local_state():
    ydoc = Doc()
    awareness = Awareness(ydoc)
    changes = []

    def callback(topic, event):
        changes.append((topic, event))

    awareness.observe(callback)

    awareness.set_local_state({"foo": "bar"})
    assert awareness.get_local_state() == {"foo": "bar"}

    awareness.set_local_state(None)
    assert awareness.get_local_state() is None

    assert changes == [
        ("change", ({"added": [], "updated": [awareness.client_id], "removed": []}, "local")),
        ("update", ({"added": [], "updated": [awareness.client_id], "removed": []}, "local")),
        ("change", ({"added": [], "updated": [], "removed": [awareness.client_id]}, "local")),
        ("update", ({"added": [], "updated": [], "removed": [awareness.client_id]}, "local")),
    ]


def test_awareness_set_local_state_field():
    ydoc = Doc()
    awareness = Awareness(ydoc)

    awareness.set_local_state_field("new_field", "new_value")
    assert awareness.get_local_state() == {"new_field": "new_value"}


def test_awareness_add_user():
    ydoc = Doc()
    awareness = Awareness(ydoc)
    changes = []

    def callback(topic, event):
        changes.append((topic, event))

    awareness.observe(callback)
    awareness.apply_awareness_update(
        create_awareness_update(REMOTE_CLIENT_ID, REMOTE_USER),
        "custom_origin",
    )
    assert len(changes) == 2
    assert changes[0] == (
        "change",
        (
            {
                "added": [REMOTE_CLIENT_ID],
                "updated": [],
                "removed": [],
            },
            "custom_origin",
        ),
    )
    assert changes[1] == (
        "update",
        (
            {
                "added": [REMOTE_CLIENT_ID],
                "updated": [],
                "removed": [],
            },
            "custom_origin",
        ),
    )
    assert awareness.states == {
        REMOTE_CLIENT_ID: REMOTE_USER,
        ydoc.client_id: {},
    }


def test_awareness_update_user():
    ydoc = Doc()
    awareness = Awareness(ydoc)

    # Add a remote user.
    awareness.apply_awareness_update(
        create_awareness_update(REMOTE_CLIENT_ID, REMOTE_USER),
        "custom_origin",
    )

    # Update it.
    remote_user = deepcopy(REMOTE_USER)
    remote_user["user"]["name"] = "New user name"
    changes = []

    def callback(topic, event):
        changes.append((topic, event))

    awareness.observe(callback)
    awareness.apply_awareness_update(
        create_awareness_update(REMOTE_CLIENT_ID, remote_user, 2),
        "custom_origin",
    )

    assert len(changes) == 2
    assert changes[0] == (
        "change",
        (
            {
                "added": [],
                "updated": [REMOTE_CLIENT_ID],
                "removed": [],
            },
            "custom_origin",
        ),
    )
    assert changes[1] == (
        "update",
        (
            {
                "added": [],
                "updated": [REMOTE_CLIENT_ID],
                "removed": [],
            },
            "custom_origin",
        ),
    )
    assert awareness.states == {
        REMOTE_CLIENT_ID: remote_user,
        ydoc.client_id: {},
    }


def test_awareness_remove_user():
    ydoc = Doc()
    awareness = Awareness(ydoc)

    # Add a remote user.
    awareness.apply_awareness_update(
        create_awareness_update(REMOTE_CLIENT_ID, REMOTE_USER),
        "custom_origin",
    )

    # Remove it.
    changes = []

    def callback(topic, event):
        changes.append((topic, event))

    awareness.observe(callback)
    awareness.apply_awareness_update(
        create_awareness_update(REMOTE_CLIENT_ID, "null", 2),
        "custom_origin",
    )

    assert len(changes) == 2
    assert changes[0] == (
        "change",
        (
            {
                "added": [],
                "updated": [],
                "removed": [REMOTE_CLIENT_ID],
            },
            "custom_origin",
        ),
    )
    assert changes[1] == (
        "update",
        (
            {
                "added": [],
                "updated": [],
                "removed": [REMOTE_CLIENT_ID],
            },
            "custom_origin",
        ),
    )
    assert awareness.states == {ydoc.client_id: {}}


def test_awareness_increment_clock():
    ydoc = Doc()
    awareness = Awareness(ydoc)
    changes = []

    def callback(topic, event):
        changes.append((topic, event))

    awareness.observe(callback)
    awareness.apply_awareness_update(
        create_awareness_update(awareness.client_id, "null"),
        "custom_origin",
    )
    assert len(changes) == 2
    assert changes[0] == (
        "change",
        (
            {
                "added": [],
                "updated": [],
                "removed": [awareness.client_id],
            },
            "custom_origin",
        ),
    )
    assert changes[1] == (
        "update",
        (
            {
                "added": [],
                "updated": [],
                "removed": [awareness.client_id],
            },
            "custom_origin",
        ),
    )
    assert awareness.meta.get(awareness.client_id, {}).get("clock") == 2


def test_awareness_observes():
    ydoc = Doc()
    awareness = Awareness(ydoc)

    changes1 = []
    changes2 = []

    def callback1(topic, value):
        changes1.append((topic, value))

    def callback2(topic, value):
        changes2.append((topic, value))

    awareness.observe(callback1)
    sub2 = awareness.observe(callback2)
    awareness.apply_awareness_update(
        create_awareness_update(REMOTE_CLIENT_ID, REMOTE_USER),
        "custom_origin",
    )
    assert len(changes1) == 2
    assert len(changes2) == 2

    changes1.clear()
    changes2.clear()

    awareness.unobserve(sub2)
    awareness.apply_awareness_update(
        create_awareness_update(REMOTE_CLIENT_ID, "null"),
        "custom_origin",
    )
    assert len(changes1) == 2
    assert len(changes2) == 0


def test_awareness_unobserve_in_callback():
    ydoc = Doc()
    awareness = Awareness(ydoc)
    changes1 = []
    changes2 = []

    def callback1(topic, value):
        changes1.append(topic)
        awareness.unobserve(sub1)

    def callback2(topic, value):
        changes2.append(topic)

    sub1 = awareness.observe(callback1)
    awareness.observe(callback2)
    awareness.set_local_state_field("new_field", "new_value")

    assert changes1 == ["change"]
    assert changes2 == ["change", "update"]


def test_awareness_observe_in_callback():
    awareness = Awareness(Doc())
    calls = []
    added = []

    def callback2(topic, value):
        calls.append(("second", topic))

    def callback1(topic, value):
        calls.append(("first", topic))
        if topic == "change" and not added:
            added.append(awareness.observe(callback2))

    awareness.observe(callback1)
    awareness.set_local_state_field("field", "first")
    assert calls == [("first", "change"), ("first", "update"), ("second", "update")]

    calls.clear()
    awareness.set_local_state_field("field", "second")
    assert calls == [
        ("first", "change"),
        ("second", "change"),
        ("first", "update"),
        ("second", "update"),
    ]


def test_awareness_unobserve_another_callback():
    awareness = Awareness(Doc())
    calls = []
    removed = []

    def callback1(topic, value):
        calls.append(("first", topic))
        if topic == "change" and not removed:
            awareness.unobserve(sub2)
            removed.append(True)

    def callback2(topic, value):
        calls.append(("second", topic))

    awareness.observe(callback1)
    sub2 = awareness.observe(callback2)
    awareness.set_local_state_field("field", "first")
    assert calls == [("first", "change"), ("second", "change"), ("first", "update")]

    calls.clear()
    awareness.set_local_state_field("field", "second")
    assert calls == [("first", "change"), ("first", "update")]


def test_awareness_observes_local_change():
    ydoc = Doc()
    awareness = Awareness(ydoc)
    changes = []

    def callback(topic, value):
        changes.append((topic, value))

    awareness.observe(callback)
    awareness.set_local_state_field("new_field", "new_value")
    assert len(changes) == 2
    assert changes[0] == (
        "change",
        (
            {
                "added": [],
                "removed": [],
                "updated": [ydoc.client_id],
            },
            "local",
        ),
    )
    assert changes[1] == (
        "update",
        (
            {
                "added": [],
                "removed": [],
                "updated": [ydoc.client_id],
            },
            "local",
        ),
    )


def test_awareness_encode():
    ydoc = Doc()
    awareness = Awareness(ydoc)
    changes = []

    def callback(topic, value):
        changes.append((topic, value))

    awareness.observe(callback)
    awareness.set_local_state_field("new_field", "new_value")
    awareness_update = awareness.encode_awareness_update(changes[0][1][0]["updated"])
    assert awareness_update == create_awareness_update(
        awareness.client_id, awareness.get_local_state()
    )
    message = create_awareness_message(awareness_update)
    assert message[0] == YMessageType.AWARENESS
    assert read_message(message[1:]) == awareness_update


def test_awareness_encode_wrong_id():
    ydoc = Doc()
    awareness = Awareness(ydoc)
    with pytest.raises(TypeError):
        awareness.encode_awareness_update([10])


async def test_awareness_periodic_updates():
    ydoc = Doc()
    outdated_timeout = 200
    awareness = Awareness(ydoc, outdated_timeout=outdated_timeout)
    remote_client_id = 0
    awareness._meta[remote_client_id] = {"clock": 0, "lastUpdated": 0}
    awareness._states[remote_client_id] = {}
    changes = []

    def callback(topic, value):
        changes.append((topic, value))

    awareness.observe(callback)
    async with create_task_group() as tg:
        await tg.start(awareness.start)
        with pytest.raises(RuntimeError) as excinfo:
            await tg.start(awareness.start)
        assert str(excinfo.value) == "Awareness already started"
        await sleep((outdated_timeout - outdated_timeout / 10) / 1000)
        awareness.remove_awareness_states([awareness.client_id], "local")
        await sleep(outdated_timeout / 1000)
        await awareness.stop()
        with pytest.raises(RuntimeError) as excinfo:
            await awareness.stop()
        assert str(excinfo.value) == "Awareness not started"

    assert len(changes) == 5
    assert changes[0] == (
        "change",
        (
            {
                "added": [],
                "removed": [remote_client_id],
                "updated": [],
            },
            "timeout",
        ),
    )
    assert changes[1] == (
        "update",
        (
            {
                "added": [],
                "removed": [remote_client_id],
                "updated": [],
            },
            "timeout",
        ),
    )
    assert changes[2] == (
        "update",
        (
            {
                "added": [],
                "removed": [],
                "updated": [awareness.client_id],
            },
            "local",
        ),
    )
    assert changes[3] == (
        "change",
        (
            {
                "added": [],
                "removed": [awareness.client_id],
                "updated": [],
            },
            "local",
        ),
    )
    assert changes[4] == (
        "update",
        (
            {
                "added": [],
                "removed": [awareness.client_id],
                "updated": [],
            },
            "local",
        ),
    )


def test_awareness_disconnection():
    # Should return True if it is a disconnection message
    update = write_message(create_awareness_update(REMOTE_CLIENT_ID, "null"))
    assert is_awareness_disconnect_message(update)

    # Should return False if it is not a disconnection message
    update = write_message(create_awareness_update(REMOTE_CLIENT_ID, "{}"))
    assert not is_awareness_disconnect_message(update)
