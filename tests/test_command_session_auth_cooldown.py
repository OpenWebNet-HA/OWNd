"""``send()`` does not log in again right after the gateway refused the password.

Every ``send()`` on a session without streams reconnects, with a 2 s cooldown
after a failure. For a refused login that meant three refused logins in 4.4 s
from a caller that kept sending, and two per ``send_to_gateway()`` call. The
HMAC document: "Every time 3 handshakes procedures fail within 60 seconds, the
authentication service have to be disabled for 60 seconds" (Hmac Specification
1.1, "Simple Authentication Mode (SAM)"). The event session already waits
``RECONNECT_PAUSE_FATAL`` (60 s) before it logs in again.
"""
from __future__ import annotations

import asyncio
import logging
import socket
import traceback
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from OWNd.connection import (
    MAX_CONNECT_ATTEMPTS,
    RECONNECT_PAUSE_FATAL,
    SEND_AUTH_COOLDOWN,
    SEND_RECONNECT_COOLDOWN,
    OWNAuthError,
    OWNCommandSession,
    OWNConnectionError,
    OWNGateway,
    OWNProtocolError,
)

MODULE = "OWNd.connection.command_session"
OPEN = "OWNd.connection.session.asyncio.open_connection"

# Bytes a stand-in peer writes on a real socket pair (not a gateway capture): the
# legacy exchange of ``tests/test_connection_extended.py``
# (``test_negotiate_nonce_numeric_password_success`` / ``..._nack``) and the
# model reply of ``tests/test_f461_live_plant.py`` (``GATEWAY_FRAMES``).
ACK = b"*#*1##"
NACK = b"*#*0##"
NONCE = b"*#123456789##"
MODEL_REPLY = b"*#13**15*200##"
LOGIN_REFUSED = ACK + NONCE + NACK
LOGIN_ACCEPTED_THEN_REPLY = ACK + NONCE + ACK + MODEL_REPLY + ACK


def make_session() -> OWNCommandSession:
    gateway = OWNGateway(
        {"address": "192.0.2.1", "port": 20000, "password": "madeup1", "modelName": "F461"}
    )
    session = OWNCommandSession(gateway=gateway)
    session._logger = MagicMock()
    return session


def refuse_logins(reason: str = "password_error") -> tuple[AsyncMock, AsyncMock]:
    """Patch the socket and the negotiation: TCP opens, the login is refused."""
    writer = MagicMock()
    writer.wait_closed = AsyncMock()
    open_connection = AsyncMock(return_value=(MagicMock(), writer))
    negotiate = AsyncMock(return_value={"Success": False, "Message": reason})
    return open_connection, negotiate


def test_auth_cooldown_is_the_event_session_pause() -> None:
    assert SEND_AUTH_COOLDOWN == RECONNECT_PAUSE_FATAL == 60
    assert SEND_AUTH_COOLDOWN > SEND_RECONNECT_COOLDOWN


@pytest.mark.asyncio
@pytest.mark.parametrize("reason", ["password_error", "password_required"])
async def test_repeated_sends_log_in_once(reason: str) -> None:
    session = make_session()
    open_connection, negotiate = refuse_logins(reason)
    clock = [1000.0]

    with (
        patch("OWNd.connection.session.asyncio.open_connection", new=open_connection),
        patch.object(session, "_negotiate", new=negotiate),
        patch(f"{MODULE}.time.monotonic", side_effect=lambda: clock[0]),
    ):
        for _ in range(6):
            assert await session.send("*#13**15##", is_status_request=True) is None
            # The refused login is what every caller is told, not
            # "connection_unavailable" on every other call.
            assert isinstance(session.last_error, OWNAuthError)
            assert session.last_error.reason == reason
            clock[0] += 1.1
        assert negotiate.await_count == 1

        # Still inside the 60 s: nothing.
        clock[0] = 1000.0 + SEND_AUTH_COOLDOWN - 0.5
        assert await session.send("*#13**15##", is_status_request=True) is None
        assert negotiate.await_count == 1

        # Past it: one new attempt, and the cooldown starts again.
        clock[0] = 1000.0 + SEND_AUTH_COOLDOWN + 0.5
        assert await session.send("*#13**15##", is_status_request=True) is None
        assert negotiate.await_count == 2
        clock[0] += 3.0
        assert await session.send("*#13**15##", is_status_request=True) is None
        assert negotiate.await_count == 2

    held = [
        call
        for call in session._logger.warning.call_args_list
        if call.args[0].startswith("%s Authentication handshake failed")
    ]
    assert len(held) == 7
    assert held[0].args[2:4] == (reason, "*#13**15##")


@pytest.mark.asyncio
async def test_cooldown_raises_the_auth_error_when_asked() -> None:
    session = make_session()
    open_connection, negotiate = refuse_logins()

    with (
        patch("OWNd.connection.session.asyncio.open_connection", new=open_connection),
        patch.object(session, "_negotiate", new=negotiate),
    ):
        with pytest.raises(OWNAuthError):
            await session.send("*1*1*11##", raise_on_error=True)
        with pytest.raises(OWNAuthError) as held:
            await session.send("*1*1*11##", raise_on_error=True)
    assert held.value.reason == "password_error"
    assert negotiate.await_count == 1


@pytest.mark.asyncio
async def test_explicit_connect_tries_at_once_and_a_good_login_ends_the_cooldown() -> None:
    session = make_session()
    open_connection, negotiate = refuse_logins()

    with (
        patch("OWNd.connection.session.asyncio.open_connection", new=open_connection),
        patch.object(session, "_negotiate", new=negotiate),
    ):
        assert await session.send("*1*1*11##") is None
        assert negotiate.await_count == 1

        # The caller's own connect() is not held back (a corrected password).
        result = await session.connect()
        assert result == {"Success": False, "Message": "password_error"}
        assert negotiate.await_count == 2

        negotiate.return_value = {"Success": True, "Message": None}
        result = await session.connect()
        assert result == {"Success": True, "Message": None}
        assert session._refused_login_reason is None
        assert session._last_reconnect_failure is None


@pytest.mark.asyncio
async def test_explicit_connect_that_raises_starts_the_cooldown_too() -> None:
    session = make_session()
    open_connection, negotiate = refuse_logins()

    with (
        patch("OWNd.connection.session.asyncio.open_connection", new=open_connection),
        patch.object(session, "_negotiate", new=negotiate),
    ):
        with pytest.raises(OWNAuthError):
            await session.connect(raise_on_error=True)
        assert await session.send("*1*1*11##") is None
    assert negotiate.await_count == 1
    assert isinstance(session.last_error, OWNAuthError)


@pytest.mark.asyncio
async def test_send_to_gateway_logs_in_once() -> None:
    """connect() then send(): the send used to log in a second time."""
    gateway = OWNGateway(
        {"address": "192.0.2.1", "port": 20000, "password": "madeup1", "modelName": "F461"}
    )
    open_connection, negotiate = refuse_logins()

    with (
        patch("OWNd.connection.session.asyncio.open_connection", new=open_connection),
        patch.object(OWNCommandSession, "_negotiate", new=negotiate),
    ):
        assert await OWNCommandSession.send_to_gateway("*#13**15##", gateway) is None

    assert negotiate.await_count == 1
    assert open_connection.await_count == 1


@pytest.mark.asyncio
async def test_failed_hmac_check_is_held_like_a_refused_password() -> None:
    session = make_session()
    open_connection, negotiate = refuse_logins("negotiation_error")

    with (
        patch("OWNd.connection.session.asyncio.open_connection", new=open_connection),
        patch.object(session, "_negotiate", new=negotiate),
    ):
        assert await session.send("*1*1*11##") is None
        assert await session.send("*1*1*11##") is None
    assert negotiate.await_count == 1
    assert isinstance(session.last_error, OWNProtocolError)
    assert session.last_error.reason == "negotiation_error"


@pytest.mark.asyncio
async def test_unreachable_gateway_keeps_the_short_cooldown() -> None:
    """Not a login problem: 2 s, and ``connection_unavailable`` in between, as before."""
    session = make_session()
    clock = [1000.0]

    with (
        patch(
            "OWNd.connection.session.asyncio.open_connection",
            new=AsyncMock(side_effect=ConnectionRefusedError),
        ) as open_connection,
        patch(f"{MODULE}.time.monotonic", side_effect=lambda: clock[0]),
    ):
        assert await session.send("*1*1*11##") is None
        assert session._refused_login_reason is None
        clock[0] += 1.0
        assert await session.send("*1*1*11##") is None
        assert isinstance(session.last_error, OWNConnectionError)
        assert session.last_error.reason == "connection_unavailable"
        assert open_connection.await_count == 1
        clock[0] += SEND_RECONNECT_COOLDOWN
        assert await session.send("*1*1*11##") is None
        assert open_connection.await_count == 2


# --- The held error, what ends the hold, and the one-shot helper (review of OWNd#185) ---


@pytest.mark.asyncio
async def test_each_held_send_raises_its_own_exception() -> None:
    """One cached exception raised again grew its traceback with every caller."""
    session = make_session()
    open_connection, negotiate = refuse_logins()
    caught: list[OWNAuthError] = []
    depth_at_first_raise = 0

    with patch(OPEN, new=open_connection), patch.object(session, "_negotiate", new=negotiate):
        for _ in range(4):
            with pytest.raises(OWNAuthError) as raised:
                await session.send("*#13**15##", is_status_request=True, raise_on_error=True)
            assert raised.value.reason == "password_error"
            caught.append(raised.value)
            if len(caught) == 1:
                depth_at_first_raise = len(traceback.extract_tb(raised.value.__traceback__))

    assert negotiate.await_count == 1
    assert len({id(error) for error in caught}) == 4
    assert session.last_error is caught[-1]
    assert len(traceback.extract_tb(caught[0].__traceback__)) == depth_at_first_raise


@pytest.mark.asyncio
@pytest.mark.parametrize("reason", ["password_error", "password_required"])
@pytest.mark.parametrize("change", ["password", "gateway", "nothing"])
async def test_a_changed_password_or_gateway_ends_the_hold(reason: str, change: str) -> None:
    session = make_session()
    open_connection, negotiate = refuse_logins(reason)
    clock = [1000.0]

    with (
        patch(OPEN, new=open_connection),
        patch.object(session, "_negotiate", new=negotiate),
        patch(f"{MODULE}.time.monotonic", side_effect=lambda: clock[0]),
    ):
        assert await session.send("*#13**15##", is_status_request=True) is None
        assert negotiate.await_count == 1

        if change == "password":
            assert session.gateway is not None
            session.gateway.password = "madeup2"
        elif change == "gateway":
            session.gateway = OWNGateway(
                {"address": "192.0.2.2", "port": 20000, "password": "madeup1", "modelName": "F461"}
            )
        clock[0] += 1.0
        assert await session.send("*#13**15##", is_status_request=True) is None

    assert negotiate.await_count == (1 if change == "nothing" else 2)
    assert isinstance(session.last_error, OWNAuthError)
    assert session.last_error.reason == reason


@pytest.mark.asyncio
async def test_on_auth_error_is_called_by_the_refused_login_only() -> None:
    callback = MagicMock()
    gateway = OWNGateway(
        {"address": "192.0.2.1", "port": 20000, "password": "madeup1", "modelName": "F461"}
    )
    session = OWNCommandSession(gateway=gateway, logger=MagicMock(), on_auth_error=callback)
    open_connection, negotiate = refuse_logins()

    with patch(OPEN, new=open_connection), patch.object(session, "_negotiate", new=negotiate):
        for _ in range(6):
            assert await session.send("*#13**15##", is_status_request=True) is None

    assert negotiate.await_count == 1
    callback.assert_called_once()


@pytest.mark.asyncio
async def test_send_to_gateway_does_not_send_after_a_refused_login(
    caplog: pytest.LogCaptureFixture,
) -> None:
    gateway = OWNGateway(
        {"address": "192.0.2.1", "port": 20000, "password": "madeup1", "modelName": "F461"}
    )
    open_connection, negotiate = refuse_logins()

    with (
        caplog.at_level(logging.DEBUG, logger="OWNd"),
        patch(OPEN, new=open_connection),
        patch.object(OWNCommandSession, "_negotiate", new=negotiate),
        patch.object(
            OWNCommandSession, "send", autospec=True, side_effect=OWNCommandSession.send
        ) as send,
    ):
        assert await OWNCommandSession.send_to_gateway("*#13**15##", gateway) is None

    assert negotiate.await_count == 1
    send.assert_not_called()
    assert not [
        record for record in caplog.records if "next login attempt" in record.getMessage()
    ]


@pytest.mark.asyncio
async def test_send_to_gateway_stops_after_the_connect_attempts() -> None:
    """``send()`` after the failed ``connect()`` was a sixth attempt."""
    gateway = OWNGateway(
        {"address": "192.0.2.1", "port": 20000, "password": "madeup1", "modelName": "F461"}
    )
    open_connection = AsyncMock(side_effect=ConnectionRefusedError)

    with (
        patch(OPEN, new=open_connection),
        patch("OWNd.connection.session.asyncio.sleep", new=AsyncMock()),
    ):
        assert await OWNCommandSession.send_to_gateway("*#13**15##", gateway) is None

    assert open_connection.await_count == MAX_CONNECT_ATTEMPTS == 5


@pytest.mark.asyncio
async def test_send_to_gateway_still_raises_the_refusal_when_asked() -> None:
    gateway = OWNGateway(
        {"address": "192.0.2.1", "port": 20000, "password": "madeup1", "modelName": "F461"}
    )
    open_connection, negotiate = refuse_logins()

    with (
        patch(OPEN, new=open_connection),
        patch.object(OWNCommandSession, "_negotiate", new=negotiate),
        pytest.raises(OWNAuthError) as raised,
    ):
        await OWNCommandSession.send_to_gateway("*#13**15##", gateway, raise_on_error=True)

    assert raised.value.reason == "password_error"
    assert negotiate.await_count == 1


# --- The hold and a caller that acts from ``on_auth_error`` (real socket pairs) ---

Streams = tuple[asyncio.StreamReader, asyncio.StreamWriter, socket.socket]


@asynccontextmanager
async def stream_pair() -> AsyncIterator[Streams]:
    """asyncio streams on one end of a socket pair; the test writes the gateway's side."""
    local, peer = socket.socketpair()
    with peer:
        try:
            reader, writer = await asyncio.open_connection(sock=local)
        except BaseException:
            local.close()
            raise
        try:
            yield reader, writer, peer
        finally:
            writer.close()
            await writer.wait_closed()


def numeric_session() -> OWNCommandSession:
    """A session whose password the legacy (nonce) exchange can use."""
    session = make_session()
    assert session.gateway is not None
    session.gateway.password = "12345"
    return session


@pytest.mark.asyncio
async def test_a_password_corrected_in_the_callback_is_tried_at_once() -> None:
    """The hold names the password that was refused, not the one the callback installed."""
    session = numeric_session()
    gateway = session.gateway
    assert gateway is not None
    session.on_auth_error = lambda _error: setattr(gateway, "password", "67890")

    async with stream_pair() as first, stream_pair() as second:
        first[2].sendall(LOGIN_REFUSED)
        second[2].sendall(LOGIN_ACCEPTED_THEN_REPLY)
        open_connection = AsyncMock(side_effect=[first[:2], second[:2]])
        with patch(OPEN, new=open_connection):
            assert await session.send("*#13**15##", is_status_request=True) is None
            assert gateway.password == "67890"
            result = await session.send("*#13**15##", is_status_request=True)

    assert open_connection.await_count == 2
    assert isinstance(result, list)
    assert [str(message) for message in result] == [MODEL_REPLY.decode()]


@pytest.mark.asyncio
async def test_a_send_started_by_the_callback_finds_the_hold() -> None:
    """The hold exists before ``connect()`` awaits the close of the refused socket."""
    session = numeric_session()
    started: list[asyncio.Task[object]] = []

    def on_auth_error(_error: OWNAuthError) -> None:
        if not started:
            started.append(asyncio.create_task(session.send("*#13**15##")))

    session.on_auth_error = on_auth_error

    async with stream_pair() as first, stream_pair() as second:
        for pair in (first, second):
            pair[2].sendall(LOGIN_REFUSED)
        open_connection = AsyncMock(side_effect=[first[:2], second[:2]])
        with patch(OPEN, new=open_connection):
            result = await session.connect()
            assert result is not None
            assert result["Message"] == "password_error"
            assert await started[0] is None

    assert open_connection.await_count == 1


@pytest.mark.asyncio
async def test_a_password_restored_after_password_required_is_tried_at_once() -> None:
    """The password was missing while the socket opened: the restored one was never refused."""
    session = numeric_session()
    gateway = session.gateway
    assert gateway is not None

    async with stream_pair() as first, stream_pair() as second:
        opening = asyncio.Event()
        go_on = asyncio.Event()

        async def open_connection(*_args: object) -> tuple[asyncio.StreamReader, asyncio.StreamWriter]:
            if not opening.is_set():
                opening.set()
                await go_on.wait()
                return first[:2]
            return second[:2]

        first[2].sendall(ACK + NONCE)
        second[2].sendall(LOGIN_ACCEPTED_THEN_REPLY)
        with patch(OPEN, new=AsyncMock(side_effect=open_connection)) as opened:
            connecting = asyncio.create_task(session.connect())
            await asyncio.wait_for(opening.wait(), 1)
            gateway.password = None
            go_on.set()
            refused = await connecting
            assert refused is not None
            assert refused["Message"] == "password_required"

            gateway.password = "12345"
            result = await session.send("*#13**15##", is_status_request=True)

    assert opened.await_count == 2
    assert isinstance(result, list)
    assert [str(message) for message in result] == [MODEL_REPLY.decode()]


@pytest.mark.asyncio
async def test_a_connect_started_by_the_callback_holds_its_own_refusal() -> None:
    """Two ``connect()`` calls overlap; the later refusal is on hold before its callback's ``send()``."""
    session = numeric_session()
    gateway = session.gateway
    assert gateway is not None
    started: list[asyncio.Task[object]] = []

    def on_auth_error(_error: OWNAuthError) -> None:
        if not started:
            gateway.password = "67890"
            started.append(asyncio.create_task(session.connect()))
        elif len(started) == 1:
            started.append(asyncio.create_task(session.send("*#13**15##")))

    session.on_auth_error = on_auth_error

    async with stream_pair() as first, stream_pair() as second, stream_pair() as third:
        pairs = (first, second, third)
        for pair in pairs:
            pair[2].sendall(LOGIN_REFUSED)
        second_opened = asyncio.Event()

        async def open_connection(*_args: object) -> tuple[asyncio.StreamReader, asyncio.StreamWriter]:
            if opened.await_count == 2:
                second_opened.set()
            return pairs[opened.await_count - 1][:2]

        async def close_after_the_callback_send() -> None:
            await asyncio.wait_for(asyncio.shield(started[1]), 1)

        with (
            patch(OPEN, new=AsyncMock(side_effect=open_connection)) as opened,
            patch.object(first[1], "wait_closed", second_opened.wait),
            patch.object(second[1], "wait_closed", close_after_the_callback_send),
        ):
            result = await session.connect()
            assert result is not None
            assert result["Message"] == "password_error"
            retried = await started[0]
            assert isinstance(retried, dict)
            assert retried["Message"] == "password_error"
            assert await started[1] is None

    assert opened.await_count == 2


@pytest.mark.asyncio
async def test_a_refusal_does_not_come_back_after_a_later_login_succeeded() -> None:
    """The retry from the callback logs in while the refused ``connect()`` still closes its socket."""
    session = numeric_session()
    retry: list[asyncio.Task[object]] = []
    session.on_auth_error = lambda _error: retry.append(asyncio.create_task(session.connect()))

    async with stream_pair() as first, stream_pair() as second, stream_pair() as third:
        first[2].sendall(LOGIN_REFUSED)
        for pair in (second, third):
            pair[2].sendall(LOGIN_ACCEPTED_THEN_REPLY)

        async def close_after_the_retry() -> None:
            retried = await asyncio.wait_for(asyncio.shield(retry[0]), 1)
            assert isinstance(retried, dict)
            assert retried["Success"] is True

        with (
            patch(OPEN, new=AsyncMock(side_effect=[pair[:2] for pair in (first, second, third)])) as opened,
            patch.object(first[1], "wait_closed", close_after_the_retry),
        ):
            result = await session.connect()
            assert result is not None
            assert result["Message"] == "password_error"
            assert session.is_connected and session.is_open
            await session.close()
            answer = await session.send("*#13**15##", is_status_request=True)

    assert opened.await_count == 3
    assert isinstance(answer, list)
    assert [str(message) for message in answer] == [MODEL_REPLY.decode()]


def test_a_session_without_a_gateway_has_no_login_target() -> None:
    assert OWNCommandSession(gateway=None, logger=MagicMock())._login_target() is None


@pytest.mark.asyncio
async def test_stale_overlapping_connect_refusal_does_not_poison_newer_connect() -> None:
    """An older ``connect()`` whose auth refusal arrives after a newer ``connect()`` started
    must not arm a hold under the newer ``connect()``'s credentials.
    """
    session = numeric_session()
    gateway = session.gateway
    assert gateway is not None

    first_started = asyncio.Event()
    allow_first_to_fail = asyncio.Event()

    async with stream_pair() as first, stream_pair() as second, stream_pair() as third:
        second[2].sendall(LOGIN_ACCEPTED_THEN_REPLY)
        third[2].sendall(LOGIN_ACCEPTED_THEN_REPLY)

        async def open_connection(*_args: object) -> tuple[asyncio.StreamReader, asyncio.StreamWriter]:
            if opened.await_count == 1:
                first_started.set()
                await allow_first_to_fail.wait()
                first[2].sendall(LOGIN_REFUSED)
                return first[:2]
            if opened.await_count == 2:
                return second[:2]
            return third[:2]

        with patch(OPEN, new=AsyncMock(side_effect=open_connection)) as opened:
            stale = asyncio.create_task(session.connect())
            await first_started.wait()
            gateway.password = "67890"
            newer = asyncio.create_task(session.connect())
            newer_result = await newer
            assert newer_result is not None and newer_result["Success"] is True

            allow_first_to_fail.set()
            stale_result = await stale
            assert stale_result is not None and stale_result["Message"] == "password_error"
            assert session._refused_login_reason is None
            assert session._refused_login_target is None

            await session.close()
            answer = await session.send("*#13**15##", is_status_request=True)

    assert opened.await_count == 3
    assert isinstance(answer, list)
    assert [str(message) for message in answer] == [MODEL_REPLY.decode()]


@pytest.mark.asyncio
async def test_concurrent_test_connection_failure_during_connect_does_not_arm_hold() -> None:
    """A ``test_connection()`` auth refusal in another task while ``connect()`` is in flight
    must not arm the ``SEND_AUTH_COOLDOWN`` hold.
    """
    session = numeric_session()
    connect_waiting = asyncio.Event()
    allow_connect = asyncio.Event()

    async with stream_pair() as conn_pair, stream_pair() as probe_pair:
        conn_pair[2].sendall(LOGIN_ACCEPTED_THEN_REPLY)
        probe_pair[2].sendall(LOGIN_REFUSED)

        async def open_connection(*_args: object) -> tuple[asyncio.StreamReader, asyncio.StreamWriter]:
            if opened.await_count == 1:
                connect_waiting.set()
                await allow_connect.wait()
                return conn_pair[:2]
            return probe_pair[:2]

        with patch(OPEN, new=AsyncMock(side_effect=open_connection)) as opened:
            conn_task = asyncio.create_task(session.connect())
            await connect_waiting.wait()

            probe_result = await session.test_connection()
            assert probe_result is not None and probe_result["Success"] is False
            assert session._refused_login_reason is None
            assert session._last_reconnect_failure is None

            allow_connect.set()
            conn_result = await conn_task
            assert conn_result is not None and conn_result["Success"] is True
            assert session._refused_login_reason is None


@pytest.mark.asyncio
async def test_superseded_send_connect_failure_does_not_close_newer_live_session() -> None:
    """When an older ``send()``'s ``connect()`` fails after a newer ``connect()`` succeeded
    (e.g. triggered from ``on_auth_error``), ``_locked_send`` must neither close the newer live
    socket nor re-arm the 2 s reconnect cooldown.
    """
    session = numeric_session()
    retry: list[asyncio.Task[object]] = []

    def on_auth_error(_err: object) -> None:
        assert session.gateway is not None
        session.gateway.password = "99999"
        retry.append(asyncio.create_task(session.connect()))

    session.on_auth_error = on_auth_error

    async with stream_pair() as first, stream_pair() as second:
        first[2].sendall(LOGIN_REFUSED)
        second[2].sendall(LOGIN_ACCEPTED_THEN_REPLY)

        async def close_after_the_retry() -> None:
            retried = await asyncio.wait_for(asyncio.shield(retry[0]), 1)
            assert isinstance(retried, dict)
            assert retried["Success"] is True

        with (
            patch(OPEN, new=AsyncMock(side_effect=[first[:2], second[:2]])),
            patch.object(first[1], "wait_closed", close_after_the_retry),
        ):
            res = await session.send("*#13**15##", is_status_request=True, raise_on_error=False)
            assert res is None
            # Newer session is still open and cooldown was NOT re-armed!
            assert session.is_open is True
            assert session._last_reconnect_failure is None
            answer = await session.send("*#13**15##", is_status_request=True)
            assert isinstance(answer, list)
            assert [str(m) for m in answer] == [MODEL_REPLY.decode()]
            await session.close()
