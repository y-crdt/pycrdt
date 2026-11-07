from __future__ import annotations

import copy
import json
from time import time
from typing import Any, Callable, Literal, cast
from uuid import uuid4

from anyio import TASK_STATUS_IGNORED, create_task_group, sleep
from anyio.abc import TaskGroup, TaskStatus

from ._doc import Doc
from ._sync import Decoder, Encoder, read_message


class Awareness:
    client_id: int
    _meta: dict[int, dict[str, Any]]
    _states: dict[int, dict[str, Any]]
    _subscriptions: dict[str, Callable[[str, tuple[dict[str, Any], Any]], None]]
    _task_group: TaskGroup | None

    def __init__(self, ydoc: Doc, *, outdated_timeout: int = 30000) -> None:
        """
        Args:
            ydoc: The [Doc][pycrdt.Doc] to associate the awareness with.
            outdated_timeout: The timeout (in milliseconds) to consider a client gone.
        """
        self.client_id = ydoc.client_id
        self._outdated_timeout = outdated_timeout
        self._meta = {}
        self._states = {}
        self._subscriptions = {}
        self._task_group = None
        self.set_local_state({})

    @property
    def meta(self) -> dict[int, dict[str, Any]]:
        """The clients' metadata."""
        return self._meta

    @property
    def states(self) -> dict[int, dict[str, Any]]:
        """The client states."""
        return self._states

    def _emit(
        self,
        topic: Literal["change", "update"],
        added: list[int],
        updated: list[int],
        removed: list[int],
        origin: Any,
    ):
        # iterate over a copy, as callbacks may observe or unobserve
        for callback in list(self._subscriptions.values()):
            callback(topic, ({"added": added, "updated": updated, "removed": removed}, origin))

    def _get_time(self) -> int:
        return int(time() * 1000)

    async def start(self, *, task_status: TaskStatus[None] = TASK_STATUS_IGNORED) -> None:
        """
        Starts updating the awareness periodically.
        """
        if self._task_group is not None:
            raise RuntimeError("Awareness already started")

        async with create_task_group() as tg:
            self._task_group = tg
            task_status.started()
            tg.start_soon(self._start)

    async def _start(self) -> None:
        while True:
            await sleep(self._outdated_timeout / 1000 / 10)
            now = self._get_time()
            if (
                self.get_local_state() is not None
                and self._outdated_timeout / 2 <= now - self._meta[self.client_id]["lastUpdated"]
            ):
                # renew local clock
                self.set_local_state(self.get_local_state())
            remove: list[int] = []
            for client_id, meta in self._meta.items():
                if (
                    client_id != self.client_id
                    and self._outdated_timeout <= now - meta["lastUpdated"]
                    and client_id in self._states
                ):
                    remove.append(client_id)
            if remove:
                self.remove_awareness_states(remove, "timeout")

    async def stop(self) -> None:
        """
        Stops updating the awareness periodically.
        """
        if self._task_group is None:
            raise RuntimeError("Awareness not started")
        self._task_group.cancel_scope.cancel()
        self._task_group = None

    def get_local_state(self) -> dict[str, Any] | None:
        """
        Returns:
            The local state, if any.
        """
        return self._states.get(self.client_id)

    def set_local_state(self, state: dict[str, Any] | None) -> None:
        """
        Updates the local state and meta, and sends the changes to subscribers.

        Args:
            state: The new local state, if any.
        """
        client_id = self.client_id
        curr_local_meta = self._meta.get(client_id)
        clock = 0 if curr_local_meta is None else curr_local_meta["clock"] + 1
        prev_state = self._states.get(client_id)
        if prev_state is not None:
            prev_state = copy.deepcopy(prev_state)
        if state is None:
            if client_id in self._states:
                del self._states[client_id]
        else:
            self._states[client_id] = state
        timestamp = self._get_time()
        self._meta[client_id] = {"clock": clock, "lastUpdated": timestamp}
        added = []
        updated = []
        filtered_updated = []
        removed = []
        if state is None:
            removed.append(client_id)
        elif prev_state is None:
            if state is not None:
                added.append(client_id)
        else:
            updated.append(client_id)
            if prev_state != state:
                filtered_updated.append(client_id)
        if added or filtered_updated or removed:
            self._emit("change", added, filtered_updated, removed, "local")
        self._emit("update", added, updated, removed, "local")

    def set_local_state_field(self, field: str, value: Any) -> None:
        """
        Sets a local state field.

        Args:
            field: The field of the local state to set.
            value: The value associated with the field.
        """
        state = self.get_local_state()
        if state is not None:
            state = copy.deepcopy(state)
            state[field] = value
            self.set_local_state(state)

    def remove_awareness_states(self, client_ids: list[int], origin: Any) -> None:
        """
        Removes awareness states for clients given by their IDs.

        Args:
            client_ids: The list of client IDs for which to remove the awareness states.
            origin: The origin of the update.
        """
        removed = []
        for client_id in client_ids:
            if client_id in self._states:
                del self._states[client_id]
                if client_id == self.client_id:
                    cur_meta = self._meta[client_id]
                    self._meta[client_id] = {
                        "clock": cur_meta["clock"] + 1,
                        "lastUpdated": self._get_time(),
                    }
                removed.append(client_id)
        if removed:
            self._emit("change", [], [], removed, origin)
            self._emit("update", [], [], removed, origin)

    def encode_awareness_update(self, client_ids: list[int]) -> bytes:
        """
        Creates an encoded awareness update of the clients given by their IDs.

        Args:
            client_ids: The list of client IDs for which to create an update.

        Returns:
            The encoded awareness update.
        """
        encoder = Encoder()
        encoder.write_var_uint(len(client_ids))
        for client_id in client_ids:
            state = self._states.get(client_id)
            clock = cast(int, self._meta.get(client_id, {}).get("clock"))
            encoder.write_var_uint(client_id)
            encoder.write_var_uint(clock)
            encoder.write_var_string(json.dumps(state, separators=(",", ":")))
        return encoder.to_bytes()

    def apply_awareness_update(self, update: bytes, origin: Any) -> None:
        """
        Applies the binary update and notifies subscribers with changes.

        Args:
            update: The binary update.
            origin: The origin of the update.
        """
        decoder = Decoder(update)
        timestamp = self._get_time()
        added = []
        updated = []
        filtered_updated = []
        removed = []
        length = decoder.read_var_uint()
        for _ in range(length):
            client_id = decoder.read_var_uint()
            clock = decoder.read_var_uint()
            state_str = decoder.read_var_string()
            state = None if not state_str else json.loads(state_str)
            client_meta = self._meta.get(client_id)
            prev_state = self._states.get(client_id)
            curr_clock = 0 if client_meta is None else client_meta["clock"]
            if curr_clock < clock or (
                curr_clock == clock and state is None and client_id in self._states
            ):
                if state is None:
                    # Never let a remote client remove this local state.
                    if client_id == self.client_id and self.get_local_state() is not None:
                        # Remote client removed the local state. Do not remove state.
                        # Broadcast a message indicating that this client still exists by increasing
                        # the clock.
                        clock += 1
                    else:
                        if client_id in self._states:
                            del self._states[client_id]
                else:
                    self._states[client_id] = state
                self._meta[client_id] = {
                    "clock": clock,
                    "lastUpdated": timestamp,
                }
                if client_meta is None and state is not None:
                    added.append(client_id)
                elif client_meta is not None and state is None:
                    removed.append(client_id)
                elif state is not None:
                    if state != prev_state:
                        filtered_updated.append(client_id)
                    updated.append(client_id)
        if added or filtered_updated or removed:
            self._emit("change", added, filtered_updated, removed, origin)
        if added or updated or removed:
            self._emit("update", added, updated, removed, origin)

    def observe(self, callback: Callable[[str, tuple[dict[str, Any], Any]], None]) -> str:
        """
        Registers the given callback to awareness changes.

        Args:
            callback: The callback to call with the awareness changes.

        Returns:
            The subscription ID that can be used to unobserve.
        """
        id = str(uuid4())
        self._subscriptions[id] = callback
        return id

    def unobserve(self, id: str) -> None:
        """
        Unregisters the given subscription ID from awareness changes.

        Args:
            id: The subscription ID to unregister.
        """
        del self._subscriptions[id]


def is_awareness_disconnect_message(message: bytes) -> bool:
    """
    Check if the message is null, which means that it is a disconnection message
    from the client.

    Args:
        message: The message received from the client.

    Returns:
        Whether the message is a disconnection message or not.
    """
    decoder = Decoder(read_message(message))
    length = decoder.read_var_uint()
    # A disconnection message should be a single message
    if length == 1:
        # Remove client_id and clock information from message (not used)
        for _ in range(2):
            decoder.read_var_uint()
        state = decoder.read_var_string()
        if state == "null":
            return True
    return False
